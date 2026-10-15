"""Execution boundary.

The strategy never talks to a broker directly.  Paper execution is available;
the live adapter is an explicit refusal until it is implemented and manually
enabled in a separately reviewed change.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy.orm import Session

from .models import Market, PaperOrder
from .paper import PaperTrading


@dataclass(frozen=True)
class ExecutionIntent:
    market_id: int
    token: str
    side: str
    price: Decimal
    quantity: Decimal
    reason: str


class ExecutionAdapter(Protocol):
    def submit(self, intent: ExecutionIntent, *, now: datetime | None = None) -> PaperOrder | object:
        """Submit an intent through this adapter."""


class PaperExecutionAdapter:
    def __init__(self, session: Session, broker: PaperTrading) -> None:
        self.session = session
        self.broker = broker

    def submit(self, intent: ExecutionIntent, *, now: datetime | None = None) -> PaperOrder:
        market = self.session.get(Market, intent.market_id)
        if market is None:
            raise ValueError("market not found")
        return self.broker.submit_order(
            market,
            intent.token,
            intent.side,
            intent.price,
            intent.quantity,
            now=now,
            auto_fill=False,
        )


class LiveExecutionDisabled(RuntimeError):
    pass


class DisabledLiveExecutionAdapter:
    """Safety placeholder: there is intentionally no live order path yet."""

    def submit(self, intent: ExecutionIntent, *, now: datetime | None = None) -> object:
        raise LiveExecutionDisabled(
            "live execution is disabled; use PaperExecutionAdapter. No wallet or live API is configured."
        )
