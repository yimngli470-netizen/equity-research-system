"""Add portfolio_positions + portfolio_account (roadmap 6.2)

Revision ID: a1f4b7c9e230
Revises: f8d3a1b9c620
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1f4b7c9e230"
down_revision: Union[str, None] = "f8d3a1b9c620"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("shares", sa.Float(), nullable=False),
        sa.Column("cost_basis", sa.Float(), nullable=True),
        sa.Column("opened_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_portfolio_positions_ticker", "portfolio_positions", ["ticker"], unique=True)

    op.create_table(
        "portfolio_account",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("cash", sa.Float(), nullable=False, server_default="0"),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("portfolio_account")
    op.drop_index("ix_portfolio_positions_ticker", table_name="portfolio_positions")
    op.drop_table("portfolio_positions")
