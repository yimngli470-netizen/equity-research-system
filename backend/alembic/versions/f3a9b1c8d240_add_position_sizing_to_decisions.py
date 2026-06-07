"""add position_sizing to stock_decisions

Roadmap 3.4 — the decision now carries a sizing block (target weight + the conviction × confidence ×
risk × concentration × calibration multiplier stack), so the recommendation is "how much", not just
which way. Stored as JSONB for schema flexibility.

Revision ID: f3a9b1c8d240
Revises: e8c1d2f5a730
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f3a9b1c8d240"
down_revision = "e8c1d2f5a730"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_decisions",
        sa.Column("position_sizing", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stock_decisions", "position_sizing")
