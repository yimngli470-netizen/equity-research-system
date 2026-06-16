"""Add coverage_tier + archetype_source to stocks (roadmap 6.1)

Revision ID: f8d3a1b9c620
Revises: e4b2c8d6f130
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8d3a1b9c620"
down_revision: Union[str, None] = "e4b2c8d6f130"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Two-tier universe: existing names are all watchlist (full pipeline). New tier-1 batch names
    # land as "universe". Server default keeps existing rows + future inserts well-defined.
    op.add_column(
        "stocks",
        sa.Column("coverage_tier", sa.String(length=20), nullable=False, server_default="watchlist"),
    )
    # archetype_source: existing labels were all LLM-grounded.
    op.add_column("stocks", sa.Column("archetype_source", sa.String(length=10), nullable=True))
    op.execute("UPDATE stocks SET archetype_source = 'llm' WHERE archetype IS NOT NULL")


def downgrade() -> None:
    op.drop_column("stocks", "archetype_source")
    op.drop_column("stocks", "coverage_tier")
