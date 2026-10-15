from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.accounts import AccountSnapshot, AccountPosition, PolymarketPublicAccountSource, persist_account_observation
from app.database import Base
from app.models import AccountActivityRecord, AccountReconciliationRecord, LedgerEntry, Market, Position


def make_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_public_account_source_uses_injectable_data_api_transport() -> None:
    calls: list[tuple[str, str]] = []

    def transport(method: str, url: str, body: object | None) -> object:
        calls.append((method, url))
        if "/positions?" in url:
            return [{
                "conditionId": "condition-1",
                "asset": "asset-yes",
                "size": "4.5",
                "avgPrice": "0.40",
                "curPrice": "0.55",
                "currentValue": "2.475",
            }]
        return [{
            "transactionHash": "0xtx",
            "timestamp": "1760000000",
            "type": "TRADE",
            "conditionId": "condition-1",
            "asset": "asset-yes",
            "side": "BUY",
            "size": "4.5",
            "price": "0.40",
            "usdcSize": "1.8",
        }]

    source = PolymarketPublicAccountSource(
        "0xpublic",
        base_url="https://data.test",
        transport=transport,
    )
    snapshot = source.snapshot()
    activities = source.activities()

    assert snapshot.cash is None
    assert snapshot.positions[0].market_id == "condition-1"
    assert snapshot.positions[0].quantity == Decimal("4.5")
    assert activities[0].activity_id == "0xtx"
    assert any(url == "https://data.test/positions?user=0xpublic" for _, url in calls)
    assert any(url == "https://data.test/activity?user=0xpublic" for _, url in calls)


def test_account_observation_persists_and_reconciles_without_mutating_paper() -> None:
    session = make_session()
    market = Market(
        market_key="market-key",
        condition_id="condition-1",
        yes_token_id="asset-yes",
        no_token_id="asset-no",
        question="Question",
        end_time=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    session.add(market)
    session.flush()
    session.add_all([
        LedgerEntry(
            entry_type="initial_funding",
            debit_account="cash",
            credit_account="paper_capital",
            asset="USD",
            amount=Decimal("100"),
        ),
        Position(
            market_id=market.id,
            token="YES",
            quantity=Decimal("4.5"),
            average_entry_price=Decimal("0.40"),
            realized_pnl=Decimal("0"),
        ),
    ])
    session.flush()

    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class FakeSource:
        provider = "mock-public"

        def snapshot(self) -> AccountSnapshot:
            return AccountSnapshot(
                account_id="0xpublic",
                observed_at=observed_at,
                positions=(AccountPosition("condition-1", "asset-yes", Decimal("4.5"), Decimal("0.40")),),
            )

        def activities(self):
            from app.accounts import AccountActivity

            return (AccountActivity("tx-1", observed_at, activity_type="trade"),)

    before_positions = [(position.market_id, position.token, position.quantity) for position in session.scalars(select(Position))]
    before_ledger_count = len(session.scalars(select(LedgerEntry)).all())

    snapshot, reconciliation = persist_account_observation(session, FakeSource(), provider="mock-public")
    session.commit()

    assert snapshot.id > 0
    assert reconciliation.status == "cash_unavailable"
    assert len(session.scalars(select(AccountActivityRecord)).all()) == 1
    assert len(session.scalars(select(AccountReconciliationRecord)).all()) == 1
    assert [(position.market_id, position.token, position.quantity) for position in session.scalars(select(Position))] == before_positions
    assert len(session.scalars(select(LedgerEntry)).all()) == before_ledger_count

    # Activity persistence is idempotent even when a snapshot is synced again.
    persist_account_observation(session, FakeSource(), provider="mock-public")
    session.commit()
    assert len(session.scalars(select(AccountActivityRecord)).all()) == 1
