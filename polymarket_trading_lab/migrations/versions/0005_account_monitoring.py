"""Add read-only account snapshots, public activity, and reconciliation history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0005_account_monitoring"
down_revision = "0004_market_timing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "account_snapshots" not in tables:
        op.create_table(
            "account_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("account_id", sa.String(length=200), nullable=False),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.Column("cash", sa.Numeric(18, 8), nullable=True),
            sa.Column("account_value", sa.Numeric(18, 8), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_account_snapshots_provider", "account_snapshots", ["provider"])
        op.create_index("ix_account_snapshots_account_id", "account_snapshots", ["account_id"])
        op.create_index("ix_account_snapshots_observed_at", "account_snapshots", ["observed_at"])

    if "account_snapshot_positions" not in tables:
        op.create_table(
            "account_snapshot_positions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("account_snapshots.id"), nullable=False),
            sa.Column("market_id", sa.String(length=300), nullable=False),
            sa.Column("token", sa.String(length=300), nullable=False),
            sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
            sa.Column("average_price", sa.Numeric(18, 8), nullable=False),
            sa.Column("current_price", sa.Numeric(18, 8), nullable=True),
            sa.Column("current_value", sa.Numeric(18, 8), nullable=True),
            sa.UniqueConstraint("snapshot_id", "market_id", "token", name="uq_account_snapshot_position"),
        )
        op.create_index("ix_account_snapshot_positions_snapshot_id", "account_snapshot_positions", ["snapshot_id"])
        op.create_index("ix_account_snapshot_positions_market_id", "account_snapshot_positions", ["market_id"])

    if "account_activities" not in tables:
        op.create_table(
            "account_activities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("account_id", sa.String(length=200), nullable=False),
            sa.Column("activity_id", sa.String(length=300), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("activity_type", sa.String(length=50), nullable=False),
            sa.Column("market_id", sa.String(length=300), nullable=True),
            sa.Column("token", sa.String(length=300), nullable=True),
            sa.Column("side", sa.String(length=10), nullable=True),
            sa.Column("quantity", sa.Numeric(18, 8), nullable=True),
            sa.Column("price", sa.Numeric(18, 8), nullable=True),
            sa.Column("cash_amount", sa.Numeric(18, 8), nullable=True),
            sa.Column("transaction_hash", sa.String(length=300), nullable=True),
            sa.Column("raw_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("provider", "account_id", "activity_id", name="uq_account_activity"),
        )
        op.create_index("ix_account_activities_provider", "account_activities", ["provider"])
        op.create_index("ix_account_activities_account_id", "account_activities", ["account_id"])
        op.create_index("ix_account_activities_occurred_at", "account_activities", ["occurred_at"])
        op.create_index("ix_account_activities_market_id", "account_activities", ["market_id"])

    if "account_reconciliations" not in tables:
        op.create_table(
            "account_reconciliations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("account_id", sa.String(length=200), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("account_snapshots.id"), nullable=False),
            sa.Column("reconciled_at", sa.DateTime(), nullable=False),
            sa.Column("paper_cash", sa.Numeric(18, 8), nullable=True),
            sa.Column("observed_cash", sa.Numeric(18, 8), nullable=True),
            sa.Column("cash_difference", sa.Numeric(18, 8), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("differences_json", sa.Text(), nullable=False, server_default="[]"),
        )
        op.create_index("ix_account_reconciliations_provider", "account_reconciliations", ["provider"])
        op.create_index("ix_account_reconciliations_account_id", "account_reconciliations", ["account_id"])
        op.create_index("ix_account_reconciliations_snapshot_id", "account_reconciliations", ["snapshot_id"])
        op.create_index("ix_account_reconciliations_reconciled_at", "account_reconciliations", ["reconciled_at"])
        op.create_index("ix_account_reconciliations_status", "account_reconciliations", ["status"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "account_reconciliations" in tables:
        op.drop_table("account_reconciliations")
    if "account_activities" in tables:
        op.drop_table("account_activities")
    if "account_snapshot_positions" in tables:
        op.drop_table("account_snapshot_positions")
    if "account_snapshots" in tables:
        op.drop_table("account_snapshots")
