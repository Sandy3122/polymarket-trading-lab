from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.live import Quote, live_quotes
from app.models import Market, Position
from app.paper import PaperTrading
from app.trading import TradeError, evaluate_exits, market_trade, portfolio_view, set_exit


@pytest.fixture()
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    live_quotes.clear()
    with sessionmaker(bind=engine, expire_on_commit=False, class_=Session)() as s:
        yield s
    live_quotes.clear()


def make_market(session: Session) -> Market:
    market = Market(market_key="m1", question="Will BTC rise?", end_time=datetime.now(timezone.utc) + timedelta(minutes=5))
    session.add(market)
    session.flush()
    return market


def quote(yes_bid: str, no_bid: str) -> Quote:
    return Quote(datetime.now(timezone.utc), Decimal(yes_bid), Decimal("100"), Decimal(no_bid), Decimal("100"))


def test_buy_at_derived_ask_then_sell_at_bid_realizes_pnl(session: Session) -> None:
    market, broker = make_market(session), None
    broker = PaperTrading(session, initial_cash=Decimal("1000"))
    live_quotes.record("m1", quote("0.60", "0.38"))  # YES ask = 1 - 0.38 = 0.62
    order = market_trade(session, broker, market, "YES", "BUY", Decimal("10"))
    assert order.average_fill_price == Decimal("0.62")
    live_quotes.record("m1", quote("0.70", "0.28"))
    view = portfolio_view(session, broker)
    assert Decimal(view["unrealized_pnl"]) == Decimal("0.8")  # 10 * (0.70 - 0.62)
    market_trade(session, broker, market, "YES", "SELL", Decimal("10"))
    view = portfolio_view(session, broker)
    assert Decimal(view["realized_pnl"]) == Decimal("0.8") and view["positions"] == []


def test_sell_without_inventory_and_without_quote_are_rejected(session: Session) -> None:
    market = make_market(session)
    broker = PaperTrading(session, initial_cash=Decimal("1000"))
    with pytest.raises(TradeError, match="no live quote"):
        market_trade(session, broker, market, "YES", "BUY", Decimal("1"))
    live_quotes.record("m1", quote("0.60", "0.38"))
    with pytest.raises(TradeError, match="inventory"):
        market_trade(session, broker, market, "YES", "SELL", Decimal("1"))


def test_stop_loss_and_take_profit_close_position(session: Session) -> None:
    market = make_market(session)
    broker = PaperTrading(session, initial_cash=Decimal("1000"))
    live_quotes.record("m1", quote("0.60", "0.38"))
    market_trade(session, broker, market, "YES", "BUY", Decimal("10"))
    with pytest.raises(TradeError, match="below the entry"):
        set_exit(session, market, "YES", Decimal("0.70"), None)
    set_exit(session, market, "YES", Decimal("0.55"), Decimal("0.80"))
    now = datetime.now(timezone.utc)
    assert evaluate_exits(session, broker, market, quote("0.58", "0.40"), now) == []
    assert evaluate_exits(session, broker, market, quote("0.54", "0.44"), now) == ["stop_loss:YES"]
    position = session.query(Position).one()
    assert position.quantity == 0
    assert Decimal(portfolio_view(session, broker)["realized_pnl"]) == Decimal("-0.8")  # 10 * (0.54 - 0.62)
    assert evaluate_exits(session, broker, market, quote("0.54", "0.44"), now) == []  # fires once


def test_auto_exit_guards_new_position_without_overriding_manual(session: Session) -> None:
    from app.trading import apply_auto_exit

    market = make_market(session)
    broker = PaperTrading(session, initial_cash=Decimal("1000"))
    live_quotes.record("m1", quote("0.60", "0.38"))
    market_trade(session, broker, market, "YES", "BUY", Decimal("10"))  # entry 0.62
    assert apply_auto_exit(session, market, "YES", Decimal("0.05"), Decimal("0.10")) is True
    view = portfolio_view(session, broker)["positions"][0]
    assert Decimal(view["stop_loss_price"]) == Decimal("0.57") and Decimal(view["take_profit_price"]) == Decimal("0.72")
    assert apply_auto_exit(session, market, "YES", Decimal("0.10"), Decimal("0")) is False  # active levels kept
    assert apply_auto_exit(session, market, "NO", Decimal("0.05"), Decimal("0")) is False  # no position


def test_runtime_settings_validate_apply_and_persist(session: Session) -> None:
    from app.config import Settings
    from app.models import AppSetting
    from app.runtime_settings import apply_changes, describe, load_overrides

    settings = Settings()
    apply_changes(session, {"max_daily_loss": "55", "worker_require_crypto": "false", "market_keywords": "btc"}, settings)
    assert settings.max_daily_loss == Decimal("55") and settings.worker_require_crypto is False
    assert session.get(AppSetting, "max_daily_loss").value == "55"
    with pytest.raises(ValueError):
        apply_changes(session, {"max_daily_loss": "-1"}, settings)
    with pytest.raises(ValueError, match="below max"):
        apply_changes(session, {"m1_min_price": "0.99", "m1_max_price": "0.9"}, settings)
    with pytest.raises(ValueError, match="not editable"):
        apply_changes(session, {"database_url": "x"}, settings)
    assert settings.max_daily_loss == Decimal("55")
    fresh = Settings()
    load_overrides(session, fresh)
    assert fresh.max_daily_loss == Decimal("55")
    assert {f["key"] for f in describe(fresh)} >= {"max_order_exposure", "market_keywords"}


def _insight(seconds_left: int, yes: str, no: str, *, yes_size: str = "200", ticks=None, age: int = 0):
    from app.config import Settings
    from app.insights import analyze

    now = datetime.now(timezone.utc)
    q = Quote(now - timedelta(seconds=age), Decimal(yes), Decimal(yes_size), Decimal(no), Decimal("200"))
    return analyze(market_id=1, question="BTC?", end_time=now + timedelta(seconds=seconds_left), now=now,
                   quote=q, ticks=ticks or [q], settings=Settings(), equity=Decimal("10000"))


def test_insight_verdicts() -> None:
    assert _insight(600, "0.97", "0.02")["verdict"] == "WAIT"            # too early
    assert _insight(60, "0.60", "0.38")["verdict"] == "WAIT"             # not near-certain
    assert _insight(60, "0.90", "0.02")["verdict"] == "AVOID"            # 8¢ spread
    assert _insight(60, "0.97", "0.02", age=60)["verdict"] == "AVOID"    # stale
    assert _insight(60, "0.97", "0.02", yes_size="5")["verdict"] == "WAIT"  # thin
    buy = _insight(60, "0.97", "0.02")
    assert buy["verdict"] == "BUY" and buy["favourite"] == "YES"
    s = buy["suggestion"]
    assert s["entry"] == 0.98 and s["stop"] == 0.93 and s["shares"] >= 1
    assert s["max_loss_at_stop"] == round(s["shares"] * 0.05, 2)
    assert s["needed_win_rate_with_stop"] == 0.714  # 0.05 / (0.05 + 0.02)


def test_insight_weakening_momentum_waits() -> None:
    now = datetime.now(timezone.utc)
    old = Quote(now - timedelta(seconds=70), Decimal("0.99"), Decimal("200"), Decimal("0.01"), Decimal("200"))
    cur = Quote(now, Decimal("0.96"), Decimal("200"), Decimal("0.03"), Decimal("200"))
    result = _insight(60, "0.96", "0.03", ticks=[old, cur])
    assert result["verdict"] == "WAIT" and "weakening" in " ".join(result["reasons"])


def test_empty_keywords_accept_every_topic() -> None:
    from app.config import Settings
    from app.market_data import MarketSnapshot
    from app.worker import PaperMarketWorker

    now = datetime.now(timezone.utc)
    snap = MarketSnapshot("x", "Will it rain in Paris?", now + timedelta(minutes=10), now, start_time=now - timedelta(minutes=5))
    worker = PaperMarketWorker(settings=Settings(market_keywords=""))
    assert worker._exclusion_reason(snap) is None
    assert PaperMarketWorker(settings=Settings(market_keywords="btc"))._exclusion_reason(snap) == "not_crypto"


def test_second_worker_lock_is_refused() -> None:
    from app.worker_lock import WorkerAlreadyRunning, WorkerLock

    first, second = WorkerLock("sqlite:///lock-test"), WorkerLock("sqlite:///lock-test")
    first.acquire()
    with pytest.raises(WorkerAlreadyRunning, match="already running"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


def test_insight_checks_and_next_steps() -> None:
    early = _insight(600, "0.90", "0.08")
    names = {c["name"]: c["status"] for c in early["checks"]}
    assert names["Timing"] == "warn" and names["Near-certain favourite"] == "fail"
    assert any("entry window" in step for step in early["next_steps"])
    assert any("+5¢" in step for step in early["next_steps"])
    assert _insight(60, "0.97", "0.02")["next_steps"] == []
