"""Persist dashboard-edited runtime settings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0008_app_settings"
down_revision = "0007_position_exits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "app_settings" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=80), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if "app_settings" in inspect(op.get_bind()).get_table_names():
        op.drop_table("app_settings")
