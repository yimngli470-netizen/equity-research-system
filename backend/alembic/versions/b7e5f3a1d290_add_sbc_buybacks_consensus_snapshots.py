"""4.1: SBC/buybacks columns on financials + consensus_snapshots history table

Roadmap 4.1 (balance-sheet completion + accrue-now data):
- financials gains stock_based_comp + buybacks (quarterly flows, YTD-differenced from EDGAR;
  total_debt/shares_outstanding columns already existed and are now actually populated).
- consensus_snapshots: an APPEND-ONLY history of forward consensus per ingestion run — the
  revisions time-series the backtest/revisions features need, which upsert-in-place was destroying.

Revision ID: b7e5f3a1d290
Revises: a6d4e2f9c180
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = "b7e5f3a1d290"
down_revision = "a6d4e2f9c180"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("financials", sa.Column("stock_based_comp", sa.Float(), nullable=True))
    op.add_column("financials", sa.Column("buybacks", sa.Float(), nullable=True))

    op.create_table(
        "consensus_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("ticker", sa.String(length=10), nullable=False, index=True),
        sa.Column("as_of", sa.Date(), nullable=False, index=True),
        sa.Column("period_end_date", sa.Date(), nullable=False),
        sa.Column("eps_consensus", sa.Float(), nullable=True),
        sa.Column("revenue_consensus", sa.Float(), nullable=True),
        sa.Column("num_analysts", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "as_of", "period_end_date", name="uq_consensus_snap"),
    )


def downgrade() -> None:
    op.drop_table("consensus_snapshots")
    op.drop_column("financials", "buybacks")
    op.drop_column("financials", "stock_based_comp")
