"""add kill_signal_evaluations

Revision ID: b6f1a83d47c2
Revises: a4d7e2c91b53
Create Date: 2026-08-22

Per-quarter LLM verdict on each kill signal (did the condition happen?), with evidence.
Mirrors ticker_kpi_values: idempotent per (signal, period), verbatim quote, honest "undetermined".
"""

import sqlalchemy as sa
from alembic import op

revision = "b6f1a83d47c2"
down_revision = "a4d7e2c91b53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kill_signal_evaluations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("signal_id", sa.BigInteger(), nullable=False),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("period_end_date", sa.Date(), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("source_url", sa.String(length=300), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["ticker_kill_signals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", "period_end_date", name="uq_kill_eval_signal_period"),
    )
    op.create_index("ix_kill_signal_evaluations_signal_id", "kill_signal_evaluations", ["signal_id"])
    op.create_index("ix_kill_signal_evaluations_ticker", "kill_signal_evaluations", ["ticker"])
    op.create_index("ix_kill_signal_evaluations_period", "kill_signal_evaluations", ["period_end_date"])


def downgrade() -> None:
    op.drop_index("ix_kill_signal_evaluations_period", table_name="kill_signal_evaluations")
    op.drop_index("ix_kill_signal_evaluations_ticker", table_name="kill_signal_evaluations")
    op.drop_index("ix_kill_signal_evaluations_signal_id", table_name="kill_signal_evaluations")
    op.drop_table("kill_signal_evaluations")
