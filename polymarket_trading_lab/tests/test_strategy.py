from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.strategy import CurrentBook, M1Strategy, StrategyMarket


class NoLookaheadMarket:
    market_id = "m-1"
    end_time = datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)

    @property
    def resolution_time(self) -> datetime:
        raise AssertionError("strategy must not inspect resolution_time")


def test_m1_uses_fresh_current_book_and_never_resolution_time() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    book = CurrentBook(
        observed_at=now - timedelta(seconds=5),
        yes_bid=Decimal("0.97"),
        yes_bid_size=Decimal("3"),
        no_bid=Decimal("0.96"),
        no_bid_size=Decimal("4"),
    )

    decision = M1Strategy().decide(NoLookaheadMarket(), book, now)  # type: ignore[arg-type]

    assert decision.reason == "actionable live M1 signal"
    assert {intent.token for intent in decision.intents} == {"YES", "NO"}
    assert all(intent.side == "BUY" for intent in decision.intents)
    assert decision.observations["book_age_seconds"] == "5.0"


def test_m1_rejects_stale_books_and_ended_markets() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    stale_book = CurrentBook(
        observed_at=now - timedelta(minutes=1),
        yes_bid=Decimal("0.97"),
        yes_bid_size=Decimal("3"),
        no_bid=Decimal("0.96"),
        no_bid_size=Decimal("4"),
    )
    strategy = M1Strategy()
    market = StrategyMarket("m-1", now + timedelta(minutes=1))

    stale = strategy.decide(market, stale_book, now)
    ended = strategy.decide(StrategyMarket("m-1", now), stale_book, now)

    assert stale.intents == ()
    assert stale.reason == "book is stale or from the future"
    assert ended.intents == ()
    assert ended.reason == "market has ended"
