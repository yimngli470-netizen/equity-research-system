"""add input_fingerprint to analysis_reports

Smart caching (2026-06-11): each report stores a deterministic fingerprint of the inputs it was
generated from (data identities + prompt hash). A smart-mode run recomputes and compares — a match
means the agent's inputs haven't changed, so the cached report is reused and the LLM call skipped.

Revision ID: a6d4e2f9c180
Revises: f3a9b1c8d240
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a6d4e2f9c180"
down_revision = "f3a9b1c8d240"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_reports",
        sa.Column("input_fingerprint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_reports", "input_fingerprint")
