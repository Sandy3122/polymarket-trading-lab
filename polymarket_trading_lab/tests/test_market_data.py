from decimal import Decimal

import pytest

from app.market_data import MarketDataError, PolymarketRestMarketDataSource


def transport_for(market: dict[str, object], books: list[dict[str, object]]):
    calls: list[tuple[str, str, object | None]] = []

    def transport(method: str, url: str, body: object | None) -> object:
        calls.append((method, url, body))
        if method == "GET":
            return market
        return books

    transport.calls = calls  # type: ignore[attr-defined]
    return transport


def base_market(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "m-1",
        "question": "Will it happen?",
        "endDateIso": "2030-01-01T00:00:00+00:00",
        "version": "v1",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["yes-asset", "no-asset"]',
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "enableOrderBook": True,
        "conditionId": "condition-1",
    }
    value.update(overrides)
    return value


def base_books() -> list[dict[str, object]]:
    return [
        {
            "asset_id": "yes-asset",
            "market": "condition-1",
            "timestamp": "1893456000123",
            "bids": [{"price": "0.96", "size": "2"}, {"price": "0.975", "size": "3.5"}],
        },
        {
            "asset_id": "no-asset",
            "market": "condition-1",
            "timestamp": "1893456000000",
            "bids": [],
        },
    ]


def test_rest_source_normalizes_market_and_best_books() -> None:
    transport = transport_for(base_market(), base_books())

    events = list(PolymarketRestMarketDataSource("m-1", transport=transport))

    assert [event.event_type for event in events] == ["market", "book"]
    market = events[0].payload
    book = events[1].payload
    assert market.market_id == "m-1"
    assert market.status == "open"
    assert book.yes_bid == Decimal("0.975")
    assert book.yes_bid_size == Decimal("3.5")
    assert book.no_bid is None
    assert book.no_bid_size == Decimal("0")
    assert book.observed_at.isoformat() == "2030-01-01T00:00:00+00:00"
    assert transport.calls[1][0:2] == ("POST", "https://clob.polymarket.com/books")
    assert transport.calls[1][2] == [{"token_id": "yes-asset"}, {"token_id": "no-asset"}]


def test_v2_uses_position_ids_and_does_not_use_clob_token_ids() -> None:
    market = base_market(
        version="v2",
        positionIds=["v2-yes", "v2-no"],
        clobTokenIds='["wrong-yes", "wrong-no"]',
    )
    transport = transport_for(
        market,
        [
            {"asset_id": "v2-yes", "timestamp": "1893456000000", "bids": []},
            {"asset_id": "v2-no", "timestamp": "1893456000000", "bids": []},
        ],
    )

    list(PolymarketRestMarketDataSource("m-1", transport=transport))

    assert transport.calls[1][2] == [{"token_id": "v2-yes"}, {"token_id": "v2-no"}]


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({"active": True, "closed": False, "acceptingOrders": True, "enableOrderBook": True}, "open"),
        ({"active": True, "closed": True, "acceptingOrders": True, "enableOrderBook": True}, "closed"),
        ({"active": False, "closed": False, "acceptingOrders": True, "enableOrderBook": True}, "inactive"),
        ({"active": True, "closed": False, "acceptingOrders": None, "enableOrderBook": True}, "inactive"),
    ],
)
def test_status_is_fail_closed(flags: dict[str, object], expected: str) -> None:
    market = base_market(**flags)
    transport = transport_for(market, base_books() if expected == "open" else [])

    events = list(PolymarketRestMarketDataSource("m-1", transport=transport))

    assert events[0].payload.status == expected
    assert len(events) == 1 if expected != "open" else len(events) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"question": None},
        {"endDateIso": None, "endDate": None},
        {"version": "v3"},
        {"outcomes": '["Yes"]'},
        {"clobTokenIds": '["only-one"]'},
    ],
)
def test_invalid_market_metadata_fails_closed(changes: dict[str, object]) -> None:
    transport = transport_for(base_market(**changes), base_books())

    with pytest.raises(MarketDataError):
        list(PolymarketRestMarketDataSource("m-1", transport=transport))


def test_mismatched_book_is_rejected() -> None:
    books = base_books()
    books[1] = {**books[1], "asset_id": "another-asset"}
    transport = transport_for(base_market(), books)

    with pytest.raises(MarketDataError, match="both requested assets"):
        list(PolymarketRestMarketDataSource("m-1", transport=transport))


def test_closed_market_does_not_fetch_books_or_emit_resolution() -> None:
    transport = transport_for(base_market(closed=True), base_books())

    events = list(PolymarketRestMarketDataSource("m-1", transport=transport))

    assert [event.event_type for event in events] == ["market"]
    assert len(transport.calls) == 1
