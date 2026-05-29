"""add provenance + staleness columns to analyst_estimates

Roadmap item 0.4 — consensus is used only as a low-weight divergence check and must be
discountable when stale, so we record where it came from, when we fetched it, and how
recently analysts revised it.

Revision ID: c3f5a1e8b740
Revises: b1d4e7a90c22
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "c3f5a1e8b740"
down_revision = "b1d4e7a90c22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyst_estimates", sa.Column("source", sa.String(length=20), nullable=True))
    op.add_column("analyst_estimates", sa.Column("as_of", sa.Date(), nullable=True))
    op.add_column("analyst_estimates", sa.Column("revisions_30d", sa.Integer(), nullable=True))
    op.create_index("ix_analyst_estimates_as_of", "analyst_estimates", ["as_of"])


def downgrade() -> None:
    op.drop_index("ix_analyst_estimates_as_of", table_name="analyst_estimates")
    op.drop_column("analyst_estimates", "revisions_30d")
    op.drop_column("analyst_estimates", "as_of")
    op.drop_column("analyst_estimates", "source")
