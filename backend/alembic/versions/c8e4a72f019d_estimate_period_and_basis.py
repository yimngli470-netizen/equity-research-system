"""Preserve consensus fiscal period, date precision, and accounting basis.

Revision ID: c8e4a72f019d
Revises: b6f1a83d47c2
"""
from alembic import op
import sqlalchemy as sa

revision = "c8e4a72f019d"
down_revision = "b6f1a83d47c2"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("analyst_estimates", "consensus_snapshots"):
        op.add_column(table, sa.Column("period_type", sa.String(20), nullable=False, server_default="legacy"))
        op.add_column(table, sa.Column("period_key", sa.String(10), nullable=True))
        op.add_column(table, sa.Column("date_precision", sa.String(20), nullable=False, server_default="unknown"))
        op.add_column(table, sa.Column("accounting_basis", sa.String(30), nullable=False, server_default="provider_unspecified"))
    op.drop_constraint("uq_est_ticker_period", "analyst_estimates", type_="unique")
    op.create_unique_constraint("uq_est_ticker_period", "analyst_estimates", ["ticker", "period_end_date", "period_type"])
    op.drop_constraint("uq_consensus_snap", "consensus_snapshots", type_="unique")
    op.create_unique_constraint("uq_consensus_snap", "consensus_snapshots", ["ticker", "as_of", "period_end_date", "period_type"])


def downgrade():
    # Q4 and FY can share a date; removing type would discard valid data. Require explicit
    # resolution before a downgrade instead of silently deleting a user's estimate history.
    op.drop_constraint("uq_est_ticker_period", "analyst_estimates", type_="unique")
    op.create_unique_constraint("uq_est_ticker_period", "analyst_estimates", ["ticker", "period_end_date"])
    op.drop_constraint("uq_consensus_snap", "consensus_snapshots", type_="unique")
    op.create_unique_constraint("uq_consensus_snap", "consensus_snapshots", ["ticker", "as_of", "period_end_date"])
    for table in ("analyst_estimates", "consensus_snapshots"):
        for column in ("accounting_basis", "date_precision", "period_key", "period_type"):
            op.drop_column(table, column)
