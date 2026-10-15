"""Persist paper maker queue assumptions and consumption."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0006_queue_simulation"
down_revision = "0005_account_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in inspect(connection).get_columns("paper_orders")}
    additions = {
        "simulation_model": sa.Column("simulation_model", sa.String(length=20), nullable=False, server_default="baseline"),
        "queue_ahead_initial": sa.Column("queue_ahead_initial", sa.Numeric(18, 8), nullable=False, server_default="0"),
        "queue_ahead_remaining": sa.Column("queue_ahead_remaining", sa.Numeric(18, 8), nullable=False, server_default="0"),
        "queue_consumed": sa.Column("queue_consumed", sa.Numeric(18, 8), nullable=False, server_default="0"),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("paper_orders", column)


def downgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in inspect(connection).get_columns("paper_orders")}
    for name in ("queue_consumed", "queue_ahead_remaining", "queue_ahead_initial", "simulation_model"):
        if name in columns:
            op.drop_column("paper_orders", name)
