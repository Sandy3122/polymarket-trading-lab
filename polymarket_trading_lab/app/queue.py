"""Deterministic maker queue and fill models for paper trading.

Public data cannot reveal our exact exchange queue position. These models make
that uncertainty explicit instead of treating every matching trade as our
fill. Each paper order records the selected model and its remaining estimated
volume ahead of us.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class QueueModel(StrEnum):
    OPTIMISTIC = "optimistic"
    BASELINE = "baseline"
    CONSERVATIVE = "conservative"


@dataclass(frozen=True)
class QueueState:
    model: QueueModel
    initial_ahead: Decimal
    remaining_ahead: Decimal


def initial_queue_ahead(model: QueueModel | str, visible_bid_size: Decimal) -> Decimal:
    """Estimate volume ahead of a newly placed maker order.

    Optimistic assumes first-in-queue. Baseline uses visible bid depth at the
    time of placement. Conservative doubles that depth to account for hidden
    or unobserved resting interest and latency.
    """

    selected = QueueModel(model)
    size = max(Decimal("0"), Decimal(str(visible_bid_size)))
    if selected is QueueModel.OPTIMISTIC:
        return Decimal("0")
    if selected is QueueModel.CONSERVATIVE:
        return size * Decimal("2")
    return size


def consume_queue(state: QueueState, trade_size: Decimal) -> tuple[QueueState, Decimal]:
    """Consume a public matching trade and return (new state, our fill)."""

    available = max(Decimal("0"), Decimal(str(trade_size)))
    consumed = min(state.remaining_ahead, available)
    remaining_trade = available - consumed
    new_state = QueueState(
        model=state.model,
        initial_ahead=state.initial_ahead,
        remaining_ahead=state.remaining_ahead - consumed,
    )
    return new_state, remaining_trade
