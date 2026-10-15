"""Add per-position stop-loss and take-profit levels."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0007_position_exits"
down_revision = "0006_queue_simulation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "position_exits" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "position_exits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=False, index=True),
        sa.Column("token", sa.String(length=10), nullable=False),
        sa.Column("stop_loss_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("take_profit_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("triggered_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("market_id", "token", name="uq_position_exit_market_token"),
    )


def downgrade() -> None:
    if "position_exits" in inspect(op.get_bind()).get_table_names():
        op.drop_table("position_exits")
