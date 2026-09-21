"""add ticker_kill_signals

Revision ID: a4d7e2c91b53
Revises: e9b3d5f1c820
Create Date: 2026-08-22

Standing, user-owned kill signals per ticker (sibling of ticker_key_metrics). See
app/models/kill_signal.py for how this differs from stock_theses.kill_criteria.
"""

import sqlalchemy as sa
from alembic import op

revision = "a4d7e2c91b53"
down_revision = "e9b3d5f1c820"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticker_kill_signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("signal", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=10), server_default="manual", nullable=False),
        sa.Column("severity", sa.String(length=10), server_default="high", nullable=False),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("by_date", sa.Date(), nullable=True),
        sa.Column("origin_as_of", sa.Date(), nullable=True),
        sa.Column("tripped_on", sa.Date(), nullable=True),
        sa.Column("tripped_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "signal", name="uq_kill_signal_ticker_signal"),
    )
    op.create_index("ix_ticker_kill_signals_ticker", "ticker_kill_signals", ["ticker"])
    op.create_index("ix_ticker_kill_signals_status", "ticker_kill_signals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ticker_kill_signals_status", table_name="ticker_kill_signals")
    op.drop_index("ix_ticker_kill_signals_ticker", table_name="ticker_kill_signals")
    op.drop_table("ticker_kill_signals")
