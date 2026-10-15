"""Small, deterministic risk checks for paper orders."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Protocol


class PositionLike(Protocol):
    market_id: int | str
    quantity: Decimal
    average_entry_price: Decimal


class OrderLike(Protocol):
    market_id: int | str
    side: str
    price: Decimal
    quantity: Decimal
    filled_quantity: Decimal


@dataclass(frozen=True)
class RiskLimits:
    max_order_exposure: Decimal = Decimal("250")
    max_market_exposure: Decimal = Decimal("1000")
    max_total_exposure: Decimal = Decimal("5000")
    max_daily_loss: Decimal = Decimal("100")


@dataclass(frozen=True)
class RiskResult:
    allowed: bool
    reason: str
    order_exposure: Decimal
    market_exposure: Decimal
    total_exposure: Decimal
    daily_loss: Decimal


class RiskChecker:
    """Check gross notional and realized daily loss before accepting an order."""

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    @staticmethod
    def _exposure(position: PositionLike) -> Decimal:
        return abs(Decimal(str(position.quantity)) * Decimal(str(position.average_entry_price)))

    def check_order(
        self,
        order: OrderLike,
        positions: Iterable[PositionLike],
        open_orders: Iterable[OrderLike] = (),
        realized_pnl_today: Decimal = Decimal("0"),
    ) -> RiskResult:
        positions = list(positions)
        open_orders = [candidate for candidate in open_orders if candidate is not order]
        order_exposure = abs(Decimal(str(order.price)) * Decimal(str(order.quantity)))
        position_exposures = [self._exposure(position) for position in positions]
        pending_exposures = [
            abs(Decimal(str(candidate.price)) * (Decimal(str(candidate.quantity)) - Decimal(str(candidate.filled_quantity))))
            for candidate in open_orders
            if candidate.side == "BUY" and getattr(candidate, "status", "open") in {"open", "partially_filled"}
        ]
        pending_exposures = [value for value in pending_exposures if value > 0]
        current_order_exposure = order_exposure if order.side == "BUY" else Decimal("0")
        existing_market_exposure = sum(
            (exposure for position, exposure in zip(positions, position_exposures) if position.market_id == order.market_id),
            Decimal("0"),
        )
        pending_market_exposure = sum(
            (abs(Decimal(str(candidate.price)) * (Decimal(str(candidate.quantity)) - Decimal(str(candidate.filled_quantity))))
             for candidate in open_orders
             if candidate.side == "BUY" and candidate.market_id == order.market_id
             and getattr(candidate, "status", "open") in {"open", "partially_filled"}),
            Decimal("0"),
        )
        market_exposure = existing_market_exposure + pending_market_exposure + current_order_exposure
        total_exposure = sum(position_exposures, Decimal("0")) + sum(pending_exposures, Decimal("0")) + current_order_exposure
        daily_loss = max(Decimal("0"), -Decimal(str(realized_pnl_today)))

        checks = (
            (order_exposure <= self.limits.max_order_exposure, "order exposure limit exceeded"),
            (market_exposure <= self.limits.max_market_exposure, "market exposure limit exceeded"),
            (total_exposure <= self.limits.max_total_exposure, "total exposure limit exceeded"),
            (daily_loss <= self.limits.max_daily_loss, "daily loss limit exceeded"),
        )
        for allowed, reason in checks:
            if not allowed:
                return RiskResult(False, reason, order_exposure, market_exposure, total_exposure, daily_loss)

        return RiskResult(True, "allowed", order_exposure, market_exposure, total_exposure, daily_loss)
