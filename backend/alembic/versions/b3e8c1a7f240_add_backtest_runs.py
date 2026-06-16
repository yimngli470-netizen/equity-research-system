"""Add backtest_runs (roadmap 6.3)

Revision ID: b3e8c1a7f240
Revises: a1f4b7c9e230
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b3e8c1a7f240"
down_revision: Union[str, None] = "a1f4b7c9e230"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("ic_series", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("backtest_runs")
