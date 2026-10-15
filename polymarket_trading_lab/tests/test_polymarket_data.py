from datetime import datetime, timezone
import asyncio
from decimal import Decimal

import pytest

from app.market_data import (
    MarketDataError,
    MarketSnapshot,
    PolymarketMarketStream,
    PolymarketPublicClient,
    parse_market_stream_message,
)


def gamma_market(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "market-1",
        "question": "Will BTC be above the threshold?",
        "endDateIso": "2030-01-01T00:00:00Z",
        "outcomes": '["No", "Yes"]',
        "clobTokenIds": '["no-asset", "yes-asset"]',
        "conditionId": "condition-1",
        "slug": "btc-threshold",
        "active": True,
        "closed": False,
    }
    value.update(overrides)
    return value


def test_public_client_discovers_binary_markets_and_fetches_books() -> None:
    calls: list[tuple[str, str]] = []

    def transport(method: str, url: str, body: object | None) -> object:
        calls.append((method, url))
        if "/markets" in url:
            return [gamma_market()]
        if "token_id=yes-asset" in url:
            return {
                "market": "condition-1",
                "asset_id": "yes-asset",
                "timestamp": "1893456000123",
                "bids": [{"price": "0.96", "size": "2"}, {"price": "0.975", "size": "3.5"}],
                "asks": [],
            }
        return {
            "market": "condition-1",
            "asset_id": "no-asset",
            "timestamp": "1893456000000",
            "bids": [{"price": "0.04", "size": "4"}],
            "asks": [],
        }

    client = PolymarketPublicClient(
        gamma_base_url="https://gamma.test",
        clob_base_url="https://clob.test",
        transport=transport,
    )
    markets = client.list_markets(limit=10)

    assert len(markets) == 1
    market = markets[0]
    assert market.yes_token_id == "yes-asset"
    assert market.no_token_id == "no-asset"
    event = client.book_event(market)
    assert event.payload.yes_bid == Decimal("0.975")
    assert event.payload.yes_bid_size == Decimal("3.5")
    assert event.payload.no_bid == Decimal("0.04")
    assert any("/book?token_id=yes-asset" in url for _, url in calls)
    assert any("/book?token_id=no-asset" in url for _, url in calls)


def test_market_discovery_passes_targeting_filters() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, body: object | None) -> object:
        calls.append(url)
        return []

    client = PolymarketPublicClient(transport=transport)
    client.list_markets(
        limit=25,
        max_pages=1,
        active=True,
        end_date_min=datetime(2030, 1, 1, tzinfo=timezone.utc),
        end_date_max=datetime(2030, 1, 1, 0, 20, tzinfo=timezone.utc),
        order="endDate",
        ascending=True,
    )

    assert len(calls) == 1
    assert "active=true" in calls[0]
    assert "end_date_min=2030-01-01T00%3A00%3A00%2B00%3A00" in calls[0]
    assert "end_date_max=2030-01-01T00%3A20%3A00%2B00%3A00" in calls[0]
    assert "order=endDate" in calls[0]
    assert "ascending=true" in calls[0]


def test_public_client_skips_unsupported_markets_and_rejects_bad_books() -> None:
    def transport(method: str, url: str, body: object | None) -> object:
        if "/markets" in url:
            return [gamma_market(outcomes='["Yes", "Maybe"]')]
        return {}

    client = PolymarketPublicClient(transport=transport)
    assert client.list_markets(limit=10) == []

    market = MarketSnapshot(
        "market-1",
        "Question",
        datetime(2030, 1, 1, tzinfo=timezone.utc),
        datetime.now(timezone.utc),
        yes_token_id="yes",
        no_token_id="no",
        condition_id="condition-1",
    )

    with pytest.raises(MarketDataError):
        client.book_event(market)


def test_market_stream_parser_tracks_both_books_and_resolution() -> None:
    market = MarketSnapshot(
        "market-1",
        "Question",
        datetime(2030, 1, 1, tzinfo=timezone.utc),
        datetime.now(timezone.utc),
        yes_token_id="yes",
        no_token_id="no",
        condition_id="condition-1",
    )
    lookup = {"yes": market, "no": market, "condition-1": market}
    books: dict[str, dict[str, tuple[Decimal | None, Decimal]]] = {}
    yes = parse_market_stream_message(
        {"event_type": "book", "market": "condition-1", "asset_id": "yes", "timestamp": "1893456000000", "bids": [{"price": "0.97", "size": "2"}]},
        lookup,
        books,
    )
    both = parse_market_stream_message(
        {"event_type": "book", "market": "condition-1", "asset_id": "no", "timestamp": "1893456001000", "bids": [{"price": "0.03", "size": "5"}]},
        lookup,
        books,
    )
    resolution = parse_market_stream_message(
        {"event_type": "market_resolved", "market": "condition-1", "winning_asset_id": "yes", "timestamp": "1893456002000"},
        lookup,
        books,
    )

    assert yes is not None and yes.payload.yes_bid == Decimal("0.97")
    assert both is not None and both.payload.no_bid == Decimal("0.03")
    assert resolution is not None and resolution.payload.winning_token == "YES"


class FakeWebSocket:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        self.sent: list[str] = []

    async def __aenter__(self) -> "FakeWebSocket":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> str:
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)


class FakeConnect:
    def __init__(self, websocket: FakeWebSocket) -> None:
        self.websocket = websocket

    def __call__(self, url: str, **kwargs: object) -> FakeWebSocket:
        return self.websocket


def test_market_stream_sends_subscription_and_heartbeat_response() -> None:
    market = MarketSnapshot(
        "market-1",
        "Question",
        datetime(2030, 1, 1, tzinfo=timezone.utc),
        datetime.now(timezone.utc),
        yes_token_id="yes",
        no_token_id="no",
    )
    websocket = FakeWebSocket([
        "PING",
        '{"event_type":"book","market":"market-1","asset_id":"yes","timestamp":"1893456000000","bids":[]}',
    ])
    stream = PolymarketMarketStream([market], connect=FakeConnect(websocket), heartbeat_seconds=3600)
    async def collect() -> list[object]:
        events: list[object] = []
        async for event in stream.events():
            events.append(event)
        return events

    events = asyncio.run(collect())

    assert events[0].event_type == "book"
    assert '"type": "market"' in websocket.sent[0]
    assert "PONG" in websocket.sent


def test_event_start_time_is_preferred_over_market_creation_date() -> None:
    """Short up/down markets are created ~24h early; startDate is not the trading window."""
    raw = gamma_market(
        slug="btc-updown-15m-1",
        startDate="2029-12-31T00:05:00Z",
        eventStartTime="2029-12-31T23:45:00Z",
        endDateIso=None,
        endDate="2030-01-01T00:00:00Z",
    )
    client = PolymarketPublicClient(transport=lambda m, u, b: [raw])
    (market,) = client.list_markets(limit=10)
    assert market.start_time == datetime(2029, 12, 31, 23, 45, tzinfo=timezone.utc)
    assert (market.end_time - market.start_time).total_seconds() == 15 * 60


def test_start_date_is_fallback_when_event_start_time_missing() -> None:
    raw = gamma_market(startDate="2029-12-31T00:00:00Z")
    client = PolymarketPublicClient(transport=lambda m, u, b: [raw])
    (market,) = client.list_markets(limit=10)
    assert market.start_time == datetime(2029, 12, 31, tzinfo=timezone.utc)


def test_up_down_markets_map_to_yes_no_slots() -> None:
    raw = gamma_market(outcomes='["Up", "Down"]', clobTokenIds='["up-asset", "down-asset"]')
    client = PolymarketPublicClient(transport=lambda m, u, b: [raw])
    (market,) = client.list_markets(limit=10)
    assert market.yes_token_id == "up-asset"
    assert market.no_token_id == "down-asset"


def test_quiet_book_is_fresh_when_just_fetched() -> None:
    """CLOB timestamp is last-change time; a just-fetched quiet book must not look stale."""
    def transport(method: str, url: str, body: object | None) -> object:
        return {
            "market": "condition-1",
            "asset_id": "x",
            "timestamp": "1893456000000",  # years in the future vs. "last change" semantics: only validated
            "bids": [{"price": "0.96", "size": "2"}],
            "asks": [],
        }

    market = MarketSnapshot(
        "market-1", "Q", datetime(2030, 1, 1, tzinfo=timezone.utc), datetime.now(timezone.utc),
        yes_token_id="yes-asset", no_token_id="no-asset", condition_id="condition-1",
    )
    event = PolymarketPublicClient(transport=transport).book_event(market)
    assert event.payload.observed_at == event.occurred_at
