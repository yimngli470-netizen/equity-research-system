"""add ticker_onboarding (auto-bootstrap status: KPI gen + IR discovery)

Developer-facing record of new-stock auto-bootstrap outcomes, so failures (esp. IR
auto-discovery) are inspectable: which ticker, what URL was tried, and why it failed
(bad URL vs IP block) — to decide whether to fix the URL or run the scraper locally.

Revision ID: f7c0a4e35d19
Revises: e6b3c9d21f08
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "f7c0a4e35d19"
down_revision = "e6b3c9d21f08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticker_onboarding",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("kpi_status", sa.String(length=20)),
        sa.Column("kpi_count", sa.Integer()),
        sa.Column("ir_status", sa.String(length=20)),
        sa.Column("ir_url", sa.String(length=300)),
        sa.Column("ir_artifact_type", sa.String(length=30)),
        sa.Column("message", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", name="uq_onboarding_ticker"),
    )
    op.create_index("ix_ticker_onboarding_ticker", "ticker_onboarding", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_ticker_onboarding_ticker", table_name="ticker_onboarding")
    op.drop_table("ticker_onboarding")
