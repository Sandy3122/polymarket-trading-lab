"""An observable, deliberately simple M1 paper-trading strategy.

The historical research measured fills against the eventual resolution block,
which is not knowable in real time.  This implementation therefore uses only
the published market end time and the current book.  It places a virtual
maker BUY at the current bid when that bid is inside the configured near-$1
range; it never reads a resolution timestamp or winner.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("strategy timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class StrategyMarket:
    market_id: str
    end_time: datetime


@dataclass(frozen=True)
class CurrentBook:
    observed_at: datetime
    yes_bid: Decimal | None
    yes_bid_size: Decimal
    no_bid: Decimal | None
    no_bid_size: Decimal


@dataclass(frozen=True)
class OrderIntent:
    market_id: str
    token: str
    side: str
    price: Decimal
    quantity: Decimal
    reason: str


@dataclass(frozen=True)
class StrategyDecision:
    market_id: str
    strategy_name: str
    decision_time: datetime
    reason: str
    intents: tuple[OrderIntent, ...] = ()
    observations: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class M1Config:
    min_price: Decimal = Decimal("0.95")
    max_price: Decimal = Decimal("1.00")
    max_order_size: Decimal = Decimal("10")
    max_book_age: timedelta = timedelta(seconds=30)
    entry_window: timedelta = timedelta(minutes=2)


class M1Strategy:
    """Buy a near-certain side using only observable live inputs.

    The strategy only receives a market end time and the currently observed
    book.  In particular, it has no resolution timestamp or resolved outcome
    input, so a decision cannot accidentally use future information.
    """

    name = "M1"

    def __init__(self, config: M1Config | None = None) -> None:
        self.config = config or M1Config()

    def decide(self, market: StrategyMarket, book: CurrentBook, now: datetime) -> StrategyDecision:
        now_utc = _as_utc(now)
        end_time = _as_utc(market.end_time)
        observed_at = _as_utc(book.observed_at)
        age = now_utc - observed_at
        observations = {
            "market_end_time": end_time.isoformat(),
            "book_observed_at": observed_at.isoformat(),
            "book_age_seconds": str(age.total_seconds()),
        }

        time_to_end = end_time - now_utc
        observations["seconds_to_market_end"] = str(time_to_end.total_seconds())
        if now_utc >= end_time:
            return StrategyDecision(market.market_id, self.name, now_utc, "market has ended", observations=observations)
        if time_to_end > self.config.entry_window:
            return StrategyDecision(market.market_id, self.name, now_utc, "outside live entry window", observations=observations)
        if age < timedelta(0) or age > self.config.max_book_age:
            return StrategyDecision(market.market_id, self.name, now_utc, "book is stale or from the future", observations=observations)
        if book.yes_bid is None and book.no_bid is None:
            return StrategyDecision(market.market_id, self.name, now_utc, "book lacks usable bids", observations=observations)

        intents: list[OrderIntent] = []
        if (book.yes_bid is not None and self.config.min_price < book.yes_bid <= self.config.max_price
                and book.yes_bid_size > 0):
            intents.append(
                OrderIntent(
                    market.market_id,
                    "YES",
                    "BUY",
                    book.yes_bid,
                    min(self.config.max_order_size, book.yes_bid_size),
                    f"YES bid in M1 price range: {book.yes_bid}",
                )
            )
        if (book.no_bid is not None and self.config.min_price < book.no_bid <= self.config.max_price
                and book.no_bid_size > 0):
            intents.append(
                OrderIntent(
                    market.market_id,
                    "NO",
                    "BUY",
                    book.no_bid,
                    min(self.config.max_order_size, book.no_bid_size),
                    f"NO bid in M1 price range: {book.no_bid}",
                )
            )

        reason = "actionable live M1 signal" if intents else "no actionable M1 signal"
        return StrategyDecision(
            market.market_id,
            self.name,
            now_utc,
            reason,
            tuple(intents),
            observations,
        )
