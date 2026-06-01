"""add business-model archetype columns to stocks

Roadmap 1.1 — a grounded-LLM archetype label (cyclical-commodity / secular-grower / platform /
mature-compounder / financial / deep-value-turnaround) plus the measured quant profile it was
grounded on (archetype_features) and a short rationale. Conditions peer-relative normalization
(1.3) and archetype weight profiles (1.4). Re-runnable, so all nullable.

Revision ID: b2e7c1a4f309
Revises: a9e2c5b7f130
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2e7c1a4f309"
down_revision = "a9e2c5b7f130"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stocks", sa.Column("archetype", sa.String(length=40), nullable=True))
    op.add_column("stocks", sa.Column("archetype_features", postgresql.JSONB(), nullable=True))
    op.add_column("stocks", sa.Column("archetype_rationale", sa.String(length=1000), nullable=True))
    op.add_column("stocks", sa.Column("archetype_as_of", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("stocks", "archetype_as_of")
    op.drop_column("stocks", "archetype_rationale")
    op.drop_column("stocks", "archetype_features")
    op.drop_column("stocks", "archetype")
