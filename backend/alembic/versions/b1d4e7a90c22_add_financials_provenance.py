"""add provenance columns to financials (source, source_url, as_of)

Roadmap item 0.3 — makes every financial row traceable to its origin (EDGAR filing
vs yfinance), a prerequisite for the auditable research analyst.

Revision ID: b1d4e7a90c22
Revises: f2c19a4b8e10
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "b1d4e7a90c22"
down_revision = "f2c19a4b8e10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("financials", sa.Column("source", sa.String(length=20), nullable=True))
    op.add_column("financials", sa.Column("source_url", sa.String(length=300), nullable=True))
    op.add_column("financials", sa.Column("as_of", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("financials", "as_of")
    op.drop_column("financials", "source_url")
    op.drop_column("financials", "source")
