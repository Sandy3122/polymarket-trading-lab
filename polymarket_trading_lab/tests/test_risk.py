from dataclasses import dataclass
from decimal import Decimal

from app.risk import RiskChecker, RiskLimits


@dataclass
class Position:
    market_id: int
    quantity: Decimal
    average_entry_price: Decimal


@dataclass
class Order:
    market_id: int
    price: Decimal
    quantity: Decimal
    side: str = "BUY"
    filled_quantity: Decimal = Decimal("0")


def test_risk_allows_order_within_all_limits() -> None:
    checker = RiskChecker(
        RiskLimits(
            max_order_exposure=Decimal("100"),
            max_market_exposure=Decimal("200"),
            max_total_exposure=Decimal("300"),
            max_daily_loss=Decimal("25"),
        )
    )
    result = checker.check_order(
        Order(1, Decimal("0.50"), Decimal("20")),
        [Position(1, Decimal("50"), Decimal("1"))],
        realized_pnl_today=Decimal("-10"),
    )

    assert result.allowed
    assert result.order_exposure == Decimal("10.00")
    assert result.market_exposure == Decimal("60.00")


def test_risk_rejects_order_and_daily_loss_boundaries() -> None:
    checker = RiskChecker(
        RiskLimits(
            max_order_exposure=Decimal("10"),
            max_market_exposure=Decimal("100"),
            max_total_exposure=Decimal("100"),
            max_daily_loss=Decimal("25"),
        )
    )
    order_result = checker.check_order(Order(1, Decimal("0.50"), Decimal("21")), [])
    loss_result = checker.check_order(
        Order(1, Decimal("0.50"), Decimal("1")), [], realized_pnl_today=Decimal("-25.01")
    )

    assert not order_result.allowed
    assert order_result.reason == "order exposure limit exceeded"
    assert not loss_result.allowed
    assert loss_result.reason == "daily loss limit exceeded"
