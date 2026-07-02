"""add financials.filed_date (M4 stage 2 — exact point-in-time gating)

Revision ID: d7a2c4e8b910
Revises: c5f1a9b3e740
Create Date: 2026-07-01
"""

import sqlalchemy as sa
from alembic import op

revision = "d7a2c4e8b910"
down_revision = "c5f1a9b3e740"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("financials", sa.Column("filed_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("financials", "filed_date")
