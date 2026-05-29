"""rename ticker_onboarding -> dev_ticker_bootstrap_status

Make it obvious this is a developer-only debug table, not a product table. Same data
(one upsert row per ticker recording auto-bootstrap KPI/IR outcomes); also logged at
WARNING level now.

Revision ID: a9e2c5b7f130
Revises: f7c0a4e35d19
Create Date: 2026-05-29
"""
from alembic import op

revision = "a9e2c5b7f130"
down_revision = "f7c0a4e35d19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("ticker_onboarding", "dev_ticker_bootstrap_status")
    op.execute("ALTER TABLE dev_ticker_bootstrap_status "
               "RENAME CONSTRAINT uq_onboarding_ticker TO uq_dev_bootstrap_ticker")
    op.execute("ALTER INDEX ix_ticker_onboarding_ticker RENAME TO ix_dev_bootstrap_ticker")


def downgrade() -> None:
    op.execute("ALTER INDEX ix_dev_bootstrap_ticker RENAME TO ix_ticker_onboarding_ticker")
    op.execute("ALTER TABLE dev_ticker_bootstrap_status "
               "RENAME CONSTRAINT uq_dev_bootstrap_ticker TO uq_onboarding_ticker")
    op.rename_table("dev_ticker_bootstrap_status", "ticker_onboarding")
