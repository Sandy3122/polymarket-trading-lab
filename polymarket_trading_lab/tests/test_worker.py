from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.market_data import BookSnapshot, MarketEvent, MarketSnapshot, Resolution, TradeSnapshot
from app.models import Market, PaperOrder, Position, SystemHealth
from app.worker import PaperMarketWorker
from app.config import Settings


def make_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


class FakeClient:
    def __init__(self, snapshots: list[MarketSnapshot], books: dict[str, BookSnapshot]) -> None:
        self.snapshots = snapshots
        self.books = books

    def list_markets(self, **kwargs: object) -> list[MarketSnapshot]:
        return self.snapshots

    def market_events(self, market: MarketSnapshot):
        yield MarketEvent("market", market.observed_at, market)
        yield MarketEvent("book", self.books[market.market_id].observed_at, self.books[market.market_id])


def test_worker_creates_paper_order_fills_from_sell_trade_and_settles() -> None:
    factory = make_factory()
    now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    snapshot = MarketSnapshot(
        "m1", "Will BTC move?", now + timedelta(minutes=1), now,
        yes_token_id="yes-1", no_token_id="no-1", condition_id="condition-1",
    )
    book = BookSnapshot("m1", now - timedelta(seconds=1), Decimal("0.97"), Decimal("2"), None, Decimal("0"))
    worker = PaperMarketWorker(
        session_factory=factory,
        client=FakeClient([snapshot], {"m1": book}),
        settings=Settings(initial_cash=Decimal("100"), max_order_exposure=Decimal("10"), worker_require_crypto=False),
    )

    stats = __import__("asyncio").run(worker.run_once())
    with factory() as session:
        market = session.scalar(select(Market).where(Market.market_key == "m1"))
        assert market is not None
        order = session.scalar(select(PaperOrder).where(PaperOrder.market_id == market.id))
        assert order is not None
        assert order.status == "open"
        assert stats.orders_created == 1

    trade_time = now + timedelta(seconds=1)
    fill_stats = worker.process_event(
        MarketEvent("trade", trade_time, TradeSnapshot("m1", "yes-1", "SELL", Decimal("0.97"), Decimal("3"), trade_time))
    )
    assert fill_stats.fills == 1

    resolution_time = now + timedelta(seconds=2)
    settlement_stats = worker.process_event(
        MarketEvent("resolution", resolution_time, Resolution("m1", "YES", resolution_time))
    )
    assert settlement_stats.settlements == 1

    with factory() as session:
        position = session.scalar(select(Position).where(Position.market_id == market.id, Position.token == "YES"))
        assert position is not None
        assert position.quantity == Decimal("0")
        assert session.get(Market, market.id).status == "settled"


def test_worker_deduplicates_same_trade_event() -> None:
    factory = make_factory()
    now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    market = MarketSnapshot("m1", "Question", now + timedelta(minutes=1), now, yes_token_id="yes-1", no_token_id="no-1")
    book = BookSnapshot("m1", now - timedelta(seconds=1), Decimal("0.97"), Decimal("1"))
    worker = PaperMarketWorker(session_factory=factory, client=FakeClient([market], {"m1": book}), settings=Settings(initial_cash=Decimal("100"), worker_require_crypto=False))
    __import__("asyncio").run(worker.run_once())
    trade_time = now + timedelta(seconds=1)
    event = MarketEvent("trade", trade_time, TradeSnapshot("m1", "yes-1", "SELL", Decimal("0.97"), Decimal("2"), trade_time))
    assert worker.process_event(event).fills == 1
    assert worker.process_event(event).fills == 0
    restarted_worker = PaperMarketWorker(session_factory=factory, client=FakeClient([market], {"m1": book}), settings=Settings(initial_cash=Decimal("100"), worker_require_crypto=False))
    assert restarted_worker.process_event(event).fills == 0


def test_worker_rejects_stale_book_before_creating_an_order() -> None:
    factory = make_factory()
    now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    market = MarketSnapshot("stale", "Question", now + timedelta(minutes=1), now, yes_token_id="yes", no_token_id="no")
    worker = PaperMarketWorker(
        session_factory=factory,
        settings=Settings(initial_cash=Decimal("100"), worker_require_crypto=False, max_market_data_age_seconds=30),
    )

    worker.process_event(MarketEvent("market", now, market))
    stats = worker.process_event(
        MarketEvent(
            "book",
            now,
            BookSnapshot("stale", now - timedelta(minutes=2), Decimal("0.97"), Decimal("5")),
        )
    )

    assert stats.orders_created == 0
    with factory() as session:
        assert session.scalar(select(PaperOrder).where(PaperOrder.market_id == 1)) is None


def test_worker_records_exclusion_reasons_for_unselected_markets() -> None:
    now = datetime.now(timezone.utc)

    def snap(mid: str, slug: str, minutes: int | None, question: str = "Up or Down") -> MarketSnapshot:
        end = now + timedelta(minutes=5)
        start = None if minutes is None else end - timedelta(minutes=minutes)
        return MarketSnapshot(mid, question, end, now, slug=slug, start_time=start, yes_token_id=f"y{mid}", no_token_id=f"n{mid}")

    snaps = [
        snap("a", "xrp-updown-15m-1", 15),
        snap("b", "btc-updown-5m-1", 5),
        snap("c", "btc-above-80000", 1440),
        snap("d", "btc-strike", None),
        snap("e", "election-2028", 15, question="Who wins?"),
    ]
    factory = make_factory()
    worker = PaperMarketWorker(session_factory=factory, client=FakeClient(snaps, {}), settings=Settings())
    selected, _ = worker.sync_markets()

    assert [m.market_id for m in selected] == ["a"]
    with factory() as session:
        message = session.execute(select(SystemHealth)).scalars().one().details
    assert "selected 1" in message
    assert "duration_outside_window=2" in message
    assert "missing_start_time=1" in message
    assert "not_crypto=1" in message
