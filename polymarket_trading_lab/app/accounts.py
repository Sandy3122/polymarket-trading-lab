"""Provider-neutral, read-only account monitoring and reconciliation.

The account boundary intentionally contains no wallet, credential, signing, or
execution code.  The Polymarket implementation uses the public Data API only
and accepts an injectable JSON transport so callers and tests can control all
I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AccountActivityRecord,
    AccountPositionRecord,
    AccountReconciliationRecord,
    AccountSnapshotRecord,
    LedgerEntry,
    Market,
    Position,
    utc_now,
)


class AccountDataError(ValueError):
    """Raised when public account data is unavailable or cannot be normalized."""


@dataclass(frozen=True)
class AccountPosition:
    market_id: str
    token: str
    quantity: Decimal
    average_price: Decimal = Decimal("0")
    current_price: Decimal | None = None
    current_value: Decimal | None = None


@dataclass(frozen=True)
class AccountActivity:
    activity_id: str
    occurred_at: datetime
    activity_type: str = "unknown"
    market_id: str | None = None
    token: str | None = None
    side: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    cash_amount: Decimal | None = None
    transaction_hash: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    observed_at: datetime
    cash: Decimal | None = None
    positions: tuple[AccountPosition, ...] = ()
    account_value: Decimal | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ReadOnlyAccountSource(Protocol):
    def snapshot(self) -> AccountSnapshot:
        """Read account state without placing or signing an order."""

    def activities(self) -> tuple[AccountActivity, ...]:
        """Read public account activity without placing or signing an order."""


@dataclass(frozen=True)
class ReconciliationReport:
    cash_difference: Decimal | None
    unknown_positions: tuple[AccountPosition, ...] = ()
    missing_positions: tuple[AccountPosition, ...] = ()
    position_differences: tuple[Mapping[str, Any], ...] = ()
    status: str = "ok"


JsonTransport = Callable[[str, str, object | None], object]


def _http_json(method: str, url: str, body: object | None = None) -> object:
    """Fetch public JSON with the standard library and no auth headers."""

    encoded = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "accept": "application/json",
        "user-agent": "polymarket-trading-lab/0.1 (+public-account-data)",
    }
    if body is not None:
        headers["content-type"] = "application/json"
    request = Request(url, data=encoded, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - configured public URL
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise AccountDataError(f"public account request failed for {url}: {exc}") from exc


def _url_with_params(base_url: str, path: str, params: Mapping[str, object]) -> str:
    query = urlencode({key: str(value) for key, value in params.items()})
    separator = "&" if "?" in path else "?"
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}" + (f"{separator}{query}" if query else "")


def _decimal(value: object, field: str, *, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    try:
        result = Decimal(str(value))
    except (ArithmeticError, ValueError) as exc:
        raise AccountDataError(f"{field} must be a decimal") from exc
    if not result.is_finite():
        raise AccountDataError(f"{field} must be finite")
    return result


def _timestamp(value: object, field: str, *, default: datetime | None = None) -> datetime:
    if value is None or value == "":
        if default is not None:
            return default
        raise AccountDataError(f"{field} is missing")
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
            numeric = Decimal(str(value))
            seconds = numeric / Decimal("1000") if numeric > Decimal("100000000000") else numeric
            return datetime.fromtimestamp(float(seconds), tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ArithmeticError, TypeError, ValueError, OverflowError) as exc:
        raise AccountDataError(f"{field} must be a timestamp") from exc
    if parsed.tzinfo is None:
        raise AccountDataError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _text(raw: Mapping[str, Any], *fields: str) -> str | None:
    for field_name in fields:
        value = raw.get(field_name)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _items(raw: object, field: str) -> list[Mapping[str, Any]]:
    if isinstance(raw, Mapping):
        raw = raw.get("data", raw.get(field, []))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise AccountDataError(f"public account {field} response must be a list")
    if not all(isinstance(item, Mapping) for item in raw):
        raise AccountDataError(f"public account {field} entries must be objects")
    return list(raw)  # type: ignore[arg-type]


class PolymarketPublicAccountSource:
    """Read positions and activity from the public Polymarket Data API.

    Current official public paths default to ``/positions`` and ``/activity``
    on ``https://data-api.polymarket.com``.  Both paths remain configurable so
    a provider change fails clearly at the adapter boundary rather than being
    hidden in the reconciliation layer.
    """

    provider = "polymarket-data-api"

    def __init__(
        self,
        account_id: str,
        *,
        base_url: str = "https://data-api.polymarket.com",
        positions_path: str = "/positions",
        activity_path: str = "/activity",
        transport: JsonTransport = _http_json,
    ) -> None:
        if not account_id.strip():
            raise ValueError("account_id must not be empty")
        if not positions_path.strip() or not activity_path.strip():
            raise ValueError("positions_path and activity_path must be configured")
        self.account_id = account_id
        self.base_url = base_url.rstrip("/")
        self.positions_path = positions_path
        self.activity_path = activity_path
        self.transport = transport

    def _get(self, path: str) -> object:
        return self.transport("GET", _url_with_params(self.base_url, path, {"user": self.account_id}), None)

    def snapshot(self) -> AccountSnapshot:
        observed_at = datetime.now(timezone.utc)
        raw = self._get(self.positions_path)
        entries = _items(raw, "positions")
        positions: list[AccountPosition] = []
        for item in entries:
            asset = _text(item, "asset", "token", "asset_id")
            market_id = _text(item, "conditionId", "condition_id", "market", "marketId", "market_id")
            if not asset or not market_id:
                raise AccountDataError("public position is missing asset or conditionId")
            quantity = _decimal(item.get("size", item.get("quantity")), "position size")
            if quantity is None or quantity < 0:
                raise AccountDataError("position size must be non-negative")
            positions.append(
                AccountPosition(
                    market_id=market_id,
                    token=asset,
                    quantity=quantity,
                    average_price=_decimal(item.get("avgPrice", item.get("averagePrice")), "average price", default=Decimal("0")) or Decimal("0"),
                    current_price=_decimal(item.get("curPrice", item.get("currentPrice")), "current price"),
                    current_value=_decimal(item.get("currentValue", item.get("value")), "current value"),
                )
            )

        # The public positions surface does not currently guarantee a cash
        # balance. Preserve it when a provider response supplies one, but do
        # not invent cash from positions or call any wallet/private endpoint.
        wrapper = raw if isinstance(raw, Mapping) else {}
        cash = _decimal(_text(wrapper, "cash", "balance", "usdcBalance"), "cash")
        account_value = _decimal(_text(wrapper, "accountValue", "totalValue"), "account value")
        return AccountSnapshot(
            account_id=self.account_id,
            observed_at=observed_at,
            cash=cash,
            positions=tuple(positions),
            account_value=account_value,
            metadata={"positions_endpoint": self.positions_path, "cash_available": cash is not None},
        )

    def activities(self) -> tuple[AccountActivity, ...]:
        observed_at = datetime.now(timezone.utc)
        raw = self._get(self.activity_path)
        result: list[AccountActivity] = []
        for item in _items(raw, "activity"):
            transaction_hash = _text(item, "transactionHash", "transaction_hash", "txHash")
            activity_id = _text(item, "id", "activityId", "activity_id", "transactionHash", "transaction_hash")
            canonical = json.dumps(item, sort_keys=True, default=str, separators=(",", ":"))
            activity_id = activity_id or hashlib.sha256(canonical.encode()).hexdigest()
            result.append(
                AccountActivity(
                    activity_id=activity_id,
                    occurred_at=_timestamp(item.get("timestamp", item.get("createdAt")), "activity timestamp", default=observed_at),
                    activity_type=(_text(item, "type", "activityType") or "unknown").lower(),
                    market_id=_text(item, "conditionId", "condition_id", "market", "marketId", "market_id"),
                    token=_text(item, "asset", "token", "asset_id"),
                    side=(_text(item, "side") or "").upper() or None,
                    quantity=_decimal(item.get("size", item.get("quantity")), "activity quantity"),
                    price=_decimal(item.get("price"), "activity price"),
                    cash_amount=_decimal(item.get("usdcSize", item.get("cashAmount")), "activity cash amount"),
                    transaction_hash=transaction_hash,
                    raw=item,
                )
            )
        return tuple(result)


def reconcile_account(
    session: Session,
    observed: AccountSnapshot,
    *,
    tolerance: Decimal = Decimal("0.01"),
) -> ReconciliationReport:
    """Compare observations with paper state without changing paper state."""

    paper_cash = sum(
        (
            Decimal(str(entry.amount)) if entry.debit_account == "cash" else -Decimal(str(entry.amount))
            for entry in session.scalars(select(LedgerEntry).where(LedgerEntry.asset == "USD"))
            if entry.debit_account == "cash" or entry.credit_account == "cash"
        ),
        Decimal("0"),
    )
    cash_difference = observed.cash - paper_cash if observed.cash is not None else None

    markets = {str(m.id): m for m in session.scalars(select(Market))}
    paper_positions = list(session.scalars(select(Position)))
    observed_by_key = {(position.market_id, position.token): position for position in observed.positions}
    matched: set[tuple[str, str]] = set()
    differences: list[Mapping[str, Any]] = []
    unknown: list[AccountPosition] = []

    def aliases(market: Market, token: str) -> set[tuple[str, str]]:
        market_aliases = {str(market.id), market.market_key}
        if market.condition_id:
            market_aliases.add(market.condition_id)
        token_aliases = {token}
        if token.upper() == "YES" and market.yes_token_id:
            token_aliases.add(market.yes_token_id)
        if token.upper() == "NO" and market.no_token_id:
            token_aliases.add(market.no_token_id)
        return {(market_alias, token_alias) for market_alias in market_aliases for token_alias in token_aliases}

    for observed_position in observed.positions:
        if (observed_position.market_id, observed_position.token) not in observed_by_key:
            continue
        matched_paper: Position | None = None
        for paper_position in paper_positions:
            market = markets.get(str(paper_position.market_id))
            if market and (observed_position.market_id, observed_position.token) in aliases(market, paper_position.token):
                matched_paper = paper_position
                break
        if matched_paper is None:
            unknown.append(observed_position)
            continue
        matched.add((str(matched_paper.market_id), matched_paper.token))
        quantity_difference = observed_position.quantity - Decimal(str(matched_paper.quantity))
        price_difference = observed_position.average_price - Decimal(str(matched_paper.average_entry_price))
        if abs(quantity_difference) > tolerance or abs(price_difference) > tolerance:
            differences.append({
                "kind": "position_mismatch",
                "market_id": observed_position.market_id,
                "token": observed_position.token,
                "quantity_difference": str(quantity_difference),
                "average_price_difference": str(price_difference),
            })

    missing: list[AccountPosition] = []
    for paper_position in paper_positions:
        key = (str(paper_position.market_id), paper_position.token)
        if key in matched or Decimal(str(paper_position.quantity)) == 0:
            continue
        market = markets.get(str(paper_position.market_id))
        missing.append(AccountPosition(
            market_id=market.condition_id if market and market.condition_id else key[0],
            token=market.yes_token_id if market and paper_position.token == "YES" and market.yes_token_id else market.no_token_id if market and paper_position.token == "NO" and market.no_token_id else paper_position.token,
            quantity=Decimal(str(paper_position.quantity)),
            average_price=Decimal(str(paper_position.average_entry_price)),
        ))

    if unknown:
        differences.extend({"kind": "unknown_observed_position", "market_id": item.market_id, "token": item.token, "quantity": str(item.quantity)} for item in unknown)
    if missing:
        differences.extend({"kind": "missing_observed_position", "market_id": item.market_id, "token": item.token, "quantity": str(item.quantity)} for item in missing)
    if cash_difference is not None and abs(cash_difference) > tolerance:
        differences.append({"kind": "cash_mismatch", "difference": str(cash_difference)})

    status = "mismatch" if differences else "ok" if observed.cash is not None else "cash_unavailable"
    return ReconciliationReport(cash_difference, tuple(unknown), tuple(missing), tuple(differences), status)


def persist_account_observation(
    session: Session,
    source: ReadOnlyAccountSource,
    *,
    provider: str = "unknown",
    tolerance: Decimal = Decimal("0.01"),
) -> tuple[AccountSnapshotRecord, AccountReconciliationRecord]:
    """Fetch, persist, and reconcile one read-only account observation."""

    snapshot = source.snapshot()
    record = AccountSnapshotRecord(
        provider=provider,
        account_id=snapshot.account_id,
        observed_at=snapshot.observed_at,
        cash=snapshot.cash,
        account_value=snapshot.account_value,
        metadata_json=json.dumps(snapshot.metadata, sort_keys=True, default=str),
    )
    record.positions = [
        AccountPositionRecord(
            market_id=position.market_id,
            token=position.token,
            quantity=position.quantity,
            average_price=position.average_price,
            current_price=position.current_price,
            current_value=position.current_value,
        )
        for position in snapshot.positions
    ]
    session.add(record)
    session.flush()

    for activity in source.activities():
        exists = session.scalar(select(AccountActivityRecord).where(
            AccountActivityRecord.provider == provider,
            AccountActivityRecord.account_id == snapshot.account_id,
            AccountActivityRecord.activity_id == activity.activity_id,
        ))
        if exists is not None:
            continue
        session.add(AccountActivityRecord(
            provider=provider,
            account_id=snapshot.account_id,
            activity_id=activity.activity_id,
            occurred_at=activity.occurred_at,
            activity_type=activity.activity_type,
            market_id=activity.market_id,
            token=activity.token,
            side=activity.side,
            quantity=activity.quantity,
            price=activity.price,
            cash_amount=activity.cash_amount,
            transaction_hash=activity.transaction_hash,
            raw_json=json.dumps(activity.raw, sort_keys=True, default=str),
            observed_at=snapshot.observed_at,
        ))

    report = reconcile_account(session, snapshot, tolerance=tolerance)
    reconciliation = AccountReconciliationRecord(
        provider=provider,
        account_id=snapshot.account_id,
        snapshot_id=record.id,
        reconciled_at=utc_now(),
        paper_cash=(snapshot.cash - report.cash_difference) if report.cash_difference is not None else None,
        observed_cash=snapshot.cash,
        cash_difference=report.cash_difference,
        status=report.status,
        differences_json=json.dumps(list(report.position_differences), sort_keys=True, default=str),
    )
    session.add(reconciliation)
    session.flush()
    return record, reconciliation


def reconcile_cash(expected_cash: Decimal, observed: AccountSnapshot, tolerance: Decimal = Decimal("0.01")) -> ReconciliationReport:
    """Backward-compatible cash-only helper for callers of the Phase 3 contract."""

    difference = observed.cash - expected_cash if observed.cash is not None else None
    return ReconciliationReport(
        cash_difference=difference,
        status=("mismatch" if difference is not None and abs(difference) > tolerance else "ok" if difference is not None else "cash_unavailable"),
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
