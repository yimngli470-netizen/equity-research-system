"""add stock_theses (thesis journal)

Roadmap 3.1 — an immutable per-run snapshot of the judge verdict + dated kill-criteria + price/
fair-value, for the accountability loop (3.2 grading, 3.3 calibration).

Revision ID: e8c1d2f5a730
Revises: d7b3e9c4a210
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e8c1d2f5a730"
down_revision = "d7b3e9c4a210"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_theses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("archetype", sa.String(length=40), nullable=True),
        sa.Column("leaning", sa.String(length=20), nullable=True),
        sa.Column("conviction", sa.Float(), nullable=True),
        sa.Column("verdict_summary", sa.Text(), nullable=True),
        sa.Column("fair_value", sa.Float(), nullable=True),
        sa.Column("price_at", sa.Float(), nullable=True),
        sa.Column("composite", sa.Float(), nullable=True),
        sa.Column("signal", sa.String(length=20), nullable=True),
        sa.Column("decision_signal", sa.String(length=20), nullable=True),
        sa.Column("kill_criteria", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("graded_at", sa.Date(), nullable=True),
        sa.Column("outcome", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "as_of", name="uq_thesis_ticker_asof"),
    )
    op.create_index("ix_stock_theses_ticker", "stock_theses", ["ticker"])
    op.create_index("ix_stock_theses_as_of", "stock_theses", ["as_of"])


def downgrade() -> None:
    op.drop_index("ix_stock_theses_as_of", table_name="stock_theses")
    op.drop_index("ix_stock_theses_ticker", table_name="stock_theses")
    op.drop_table("stock_theses")
