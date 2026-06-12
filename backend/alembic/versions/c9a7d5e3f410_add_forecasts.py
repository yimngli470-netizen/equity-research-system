"""add forecasts table (roadmap 4.2 — the analyst's own numbers)

Revision ID: c9a7d5e3f410
Revises: b7e5f3a1d290
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c9a7d5e3f410"
down_revision = "b7e5f3a1d290"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecasts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("ticker", sa.String(length=10), nullable=False, index=True),
        sa.Column("as_of", sa.Date(), nullable=False, index=True),
        sa.Column("archetype", sa.String(length=40), nullable=True),
        sa.Column("horizon_quarters", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("assumptions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("projections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("base_next_q_eps", sa.Float(), nullable=True),
        sa.Column("base_ntm_eps", sa.Float(), nullable=True),
        sa.Column("base_ntm_revenue", sa.Float(), nullable=True),
        sa.Column("street_next_q_eps", sa.Float(), nullable=True),
        sa.Column("eps_vs_street_next_q", sa.Float(), nullable=True),
        sa.Column("input_fingerprint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("graded_at", sa.Date(), nullable=True),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "as_of", name="uq_forecast_ticker_asof"),
    )


def downgrade() -> None:
    op.drop_table("forecasts")
