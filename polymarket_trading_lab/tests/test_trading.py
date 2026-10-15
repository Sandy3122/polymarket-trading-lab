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
