"""Persist market start time and category for explicit worker filtering."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0004_market_timing"
down_revision = "0003_fill_event_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in inspect(connection).get_columns("markets")}
    if "start_time" not in columns:
        op.add_column("markets", sa.Column("start_time", sa.DateTime(), nullable=True))
    if "category" not in columns:
        op.add_column("markets", sa.Column("category", sa.String(length=100), nullable=True))
    indexes = {index["name"] for index in inspect(connection).get_indexes("markets")}
    if "ix_markets_start_time" not in indexes:
        op.create_index("ix_markets_start_time", "markets", ["start_time"], unique=False)


def downgrade() -> None:
    connection = op.get_bind()
    indexes = {index["name"] for index in inspect(connection).get_indexes("markets")}
    if "ix_markets_start_time" in indexes:
        op.drop_index("ix_markets_start_time", table_name="markets")
    columns = {column["name"] for column in inspect(connection).get_columns("markets")}
    if "category" in columns:
        op.drop_column("markets", "category")
    if "start_time" in columns:
        op.drop_column("markets", "start_time")
