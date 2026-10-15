from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import LedgerEntry, Market, PaperFill, Position
from app.paper import PaperTrading


def make_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_paper_order_lifecycle_and_winning_settlement() -> None:
    session = make_session()
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    market = Market(
        market_key="will-it-happen",
        question="Will it happen?",
        end_time=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
    )
    session.add(market)
    session.flush()
    broker = PaperTrading(session, initial_cash=Decimal("100"))

    order = broker.submit_order(
        market,
        "YES",
        "BUY",
        Decimal("0.40"),
        Decimal("10"),
        now=now,
    )
    assert order.status == "open"
    fill = broker.fill_order(order, now=now)
    session.commit()

    assert order.status == "filled"
    assert fill.price == Decimal("0.40")
    position = session.scalar(select(Position).where(Position.market_id == market.id, Position.token == "YES"))
    assert position is not None
    assert position.quantity == Decimal("10.00000000")
    assert broker.cash_balance() == Decimal("96.00")

    payout = broker.settle_market(market, "YES", now=now)
    session.commit()

    assert payout == Decimal("10")
    assert market.status == "settled"
    assert market.winning_token == "YES"
    assert position.quantity == Decimal("0")
    assert position.realized_pnl == Decimal("6.00000000")
    assert broker.cash_balance() == Decimal("106.00")
    assert {entry.entry_type for entry in session.scalars(select(LedgerEntry))} >= {
        "initial_funding",
        "trade_cash",
        "trade_position",
        "settlement_position",
        "settlement_cash",
    }


def test_open_order_can_be_cancelled_without_a_fill() -> None:
    session = make_session()
    market = Market(
        market_key="cancel-me",
        question="Will it happen?",
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    session.add(market)
    session.flush()
    broker = PaperTrading(session)
    order = broker.submit_order(
        market, "NO", "BUY", Decimal("0.25"), Decimal("2"), now=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    broker.cancel_order(order)

    assert order.status == "cancelled"
    assert order.fills == []


def test_buy_cannot_spend_beyond_cash() -> None:
    session = make_session()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    market = Market(market_key="funds", question="Enough?", end_time=now + timedelta(days=1))
    session.add(market)
    session.flush()
    broker = PaperTrading(session, initial_cash=Decimal("1"))
    order = broker.submit_order(market, "YES", "BUY", Decimal("1"), Decimal("2"), now=now)

    try:
        broker.fill_order(order, now=now)
    except ValueError as exc:
        assert str(exc) == "insufficient paper cash"
    else:
        raise AssertionError("an underfunded BUY was filled")

    session.rollback()
    assert not session.scalars(select(PaperFill)).all()


def test_oversell_is_rejected_before_persisting_a_fill() -> None:
    session = make_session()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    market = Market(market_key="inventory", question="Held?", end_time=now + timedelta(days=1))
    session.add(market)
    session.flush()
    broker = PaperTrading(session)
    order = broker.submit_order(market, "NO", "SELL", Decimal("0.25"), Decimal("1"), now=now)

    try:
        broker.fill_order(order, now=now)
    except ValueError as exc:
        assert str(exc) == "cannot sell more paper inventory than held"
    else:
        raise AssertionError("an unsupported SELL was filled")

    session.rollback()
    assert not session.scalars(select(PaperFill)).all()


def test_settlement_cancels_open_orders() -> None:
    session = make_session()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    market = Market(market_key="terminal", question="Done?", end_time=now + timedelta(days=1))
    session.add(market)
    session.flush()
    broker = PaperTrading(session)
    order = broker.submit_order(market, "YES", "BUY", Decimal("0.97"), Decimal("1"), now=now)

    broker.settle_market(market, "YES", now=now + timedelta(minutes=1))

    assert order.status == "cancelled"
