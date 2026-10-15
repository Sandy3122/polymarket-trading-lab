"""Manual paper trades, stop-loss / take-profit exits, and mark-to-market views.

Quotes only carry best bids, so the ask of a token is derived from the
opposite token's bid (``ask = 1 - opposite bid``).  Every fill here is a
paper fill; nothing reaches a live venue.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .live import Quote, live_quotes
from .models import Market, PaperOrder, Position, PositionExit
from .paper import PaperTrading

MAX_QUOTE_AGE = timedelta(seconds=30)
ZERO = Decimal("0")


class TradeError(ValueError):
    """A manual trade or exit configuration that cannot be accepted."""


def _risk_free(broker: PaperTrading) -> PaperTrading:
    # Closing a position reduces exposure, so it must not be blocked by the
    # open-risk limits (e.g. the daily-loss limit would otherwise trap a loser).
    return PaperTrading(broker.session, initial_cash=broker.initial_cash)


def _position(session: Session, market_id: int, token: str) -> Position | None:
    return session.scalar(select(Position).where(Position.market_id == market_id, Position.token == token))


def market_trade(
    session: Session,
    broker: PaperTrading,
    market: Market,
    token: str,
    side: str,
    quantity: Decimal,
    *,
    now: datetime | None = None,
) -> PaperOrder:
    """Fill a paper order immediately at the current quote (BUY at ask, SELL at bid)."""

    now = now or datetime.now(timezone.utc)
    token, side = token.upper(), side.upper()
    quote = live_quotes.latest(market.market_key)
    if quote is None:
        raise TradeError("no live quote for this market yet; start the worker first")
    if now - quote.observed_at > MAX_QUOTE_AGE:
        raise TradeError("live quote is stale")
    price = quote.ask(token) if side == "BUY" else quote.bid(token)
    if price is None or price <= 0:
        raise TradeError(f"no {'ask' if side == 'BUY' else 'bid'} available for {token}")
    if side == "SELL":
        held = _position(session, market.id, token)
        if held is None or Decimal(str(held.quantity)) < quantity:
            raise TradeError("insufficient paper inventory")
        order = _risk_free(broker).submit_order(market, token, side, price, quantity, now=now, auto_fill=True)
    else:
        order = broker.submit_order(market, token, side, price, quantity, now=now, auto_fill=True)
    if order.status == "rejected":
        raise TradeError(order.reject_reason or "order rejected")
    return order


def set_exit(
    session: Session,
    market: Market,
    token: str,
    stop_loss: Decimal | None,
    take_profit: Decimal | None,
) -> PositionExit:
    token = token.upper()
    held = _position(session, market.id, token)
    if held is None or Decimal(str(held.quantity)) <= 0:
        raise TradeError("no open position to protect")
    entry = Decimal(str(held.average_entry_price))
    for value in (stop_loss, take_profit):
        if value is not None and not ZERO < value < 1:
            raise TradeError("exit prices must be between 0 and 1")
    if stop_loss is not None and stop_loss >= entry:
        raise TradeError(f"stop loss must be below the entry price ({entry:.4f})")
    if take_profit is not None and take_profit <= entry:
        raise TradeError(f"take profit must be above the entry price ({entry:.4f})")
    row = session.scalar(select(PositionExit).where(PositionExit.market_id == market.id, PositionExit.token == token))
    if row is None:
        row = PositionExit(market_id=market.id, token=token)
        session.add(row)
    row.stop_loss_price, row.take_profit_price = stop_loss, take_profit
    row.status, row.triggered_at = "active", None
    session.flush()
    return row


def apply_auto_exit(session: Session, market: Market, token: str, stop_offset: Decimal, take_profit_offset: Decimal) -> bool:
    """Guard a freshly filled strategy position; never overrides active (e.g. manual) levels."""

    if stop_offset <= 0 and take_profit_offset <= 0:
        return False
    token = token.upper()
    existing = session.scalar(select(PositionExit).where(PositionExit.market_id == market.id, PositionExit.token == token))
    held = _position(session, market.id, token)
    if (existing is not None and existing.status == "active") or held is None or Decimal(str(held.quantity)) <= 0:
        return False
    entry = Decimal(str(held.average_entry_price))
    stop = entry - stop_offset if stop_offset > 0 and entry - stop_offset > 0 else None
    target = entry + take_profit_offset if 0 < take_profit_offset and entry + take_profit_offset < 1 else None
    if stop is None and target is None:
        return False
    set_exit(session, market, token, stop, target)
    return True


def clear_exit(session: Session, market: Market, token: str) -> None:
    row = session.scalar(select(PositionExit).where(PositionExit.market_id == market.id, PositionExit.token == token.upper()))
    if row is not None:
        session.delete(row)
        session.flush()


def evaluate_exits(session: Session, broker: PaperTrading, market: Market, quote: Quote, now: datetime) -> list[str]:
    """Sell any guarded position whose bid crossed its stop-loss or take-profit."""

    triggered: list[str] = []
    exits = session.scalars(
        select(PositionExit).where(PositionExit.market_id == market.id, PositionExit.status == "active")
    )
    for row in exits:
        held = _position(session, market.id, row.token)
        quantity = Decimal(str(held.quantity)) if held is not None else ZERO
        bid = quote.bid(row.token)
        if quantity <= 0 or bid is None or bid <= 0:
            continue
        reason = None
        if row.stop_loss_price is not None and bid <= Decimal(str(row.stop_loss_price)):
            reason = "stop_loss"
        elif row.take_profit_price is not None and bid >= Decimal(str(row.take_profit_price)):
            reason = "take_profit"
        if reason is None:
            continue
        order = _risk_free(broker).submit_order(market, row.token, "SELL", bid, quantity, now=now, auto_fill=True)
        if order.status == "filled":
            row.status, row.triggered_at = reason, now
            triggered.append(f"{reason}:{row.token}")
    return triggered


def portfolio_view(session: Session, broker: PaperTrading) -> dict[str, object]:
    """Cash, realized/unrealized P&L, equity and guarded positions."""

    cash = broker.cash_balance()
    realized = broker.realized_pnl()
    positions = []
    market_value = ZERO
    unrealized_total = ZERO
    for position in session.scalars(select(Position).order_by(Position.market_id, Position.token)):
        quantity = Decimal(str(position.quantity))
        if quantity <= 0:
            continue
        market = session.get(Market, position.market_id)
        quote = live_quotes.latest(market.market_key) if market else None
        entry = Decimal(str(position.average_entry_price))
        mark = quote.bid(position.token) if quote else None
        value = quantity * (mark if mark is not None else entry)
        unrealized = quantity * (mark - entry) if mark is not None else ZERO
        market_value += value
        unrealized_total += unrealized
        guard = session.scalar(
            select(PositionExit).where(PositionExit.market_id == position.market_id, PositionExit.token == position.token)
        )
        positions.append({
            "market_id": position.market_id,
            "market_key": market.market_key if market else None,
            "question": market.question if market else None,
            "token": position.token,
            "quantity": str(quantity),
            "average_entry_price": str(entry),
            "mark_price": str(mark) if mark is not None else None,
            "market_value": str(value),
            "unrealized_pnl": str(unrealized),
            "realized_pnl": str(position.realized_pnl),
            "stop_loss_price": str(guard.stop_loss_price) if guard and guard.stop_loss_price is not None else None,
            "take_profit_price": str(guard.take_profit_price) if guard and guard.take_profit_price is not None else None,
            "exit_status": guard.status if guard else None,
        })
    return {
        "cash": str(cash),
        "realized_pnl": str(realized),
        "unrealized_pnl": str(unrealized_total),
        "market_value": str(market_value),
        "equity": str(cash + market_value),
        "total_pnl": str(realized + unrealized_total),
        "positions": positions,
    }
