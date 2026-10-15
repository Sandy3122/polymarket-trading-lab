"""Small provider-neutral market-data contracts.

The trading engine consumes these objects rather than a vendor SDK.  A live
Polymarket adapter can be added later without changing strategy or accounting.
The JSONL reader is useful for deterministic local replay and smoke testing.
"""

from __future__ import annotations

import json
import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import Any, Iterable, Iterator, Protocol


class MarketDataError(ValueError):
    """Raised when a provider response cannot be trusted or normalized."""


JsonTransport = Callable[[str, str, object | None], object]


def as_utc(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("market-data timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class MarketSnapshot:
    market_id: str
    question: str
    end_time: datetime
    observed_at: datetime
    status: str = "open"
    yes_token_id: str | None = None
    no_token_id: str | None = None
    condition_id: str | None = None
    slug: str | None = None
    start_time: datetime | None = None
    category: str | None = None


@dataclass(frozen=True)
class BookSnapshot:
    market_id: str
    observed_at: datetime
    yes_bid: Decimal | None
    yes_bid_size: Decimal = Decimal("0")
    no_bid: Decimal | None = None
    no_bid_size: Decimal = Decimal("0")


@dataclass(frozen=True)
class TradeSnapshot:
    market_id: str
    token_id: str
    side: str
    price: Decimal
    size: Decimal
    observed_at: datetime
    event_id: str | None = None


@dataclass(frozen=True)
class Resolution:
    market_id: str
    winning_token: str
    resolved_at: datetime


@dataclass(frozen=True)
class MarketEvent:
    event_type: str
    occurred_at: datetime
    payload: MarketSnapshot | BookSnapshot | TradeSnapshot | Resolution


class MarketDataSource(Protocol):
    def events(self) -> Iterable[MarketEvent]:
        """Yield normalized events in chronological order."""


def event_from_mapping(raw: Mapping[str, Any]) -> MarketEvent:
    """Parse one normalized event mapping for files and API submissions."""

    event_type = raw["event_type"]
    occurred_at = as_utc(raw["occurred_at"])
    payload = raw["payload"]
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be an object")
    if event_type == "market":
        value = MarketSnapshot(
            market_id=str(payload["market_id"]),
            question=str(payload["question"]),
            end_time=as_utc(payload["end_time"]),
            observed_at=as_utc(payload["observed_at"]),
            status=str(payload.get("status", "open")),
            yes_token_id=str(payload["yes_token_id"]) if payload.get("yes_token_id") is not None else None,
            no_token_id=str(payload["no_token_id"]) if payload.get("no_token_id") is not None else None,
            condition_id=str(payload["condition_id"]) if payload.get("condition_id") is not None else None,
            slug=str(payload["slug"]) if payload.get("slug") is not None else None,
            start_time=as_utc(payload["start_time"]) if payload.get("start_time") else None,
            category=str(payload["category"]) if payload.get("category") is not None else None,
        )
    elif event_type == "book":
        value = BookSnapshot(
            market_id=str(payload["market_id"]),
            observed_at=as_utc(payload["observed_at"]),
            yes_bid=Decimal(str(payload["yes_bid"])) if payload.get("yes_bid") is not None else None,
            yes_bid_size=Decimal(str(payload.get("yes_bid_size", "0"))),
            no_bid=Decimal(str(payload["no_bid"])) if payload.get("no_bid") is not None else None,
            no_bid_size=Decimal(str(payload.get("no_bid_size", "0"))),
        )
    elif event_type == "resolution":
        value = Resolution(
            market_id=str(payload["market_id"]),
            winning_token=str(payload["winning_token"]),
            resolved_at=as_utc(payload["resolved_at"]),
        )
    elif event_type == "trade":
        value = TradeSnapshot(
            market_id=str(payload["market_id"]),
            token_id=str(payload["token_id"]),
            side=str(payload["side"]).upper(),
            price=Decimal(str(payload["price"])),
            size=Decimal(str(payload["size"])),
            observed_at=as_utc(payload.get("observed_at", raw["occurred_at"])),
            event_id=str(payload["event_id"]) if payload.get("event_id") is not None else None,
        )
    else:
        raise ValueError(f"unsupported event_type {event_type!r}")
    return MarketEvent(str(event_type), occurred_at, value)


class JsonlMarketDataSource:
    """Read normalized events from a JSONL file without vendor coupling."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def events(self) -> Iterator[MarketEvent]:
        with self.path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, Mapping):
                        raise ValueError("event must be an object")
                    yield event_from_mapping(raw)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"invalid JSONL event on line {line_number}: {exc}") from exc


def _http_json(method: str, url: str, body: object | None = None) -> object:
    """Fetch JSON using the standard library so the adapter has no new dependency."""

    encoded = None
    headers = {
        "accept": "application/json",
        "user-agent": "polymarket-trading-lab/0.1 (+public-market-data)",
    }
    if body is not None:
        encoded = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"
    request = Request(url, data=encoded, headers=headers, method=method)
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=10) as response:  # noqa: S310 - URL is configured by the caller.
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # Retry provider throttling and transient server failures, but fail
            # immediately on malformed requests/auth errors.
            last_error = exc
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                break
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(0.5 * (2**attempt))
    raise MarketDataError(f"market-data request failed for {url}: {last_error}") from last_error


def _json_list(value: object, field: str) -> list[object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise MarketDataError(f"{field} is not valid JSON") from exc
    if not isinstance(value, list):
        raise MarketDataError(f"{field} must be a list")
    return value


def _timestamp(value: object, field: str) -> datetime:
    if value is None:
        raise MarketDataError(f"{field} is missing")
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        numeric = Decimal(str(value))
        # CLOB book timestamps are epoch milliseconds; accept seconds too for fixtures
        # and providers that normalize the field before returning it.
        seconds = numeric / Decimal("1000") if numeric > Decimal("100000000000") else numeric
        return datetime.fromtimestamp(float(seconds), tz=timezone.utc)
    try:
        return as_utc(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketDataError(f"{field} must be a timezone-aware timestamp") from exc


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ArithmeticError, ValueError) as exc:
        raise MarketDataError(f"{field} must be a decimal") from exc
    if not result.is_finite():
        raise MarketDataError(f"{field} must be finite")
    return result


def _best_bid(book: Mapping[str, Any], asset_id: str) -> tuple[Decimal | None, Decimal]:
    bids = book.get("bids", [])
    if not isinstance(bids, list):
        raise MarketDataError(f"book for {asset_id} has invalid bids")
    levels: list[tuple[Decimal, Decimal]] = []
    for level in bids:
        if not isinstance(level, Mapping) or "price" not in level or "size" not in level:
            raise MarketDataError(f"book for {asset_id} has an invalid bid level")
        price = _decimal(level["price"], f"book {asset_id} bid price")
        size = _decimal(level["size"], f"book {asset_id} bid size")
        if not (Decimal("0") <= price <= Decimal("1")) or size < 0:
            raise MarketDataError(f"book for {asset_id} has an out-of-range bid")
        if size > 0:
            levels.append((price, size))
    if not levels:
        return None, Decimal("0")
    return max(levels, key=lambda item: item[0])


class PolymarketRestMarketDataSource:
    """One-shot, read-only polling of a public binary Polymarket market.

    The adapter intentionally emits no resolution event.  Gamma's display and
    status fields are not treated as an authoritative winning outcome, so
    settlement remains a separate integration boundary.
    """

    def __init__(
        self,
        market_id: str,
        *,
        gamma_base_url: str = "https://gamma-api.polymarket.com",
        clob_base_url: str = "https://clob.polymarket.com",
        transport: JsonTransport = _http_json,
    ) -> None:
        if not market_id.strip():
            raise ValueError("market_id must not be empty")
        self.market_id = market_id
        self.gamma_base_url = gamma_base_url.rstrip("/")
        self.clob_base_url = clob_base_url.rstrip("/")
        self.transport = transport

    def __iter__(self) -> Iterator[MarketEvent]:
        """Allow the source to be consumed directly as an event iterable."""
        return self.events()

    def events(self) -> Iterator[MarketEvent]:
        received_at = datetime.now(timezone.utc)
        raw = self.transport("GET", f"{self.gamma_base_url}/markets/{quote(self.market_id, safe='')}", None)
        if not isinstance(raw, Mapping):
            raise MarketDataError("Gamma market response must be an object")

        market_id = self._text(raw, "id")
        question = self._text(raw, "question")
        end_value = raw.get("endDateIso", raw.get("endDate"))
        end_time = _timestamp(end_value, "endDate")
        version = str(raw.get("version", "")).lower()
        outcomes = _json_list(raw.get("outcomes"), "outcomes")
        if len(outcomes) != 2 or [str(item).strip().lower() for item in outcomes] != ["yes", "no"]:
            raise MarketDataError("only binary outcomes ordered as YES, NO are supported")
        token_field = "clobTokenIds" if version == "v1" else "positionIds" if version == "v2" else None
        if token_field is None:
            raise MarketDataError(f"unsupported Polymarket protocol version: {version!r}")
        token_values = _json_list(raw.get(token_field), token_field)
        if len(token_values) != 2 or not all(isinstance(item, (str, int)) and str(item) for item in token_values):
            raise MarketDataError(f"{token_field} must contain exactly two asset IDs")
        yes_asset, no_asset = (str(token_values[0]), str(token_values[1]))
        status = self._status(raw)

        yield MarketEvent(
            "market",
            received_at,
            MarketSnapshot(
                market_id, question, end_time, received_at, status,
                yes_token_id=yes_asset, no_token_id=no_asset,
                condition_id=str(raw.get("conditionId")) if raw.get("conditionId") is not None else None,
                slug=str(raw.get("slug")) if raw.get("slug") is not None else None,
                start_time=_market_start(raw),
                category=str(raw["category"]) if raw.get("category") is not None else None,
            ),
        )
        if status != "open":
            return

        books = self.transport(
            "POST",
            f"{self.clob_base_url}/books",
            [{"token_id": yes_asset}, {"token_id": no_asset}],
        )
        if not isinstance(books, Sequence) or isinstance(books, (str, bytes)):
            raise MarketDataError("CLOB books response must be a list")
        by_asset: dict[str, Mapping[str, Any]] = {}
        expected_condition = raw.get("conditionId")
        for book in books:
            if not isinstance(book, Mapping):
                raise MarketDataError("CLOB book must be an object")
            asset_id = self._text(book, "asset_id")
            if asset_id in by_asset:
                raise MarketDataError(f"duplicate CLOB book for asset {asset_id}")
            if expected_condition is not None and book.get("market") is not None and str(book["market"]).lower() != str(expected_condition).lower():
                raise MarketDataError(f"CLOB book for {asset_id} belongs to another market")
            by_asset[asset_id] = book
        if set(by_asset) != {yes_asset, no_asset}:
            raise MarketDataError("CLOB books did not contain both requested assets")

        yes_bid, yes_size = _best_bid(by_asset[yes_asset], yes_asset)
        no_bid, no_size = _best_bid(by_asset[no_asset], no_asset)
        # The CLOB "timestamp" is when the book last *changed*; a quiet book can
        # be minutes old yet still be exactly what the exchange shows now. Validate
        # it, but measure freshness by when this snapshot was actually fetched.
        _timestamp(by_asset[yes_asset].get("timestamp"), "CLOB timestamp")
        _timestamp(by_asset[no_asset].get("timestamp"), "CLOB timestamp")
        observed_at = received_at
        yield MarketEvent(
            "book",
            received_at,
            BookSnapshot(market_id, observed_at, yes_bid, yes_size, no_bid, no_size),
        )

    @staticmethod
    def _text(raw: Mapping[str, Any], field: str) -> str:
        value = raw.get(field)
        if not isinstance(value, (str, int)) or not str(value).strip():
            raise MarketDataError(f"market-data response is missing {field}")
        return str(value)

    @staticmethod
    def _status(raw: Mapping[str, Any]) -> str:
        if raw.get("closed") is True:
            return "closed"
        if all(raw.get(field) is True for field in ("active", "acceptingOrders", "enableOrderBook")):
            return "open"
        return "inactive"


def _url_with_params(base_url: str, path: str, params: Mapping[str, object]) -> str:
    query = urlencode([(key, str(value).lower() if isinstance(value, bool) else str(value)) for key, value in params.items()])
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}?{query}" if query else f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _gamma_market(raw: Mapping[str, Any], observed_at: datetime | None = None) -> MarketSnapshot:
    """Normalize one Gamma market while retaining only supported binary data."""

    def required_text(field: str) -> str:
        value = raw.get(field)
        if not isinstance(value, (str, int)) or not str(value).strip():
            raise MarketDataError(f"Gamma market is missing {field}")
        return str(value)

    market_id = required_text("id")
    question_value = raw.get("question") or raw.get("title")
    if not isinstance(question_value, str) or not question_value.strip():
        raise MarketDataError(f"Gamma market {market_id} is missing question")
    end_time = None
    for candidate in (raw.get("endDateIso"), raw.get("endDate")):
        if candidate is None:
            continue
        try:
            end_time = _timestamp(candidate, "endDate")
            break
        except MarketDataError:
            continue
    if end_time is None:
        raise MarketDataError("Gamma market has no usable endDate")
    outcomes = [str(item).strip().lower() for item in _json_list(raw.get("outcomes"), "outcomes")]
    # Up/Down markets are binary too: Up takes the affirmative (YES) slot.
    outcomes = [_OUTCOME_ALIASES.get(item, item) for item in outcomes]
    if len(outcomes) != 2 or set(outcomes) != {"yes", "no"}:
        raise MarketDataError("only binary YES/NO or Up/Down markets are supported")

    token_values = raw.get("clobTokenIds")
    if token_values is None:
        token_values = raw.get("positionIds")
    tokens = [str(item) for item in _json_list(token_values, "clobTokenIds/positionIds")]
    if len(tokens) != 2 or not all(token.strip() for token in tokens):
        raise MarketDataError("market must contain exactly two asset IDs")
    by_outcome = dict(zip(outcomes, tokens))
    observed = observed_at or datetime.now(timezone.utc)
    return MarketSnapshot(
        market_id=market_id,
        question=question_value,
        end_time=end_time,
        observed_at=observed,
        status=_gamma_status(raw),
        yes_token_id=by_outcome["yes"],
        no_token_id=by_outcome["no"],
        condition_id=str(raw["conditionId"]) if raw.get("conditionId") is not None else None,
        slug=str(raw["slug"]) if raw.get("slug") is not None else None,
        start_time=_market_start(raw),
        category=str(raw["category"]) if raw.get("category") is not None else None,
    )


_OUTCOME_ALIASES = {"up": "yes", "down": "no"}


def _market_start(raw: Mapping[str, Any]) -> datetime | None:
    """Start of the trading window.

    ``eventStartTime`` is when the window opens; ``startDate`` is when the
    market was created (often ~24h earlier for short up/down markets), so it is
    only a fallback.
    """
    if raw.get("eventStartTime"):
        return _timestamp(raw["eventStartTime"], "eventStartTime")
    if raw.get("startDate"):
        return _timestamp(raw["startDate"], "startDate")
    return None


def _gamma_status(raw: Mapping[str, Any]) -> str:
    if raw.get("closed") is True:
        return "closed"
    if raw.get("active") is False or raw.get("acceptingOrders") is False or raw.get("enableOrderBook") is False:
        return "inactive"
    return "open"


class PolymarketPublicClient:
    """Read-only Gamma and CLOB client for public market data.

    This class deliberately has no account credentials, wallet, signing, or
    order methods.  Its transport is injectable so every behavior can be
    tested without contacting Polymarket.
    """

    def __init__(
        self,
        *,
        gamma_base_url: str = "https://gamma-api.polymarket.com",
        clob_base_url: str = "https://clob.polymarket.com",
        transport: JsonTransport = _http_json,
    ) -> None:
        self.gamma_base_url = gamma_base_url.rstrip("/")
        self.clob_base_url = clob_base_url.rstrip("/")
        self.transport = transport

    def list_markets(
        self,
        *,
        limit: int = 100,
        max_pages: int = 1,
        closed: bool = False,
        active: bool | None = None,
        end_date_min: datetime | None = None,
        end_date_max: datetime | None = None,
        order: str | None = None,
        ascending: bool | None = None,
    ) -> list[MarketSnapshot]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        markets: list[MarketSnapshot] = []
        for page in range(max_pages):
            params: dict[str, object] = {"closed": closed, "limit": limit, "offset": page * limit}
            if active is not None:
                params["active"] = active
            if end_date_min is not None:
                params["end_date_min"] = as_utc(end_date_min).isoformat()
            if end_date_max is not None:
                params["end_date_max"] = as_utc(end_date_max).isoformat()
            if order:
                params["order"] = order
            if ascending is not None:
                params["ascending"] = ascending
            raw = self.transport(
                "GET",
                _url_with_params(self.gamma_base_url, "/markets", params),
                None,
            )
            if isinstance(raw, Mapping):
                raw_items = raw.get("data", raw.get("markets", []))
            else:
                raw_items = raw
            if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
                raise MarketDataError("Gamma markets response must be a list")
            observed = datetime.now(timezone.utc)
            for item in raw_items:
                if not isinstance(item, Mapping):
                    raise MarketDataError("Gamma market entry must be an object")
                try:
                    markets.append(_gamma_market(item, observed))
                except MarketDataError:
                    # Unsupported/non-binary markets are not silently mixed
                    # into the strategy universe; they are skipped by design.
                    continue
            if len(raw_items) < limit:
                break
        return markets

    def get_market(self, market_id: str) -> MarketSnapshot:
        raw = self.transport("GET", f"{self.gamma_base_url}/markets/{quote(market_id, safe='')}", None)
        if not isinstance(raw, Mapping):
            raise MarketDataError("Gamma market response must be an object")
        return _gamma_market(raw)

    def get_book(self, token_id: str) -> Mapping[str, Any]:
        if not token_id.strip():
            raise ValueError("token_id must not be empty")
        raw = self.transport(
            "GET",
            _url_with_params(self.clob_base_url, "/book", {"token_id": token_id}),
            None,
        )
        if not isinstance(raw, Mapping):
            raise MarketDataError("CLOB book response must be an object")
        return raw

    def book_event(self, market: MarketSnapshot) -> MarketEvent:
        if not market.yes_token_id or not market.no_token_id:
            raise MarketDataError("market has no YES/NO asset IDs")
        books = {token: self.get_book(token) for token in (market.yes_token_id, market.no_token_id)}
        if market.condition_id:
            for token, book in books.items():
                book_market = book.get("market")
                if book_market is not None and str(book_market).lower() != market.condition_id.lower():
                    raise MarketDataError(f"CLOB book for {token} belongs to another market")
        yes_bid, yes_size = _best_bid(books[market.yes_token_id], market.yes_token_id)
        no_bid, no_size = _best_bid(books[market.no_token_id], market.no_token_id)
        # The CLOB "timestamp" is the last book *change*; validate it, but measure
        # freshness by fetch time so a quiet-but-current book isn't called stale.
        _timestamp(books[market.yes_token_id].get("timestamp"), "YES book timestamp")
        _timestamp(books[market.no_token_id].get("timestamp"), "NO book timestamp")
        occurred = datetime.now(timezone.utc)
        return MarketEvent(
            "book",
            occurred,
            BookSnapshot(market.market_id, occurred, yes_bid, yes_size, no_bid, no_size),
        )

    def market_events(self, market: MarketSnapshot) -> Iterator[MarketEvent]:
        yield MarketEvent("market", market.observed_at, market)
        if market.status == "open":
            yield self.book_event(market)


def _ws_timestamp(message: Mapping[str, Any]) -> datetime:
    value = message.get("timestamp")
    return _timestamp(value, "WebSocket timestamp") if value is not None else datetime.now(timezone.utc)


def _ws_best_bid(message: Mapping[str, Any], asset_id: str) -> tuple[Decimal | None, Decimal]:
    return _best_bid(message, asset_id)


def parse_market_stream_message(
    message: str | Mapping[str, Any],
    markets: Mapping[str, MarketSnapshot],
    books: dict[str, dict[str, tuple[Decimal | None, Decimal]]] | None = None,
) -> MarketEvent | None:
    """Parse one public CLOB market-stream message into a normalized event."""

    if isinstance(message, str):
        if message in {"PING", "PONG", ""}:
            return None
        try:
            raw = json.loads(message)
        except json.JSONDecodeError as exc:
            raise MarketDataError("WebSocket message is not valid JSON") from exc
    else:
        raw = message
    if not isinstance(raw, Mapping):
        return None
    event_type = str(raw.get("event_type", raw.get("type", ""))).lower()
    asset_id = str(raw.get("asset_id", ""))
    market = markets.get(asset_id) or markets.get(str(raw.get("market", "")))
    if event_type == "book":
        if not asset_id:
            return None
        if market is None:
            return None
        if books is None:
            books = {}
        state = books.setdefault(market.market_id, {})
        state[asset_id] = _ws_best_bid(raw, asset_id)
        yes = state.get(market.yes_token_id or "", (None, Decimal("0")))
        no = state.get(market.no_token_id or "", (None, Decimal("0")))
        return MarketEvent("book", _ws_timestamp(raw), BookSnapshot(market.market_id, _ws_timestamp(raw), yes[0], yes[1], no[0], no[1]))
    if event_type == "market_resolved":
        winning_asset = raw.get("winning_asset_id")
        winner = str(winning_asset) if winning_asset is not None else ""
        resolved_market = market
        if resolved_market is None:
            for candidate in markets.values():
                if winner in {candidate.yes_token_id, candidate.no_token_id}:
                    resolved_market = candidate
                    break
        if resolved_market is None:
            return None
        winning_token = "YES" if winner == resolved_market.yes_token_id else "NO" if winner == resolved_market.no_token_id else ""
        if not winning_token:
            return None
        resolved_at = _ws_timestamp(raw)
        return MarketEvent("resolution", resolved_at, Resolution(resolved_market.market_id, winning_token, resolved_at))
    if event_type in {"last_trade_price", "trade"}:
        if not asset_id or market is None:
            return None
        price_value = raw.get("price")
        if price_value is None:
            return None
        observed_at = _ws_timestamp(raw)
        return MarketEvent(
            "trade",
            observed_at,
            TradeSnapshot(
                market_id=market.market_id,
                token_id=asset_id,
                side=str(raw.get("side", "")).upper(),
                price=_decimal(price_value, "trade price"),
                size=_decimal(raw.get("size", "0"), "trade size"),
                observed_at=observed_at,
                event_id=str(raw.get("transaction_hash")) if raw.get("transaction_hash") is not None else str(raw.get("hash")) if raw.get("hash") is not None else None,
            ),
        )
    return None


class PolymarketMarketStream:
    """Async public CLOB stream with the documented application heartbeat."""

    def __init__(
        self,
        markets: Sequence[MarketSnapshot],
        *,
        ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market",
        connect: Callable[..., Any] | None = None,
        heartbeat_seconds: float = 10.0,
    ) -> None:
        self.markets = tuple(markets)
        self.ws_url = ws_url
        self.heartbeat_seconds = heartbeat_seconds
        if connect is None:
            try:
                from websockets.asyncio.client import connect as default_connect
            except ImportError:  # pragma: no cover - supported dependency path
                from websockets import connect as default_connect
            connect = default_connect
        self.connect = connect

    def subscription(self) -> dict[str, object]:
        assets = [
            token
            for market in self.markets
            for token in (market.yes_token_id, market.no_token_id)
            if token
        ]
        return {"assets_ids": assets, "type": "market", "custom_feature_enabled": True}

    async def events(self) -> Any:
        lookup: dict[str, MarketSnapshot] = {}
        for market in self.markets:
            if market.yes_token_id:
                lookup[market.yes_token_id] = market
            if market.no_token_id:
                lookup[market.no_token_id] = market
            if market.condition_id:
                lookup[market.condition_id] = market
        books: dict[str, dict[str, tuple[Decimal | None, Decimal]]] = {}
        async with self.connect(self.ws_url, ping_interval=None, max_queue=2048) as websocket:
            await websocket.send(json.dumps(self.subscription()))

            async def heartbeat() -> None:
                while True:
                    await asyncio.sleep(self.heartbeat_seconds)
                    await websocket.send("PING")

            heartbeat_task = asyncio.create_task(heartbeat())
            try:
                async for raw_message in websocket:
                    if raw_message == "PING":
                        await websocket.send("PONG")
                        continue
                    event = parse_market_stream_message(raw_message, lookup, books)
                    if event is not None:
                        yield event
            finally:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
