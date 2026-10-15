from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.market_data import BookSnapshot, MarketEvent, MarketSnapshot, Resolution
from app.replay import ReplayRunner
from app.strategy import M1Strategy


def test_replay_is_time_ordered_and_uses_observed_end_time() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    events = [
        MarketEvent(
            "book",
            now + timedelta(seconds=5),
            BookSnapshot("m1", now + timedelta(seconds=5), Decimal("0.97"), Decimal("2")),
        ),
        MarketEvent(
            "market",
            now,
            MarketSnapshot("m1", "Test", now + timedelta(seconds=30), now),
        ),
    ]

    decisions = ReplayRunner(M1Strategy()).run(events)

    assert len(decisions) == 1
    assert decisions[0].reason == "actionable live M1 signal"
    assert decisions[0].intents[0].token == "YES"


def test_replay_stops_after_resolution() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    events = [
        MarketEvent("market", now, MarketSnapshot("m1", "Test", now + timedelta(minutes=2), now)),
        MarketEvent("resolution", now + timedelta(seconds=30), Resolution("m1", "YES", now + timedelta(seconds=30))),
        MarketEvent("book", now + timedelta(seconds=31), BookSnapshot("m1", now + timedelta(seconds=31), Decimal("0.97"), Decimal("2"))),
    ]

    assert ReplayRunner(M1Strategy()).run(events) == []
