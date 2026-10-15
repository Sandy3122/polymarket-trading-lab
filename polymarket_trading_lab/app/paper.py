"""Virtual paper order lifecycle, journal, and deterministic settlement."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LedgerEntry, Market, PaperFill, PaperOrder, Position, utc_now
from .risk import RiskChecker


def _decimal(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value))


def _aware(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError("paper timestamps must be timezone-aware")
    return result.astimezone(timezone.utc)


class PaperTrading:
    """A local paper broker with a full-fill-at-limit deterministic model."""

    def __init__(
        self,
        session: Session,
        initial_cash: Decimal = Decimal("10000"),
        risk_checker: RiskChecker | None = None,
    ) -> None:
        self.session = session
        self.initial_cash = _decimal(initial_cash)
        self.risk_checker = risk_checker

    def _ensure_funded(self, now: datetime) -> None:
        exists = self.session.scalar(
            select(LedgerEntry.id).where(LedgerEntry.entry_type == "initial_funding")
        )
        if exists is None:
            self.session.add(
                LedgerEntry(
                    entry_type="initial_funding",
                    debit_account="cash",
                    credit_account="paper_capital",
                    asset="USD",
                    amount=self.initial_cash,
                    description="paper account opening balance",
                    created_at=now,
                )
            )
            self.session.flush()

    def cash_balance(self) -> Decimal:
        self._ensure_funded(datetime.now(timezone.utc))
        balance = Decimal("0")
        entries = self.session.scalars(select(LedgerEntry).where(LedgerEntry.asset == "USD"))
        for entry in entries:
            if entry.debit_account == "cash":
                balance += _decimal(entry.amount)
            if entry.credit_account == "cash":
                balance -= _decimal(entry.amount)
        return balance

    def submit_order(
        self,
        market: Market,
        token: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        *,
        now: datetime | None = None,
        auto_fill: bool = False,
    ) -> PaperOrder:
        now_utc = _aware(now)
        price = _decimal(price)
        quantity = _decimal(quantity)
        token = token.upper()
        side = side.upper()
        if token not in {"YES", "NO"}:
            raise ValueError("token must be YES or NO")
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if price <= 0 or price > 1 or quantity <= 0:
            raise ValueError("price must be in (0, 1] and quantity must be positive")
        if market.status != "open":
            raise ValueError("market is not open")
        if now_utc >= _aware(market.end_time):
            raise ValueError("market has ended")

        self._ensure_funded(now_utc)
        order = PaperOrder(
            client_order_id=str(uuid4()),
            market=market,
            token=token,
            side=side,
            price=price,
            quantity=quantity,
            filled_quantity=Decimal("0"),
            status="open",
            created_at=now_utc,
            updated_at=now_utc,
        )
        self.session.add(order)
        self.session.flush()

        if self.risk_checker is not None:
            positions = list(self.session.scalars(select(Position)))
            open_orders = list(self.session.scalars(select(PaperOrder).where(PaperOrder.status.in_(("open", "partially_filled")))))
            if side == "SELL":
                held = next((position for position in positions if position.market_id == market.id and position.token == token), None)
                if held is None or _decimal(held.quantity) < quantity:
                    order.status = "rejected"
                    order.reject_reason = "insufficient paper inventory"
                    self.session.flush()
                    return order
            result = self.risk_checker.check_order(order, positions, open_orders, self.realized_pnl_today(now_utc))
            if not result.allowed:
                order.status = "rejected"
                order.reject_reason = result.reason
                self.session.flush()
                return order

        if auto_fill:
            self.fill_order(order, now=now_utc)
        return order

    def fill_order(
        self,
        order: PaperOrder,
        *,
        now: datetime | None = None,
        price: Decimal | None = None,
        quantity: Decimal | None = None,
        fee: Decimal = Decimal("0"),
        event_id: str | None = None,
    ) -> PaperFill:
        if order.status not in {"open", "partially_filled"}:
            raise ValueError(f"order is not fillable: {order.status}")
        if event_id is not None:
            existing = self.session.scalar(select(PaperFill).where(PaperFill.event_id == event_id))
            if existing is not None:
                return existing
        if order.market.status != "open" or _aware(order.market.end_time) <= _aware(now):
            raise ValueError("market is no longer open for fills")
        fill_price = _decimal(price if price is not None else order.price)
        remaining = _decimal(order.quantity) - _decimal(order.filled_quantity)
        fill_quantity = _decimal(quantity if quantity is not None else remaining)
        if fill_price <= 0 or fill_price > 1 or fill_quantity <= 0 or fill_quantity > remaining:
            raise ValueError("invalid deterministic fill")
        fee = _decimal(fee)
        if fee < 0:
            raise ValueError("fee cannot be negative")

        filled_at = _aware(now)
        self._ensure_funded(filled_at)
        if order.side == "BUY" and self.cash_balance() < fill_quantity * fill_price + fee:
            raise ValueError("insufficient paper cash")
        if order.side == "SELL":
            position = self.session.scalar(
                select(Position).where(Position.market_id == order.market_id, Position.token == order.token)
            )
            if position is None or _decimal(position.quantity) < fill_quantity:
                raise ValueError("cannot sell more paper inventory than held")
        fill = PaperFill(
            order=order,
            quantity=fill_quantity,
            price=fill_price,
            fee=fee,
            event_id=event_id,
            filled_at=filled_at,
        )
        self.session.add(fill)
        order.filled_quantity = _decimal(order.filled_quantity) + fill_quantity
        total_filled_value = sum((_decimal(item.quantity) * _decimal(item.price) for item in order.fills), Decimal("0"))
        order.average_fill_price = total_filled_value / _decimal(order.filled_quantity)
        order.status = "filled" if order.filled_quantity == order.quantity else "partially_filled"
        order.updated_at = filled_at
        self.session.flush()
        self._apply_fill(order, fill)
        return fill

    def _apply_fill(self, order: PaperOrder, fill: PaperFill) -> None:
        cost = _decimal(fill.quantity) * _decimal(fill.price) + _decimal(fill.fee)
        cash_account = "cash"
        position_account = f"position:{order.market_id}:{order.token}"
        if order.side == "BUY":
            cash_debit, cash_credit = "paper_expense", cash_account
            position_debit, position_credit = position_account, "paper_inventory"
        else:
            cash_debit, cash_credit = cash_account, "paper_income"
            position_debit, position_credit = "paper_inventory", position_account

        self.session.add(
            LedgerEntry(
                entry_type="trade_cash",
                debit_account=cash_debit,
                credit_account=cash_credit,
                asset="USD",
                amount=cost,
                market_id=order.market_id,
                order_id=order.id,
                description=f"{order.side} {order.token} cash leg",
            )
        )
        self.session.add(
            LedgerEntry(
                entry_type="trade_position",
                debit_account=position_debit,
                credit_account=position_credit,
                asset=order.token,
                amount=_decimal(fill.quantity),
                market_id=order.market_id,
                order_id=order.id,
                description=f"{order.side} {order.token} position leg",
            )
        )

        position = self.session.scalar(
            select(Position).where(Position.market_id == order.market_id, Position.token == order.token)
        )
        if position is None:
            position = Position(
                market_id=order.market_id,
                token=order.token,
                quantity=Decimal("0"),
                average_entry_price=Decimal("0"),
                realized_pnl=Decimal("0"),
            )
            self.session.add(position)
            self.session.flush()

        old_quantity = _decimal(position.quantity)
        if order.side == "BUY":
            new_quantity = old_quantity + _decimal(fill.quantity)
            old_cost = old_quantity * _decimal(position.average_entry_price)
            position.average_entry_price = (old_cost + _decimal(fill.quantity) * _decimal(fill.price) + _decimal(fill.fee)) / new_quantity
            position.quantity = new_quantity
        else:
            if _decimal(fill.quantity) > old_quantity:
                raise ValueError("cannot sell more paper inventory than held")
            position.quantity = old_quantity - _decimal(fill.quantity)
            position.realized_pnl = _decimal(position.realized_pnl) + (
                _decimal(fill.quantity) * (_decimal(fill.price) - _decimal(position.average_entry_price)) - _decimal(fill.fee)
            )
            realized = _decimal(fill.quantity) * (_decimal(fill.price) - _decimal(position.average_entry_price)) - _decimal(fill.fee)
            self.session.add(
                LedgerEntry(
                    entry_type="realized_pnl",
                    debit_account="pnl",
                    credit_account="equity",
                    asset="PNL",
                    amount=realized,
                    market_id=order.market_id,
                    order_id=order.id,
                    description="realized paper P&L on sale",
                    created_at=fill.filled_at,
                )
            )
        self.session.flush()

    def cancel_order(self, order: PaperOrder, *, now: datetime | None = None) -> None:
        if order.status not in {"open", "partially_filled"}:
            raise ValueError(f"order is not cancellable: {order.status}")
        order.status = "cancelled"
        order.updated_at = _aware(now)
        self.session.flush()

    def realized_pnl(self) -> Decimal:
        entries = self.session.scalars(select(LedgerEntry).where(LedgerEntry.asset == "PNL"))
        return sum((_decimal(entry.amount) for entry in entries), Decimal("0"))

    def realized_pnl_today(self, as_of: datetime | None = None) -> Decimal:
        as_of_utc = _aware(as_of)
        start = as_of_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        entries = self.session.scalars(
            select(LedgerEntry).where(LedgerEntry.asset == "PNL", LedgerEntry.created_at >= start)
        )
        return sum((_decimal(entry.amount) for entry in entries), Decimal("0"))

    def settle_market(
        self,
        market: Market,
        winning_token: str,
        *,
        now: datetime | None = None,
        payout_per_share: Decimal = Decimal("1"),
    ) -> Decimal:
        winning_token = winning_token.upper()
        payout_per_share = _decimal(payout_per_share)
        if winning_token not in {"YES", "NO"} or not 0 <= payout_per_share <= 1:
            raise ValueError("invalid settlement")
        settled_at = _aware(now)
        payout_total = Decimal("0")
        if market.status == "settled":
            return Decimal("0")
        for order in self.session.scalars(
            select(PaperOrder).where(PaperOrder.market_id == market.id, PaperOrder.status.in_(("open", "partially_filled")))
        ):
            order.status = "cancelled"
            order.updated_at = settled_at
        positions = list(self.session.scalars(select(Position).where(Position.market_id == market.id)))
        for position in positions:
            quantity = _decimal(position.quantity)
            if quantity <= 0:
                continue
            payout = quantity * payout_per_share if position.token == winning_token else Decimal("0")
            payout_total += payout
            self.session.add(
                LedgerEntry(
                    entry_type="settlement_position",
                    debit_account="settlement",
                    credit_account=f"position:{market.id}:{position.token}",
                    asset=position.token,
                    amount=quantity,
                    market_id=market.id,
                    description="remove settled token position",
                    created_at=settled_at,
                )
            )
            if payout:
                self.session.add(
                    LedgerEntry(
                        entry_type="settlement_cash",
                        debit_account="cash",
                        credit_account="settlement",
                        asset="USD",
                        amount=payout,
                        market_id=market.id,
                        description="winning token payout",
                        created_at=settled_at,
                    )
                )
            realized = payout - quantity * _decimal(position.average_entry_price)
            position.realized_pnl = _decimal(position.realized_pnl) + realized
            self.session.add(
                LedgerEntry(
                    entry_type="realized_pnl",
                    debit_account="pnl",
                    credit_account="equity",
                    asset="PNL",
                    amount=realized,
                    market_id=market.id,
                    description="realized paper P&L on settlement",
                    created_at=settled_at,
                )
            )
            position.quantity = Decimal("0")
            position.average_entry_price = Decimal("0")
            position.updated_at = settled_at

        market.status = "settled"
        market.winning_token = winning_token
        market.settled_at = settled_at
        self.session.flush()
        return payout_total
