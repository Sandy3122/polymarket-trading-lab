"""Make external paper fills idempotent across worker restarts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0003_fill_event_id"
down_revision = "0002_market_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in inspect(connection).get_columns("paper_fills")}
    if "event_id" not in columns:
        op.add_column("paper_fills", sa.Column("event_id", sa.String(length=300), nullable=True))
    indexes = {index["name"] for index in inspect(connection).get_indexes("paper_fills")}
    if "ix_paper_fills_event_id" not in indexes:
        op.create_index("ix_paper_fills_event_id", "paper_fills", ["event_id"], unique=True)


def downgrade() -> None:
    connection = op.get_bind()
    indexes = {index["name"] for index in inspect(connection).get_indexes("paper_fills")}
    if "ix_paper_fills_event_id" in indexes:
        op.drop_index("ix_paper_fills_event_id", table_name="paper_fills")
    columns = {column["name"] for column in inspect(connection).get_columns("paper_fills")}
    if "event_id" in columns:
        op.drop_column("paper_fills", "event_id")
