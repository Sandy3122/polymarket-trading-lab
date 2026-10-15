"""SQLAlchemy 2.0 domain models for paper trading."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    """Store UTC consistently even on SQLite, which drops timezone metadata."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    yes_token_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    no_token_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    condition_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    slug: Mapped[str | None] = mapped_column(String(300), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    winning_token: Mapped[str | None] = mapped_column(String(10), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    orders: Mapped[list["PaperOrder"]] = relationship(back_populates="market")
    positions: Mapped[list["Position"]] = relationship(back_populates="market")


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    token: Mapped[str] = mapped_column(String(10))
    side: Mapped[str] = mapped_column(String(4))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    simulation_model: Mapped[str] = mapped_column(String(20), default="baseline")
    queue_ahead_initial: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    queue_ahead_remaining: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    queue_consumed: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)

    market: Mapped[Market] = relationship(back_populates="orders")
    fills: Mapped[list["PaperFill"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class PaperFill(Base):
    __tablename__ = "paper_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("paper_orders.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    event_id: Mapped[str | None] = mapped_column(String(300), nullable=True, unique=True, index=True)
    filled_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    order: Mapped[PaperOrder] = relationship(back_populates="fills")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("market_id", "token", name="uq_position_market_token"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    token: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    average_entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)

    market: Mapped[Market] = relationship(back_populates="positions")


class LedgerEntry(Base):
    """A small double-entry-ish journal.

    Each row transfers one asset/quantity between two named accounts.  Cash
    and token transfers are recorded separately, which keeps the journal
    understandable without pretending that shares and dollars share a unit.
    """

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_type: Mapped[str] = mapped_column(String(30), index=True)
    debit_account: Mapped[str] = mapped_column(String(100))
    credit_account: Mapped[str] = mapped_column(String(100))
    asset: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("paper_orders.id"), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)


class StrategyDecision(Base):
    __tablename__ = "strategy_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    strategy_name: Mapped[str] = mapped_column(String(50))
    decision_time: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    reason: Mapped[str] = mapped_column(Text)
    intents_json: Mapped[str] = mapped_column(Text, default="[]")
    observations_json: Mapped[str] = mapped_column(Text, default="{}")


class SystemHealth(Base):
    __tablename__ = "system_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)


class AccountSnapshotRecord(Base):
    """Immutable observation of a provider account at one point in time."""

    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    account_id: Mapped[str] = mapped_column(String(200), index=True)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    account_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    positions: Mapped[list["AccountPositionRecord"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )
    reconciliations: Mapped[list["AccountReconciliationRecord"]] = relationship(
        back_populates="snapshot"
    )


class AccountPositionRecord(Base):
    """Positions belonging to an observed account snapshot."""

    __tablename__ = "account_snapshot_positions"
    __table_args__ = (UniqueConstraint("snapshot_id", "market_id", "token", name="uq_account_snapshot_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("account_snapshots.id"), index=True)
    market_id: Mapped[str] = mapped_column(String(300), index=True)
    token: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    average_price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    snapshot: Mapped[AccountSnapshotRecord] = relationship(back_populates="positions")


class AccountActivityRecord(Base):
    """Normalized public account activity, retained independently of snapshots."""

    __tablename__ = "account_activities"
    __table_args__ = (UniqueConstraint("provider", "account_id", "activity_id", name="uq_account_activity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    account_id: Mapped[str] = mapped_column(String(200), index=True)
    activity_id: Mapped[str] = mapped_column(String(300))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    activity_type: Mapped[str] = mapped_column(String(50), default="unknown")
    market_id: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    token: Mapped[str | None] = mapped_column(String(300), nullable=True)
    side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    transaction_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AccountReconciliationRecord(Base):
    """Result of comparing an observed account with the paper portfolio."""

    __tablename__ = "account_reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    account_id: Mapped[str] = mapped_column(String(200), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("account_snapshots.id"), index=True)
    reconciled_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    paper_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    observed_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cash_difference: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    differences_json: Mapped[str] = mapped_column(Text, default="[]")

    snapshot: Mapped[AccountSnapshotRecord] = relationship(back_populates="reconciliations")


class ReplayRun(Base):
    """A persisted, isolated paper execution of normalized market events."""

    __tablename__ = "replay_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(300), default="api")
    strategy_name: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    market_count: Mapped[int] = mapped_column(Integer, default=0)
    decision_count: Mapped[int] = mapped_column(Integer, default=0)
    actionable_decision_count: Mapped[int] = mapped_column(Integer, default=0)
    orders_created: Mapped[int] = mapped_column(Integer, default=0)
    fills: Mapped[int] = mapped_column(Integer, default=0)
    settlements: Mapped[int] = mapped_column(Integer, default=0)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    final_cash: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    positions_json: Mapped[str] = mapped_column(Text, default="[]")
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)

    decisions: Mapped[list["ReplayDecision"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ReplayDecision.decision_time"
    )


class ReplayDecision(Base):
    """The decision trace belonging to one persisted replay run."""

    __tablename__ = "replay_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("replay_runs.id"), index=True)
    market_key: Mapped[str] = mapped_column(String(200), index=True)
    strategy_name: Mapped[str] = mapped_column(String(50))
    decision_time: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    reason: Mapped[str] = mapped_column(Text)
    intents_json: Mapped[str] = mapped_column(Text, default="[]")
    observations_json: Mapped[str] = mapped_column(Text, default="{}")

    run: Mapped[ReplayRun] = relationship(back_populates="decisions")
