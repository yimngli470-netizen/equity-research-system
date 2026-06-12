"""add price_targets table (roadmap 4.3)

Revision ID: d2c8e6f4a510
Revises: c9a7d5e3f410
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d2c8e6f4a510"
down_revision = "c9a7d5e3f410"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_targets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("ticker", sa.String(length=10), nullable=False, index=True),
        sa.Column("as_of", sa.Date(), nullable=False, index=True),
        sa.Column("archetype", sa.String(length=40), nullable=True),
        sa.Column("horizon_months", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("fair_value", sa.Float(), nullable=True),
        sa.Column("price_target", sa.Float(), nullable=True),
        sa.Column("price_at", sa.Float(), nullable=True),
        sa.Column("upside", sa.Float(), nullable=True),
        sa.Column("street_target_mean", sa.Float(), nullable=True),
        sa.Column("probabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scenarios", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("method", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("wacc", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sensitivity", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("forecast_as_of", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "as_of", name="uq_pt_ticker_asof"),
    )


def downgrade() -> None:
    op.drop_table("price_targets")
