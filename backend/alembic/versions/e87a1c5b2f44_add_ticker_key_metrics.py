"""Add ticker_key_metrics table

Revision ID: e87a1c5b2f44
Revises: d4a2878873fc
Create Date: 2026-05-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e87a1c5b2f44"
down_revision: Union[str, None] = "d4a2878873fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticker_key_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("metric_name", sa.String(length=120), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("target_or_threshold", sa.String(length=200), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "metric_name", name="uq_key_metric_ticker_name"),
    )
    op.create_index("ix_ticker_key_metrics_ticker", "ticker_key_metrics", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_ticker_key_metrics_ticker", table_name="ticker_key_metrics")
    op.drop_table("ticker_key_metrics")
