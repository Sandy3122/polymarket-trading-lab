"""In-memory live quote store shared by the worker and the dashboard API.

The worker and the API run in one process, so a small lock-guarded ring buffer
is enough to drive the live chart and mark open positions to market.  History
is intentionally not persisted: it is a view of the current session.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

MAX_TICKS = 900


@dataclass(frozen=True)
class Quote:
    observed_at: datetime
    yes_bid: Decimal | None
    yes_bid_size: Decimal
    no_bid: Decimal | None
    no_bid_size: Decimal

    @property
    def yes_ask(self) -> Decimal | None:
        """Binary-market identity: buying YES is selling NO, so ask = 1 - NO bid."""

        return Decimal("1") - self.no_bid if self.no_bid is not None else None

    @property
    def no_ask(self) -> Decimal | None:
        return Decimal("1") - self.yes_bid if self.yes_bid is not None else None

    def bid(self, token: str) -> Decimal | None:
        return self.yes_bid if token == "YES" else self.no_bid

    def ask(self, token: str) -> Decimal | None:
        return self.yes_ask if token == "YES" else self.no_ask


class LiveQuotes:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, Quote] = {}
        self._ticks: dict[str, deque[Quote]] = {}

    def record(self, market_key: str, quote: Quote) -> None:
        with self._lock:
            previous = self._latest.get(market_key)
            self._latest[market_key] = quote
            ticks = self._ticks.setdefault(market_key, deque(maxlen=MAX_TICKS))
            if previous is None or (previous.yes_bid, previous.no_bid) != (quote.yes_bid, quote.no_bid) or (
                quote.observed_at - ticks[-1].observed_at
            ).total_seconds() >= 5:
                ticks.append(quote)

    def latest(self, market_key: str) -> Quote | None:
        with self._lock:
            return self._latest.get(market_key)

    def ticks(self, market_key: str) -> list[Quote]:
        with self._lock:
            return list(self._ticks.get(market_key, ()))

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._latest)

    def clear(self) -> None:
        with self._lock:
            self._latest.clear()
            self._ticks.clear()


live_quotes = LiveQuotes()
