"""Persist public Polymarket identifiers needed by the paper worker."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0002_market_tokens"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in inspect(connection).get_columns("markets")}
    if "yes_token_id" not in columns:
        op.add_column("markets", sa.Column("yes_token_id", sa.String(length=200), nullable=True))
    if "no_token_id" not in columns:
        op.add_column("markets", sa.Column("no_token_id", sa.String(length=200), nullable=True))
    if "condition_id" not in columns:
        op.add_column("markets", sa.Column("condition_id", sa.String(length=200), nullable=True))
    if "slug" not in columns:
        op.add_column("markets", sa.Column("slug", sa.String(length=300), nullable=True))
    indexes = {index["name"] for index in inspect(connection).get_indexes("markets")}
    if "ix_markets_condition_id" not in indexes:
        op.create_index("ix_markets_condition_id", "markets", ["condition_id"], unique=False)


def downgrade() -> None:
    connection = op.get_bind()
    indexes = {index["name"] for index in inspect(connection).get_indexes("markets")}
    if "ix_markets_condition_id" in indexes:
        op.drop_index("ix_markets_condition_id", table_name="markets")
    columns = {column["name"] for column in inspect(connection).get_columns("markets")}
    for name in ("slug", "condition_id", "no_token_id", "yes_token_id"):
        if name in columns:
            op.drop_column("markets", name)
