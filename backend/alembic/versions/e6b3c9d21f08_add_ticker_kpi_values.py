"""add ticker_kpi_values (extracted, evidence-backed KPI values)

Roadmap 0.5 — stores the period-specific VALUE of each per-ticker key metric (HBM revenue,
DRAM ASP trend, inventory days, ...) extracted from the earnings transcript/IR materials,
with the verbatim evidence quote + source so the number is auditable.

Revision ID: e6b3c9d21f08
Revises: d4a8b2f60e51
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "e6b3c9d21f08"
down_revision = "d4a8b2f60e51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticker_kpi_values",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("period_end_date", sa.Date(), nullable=False),
        sa.Column("metric_name", sa.String(length=120), nullable=False),
        sa.Column("value", sa.String(length=200)),
        sa.Column("vs_target", sa.String(length=20)),
        sa.Column("trend", sa.String(length=20)),
        sa.Column("evidence_quote", sa.Text()),
        sa.Column("source", sa.String(length=20)),
        sa.Column("source_url", sa.String(length=300)),
        sa.Column("as_of", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "period_end_date", "metric_name", name="uq_kpi_val_ticker_period_name"),
    )
    op.create_index("ix_ticker_kpi_values_ticker", "ticker_kpi_values", ["ticker"])
    op.create_index("ix_ticker_kpi_values_period_end_date", "ticker_kpi_values", ["period_end_date"])


def downgrade() -> None:
    op.drop_index("ix_ticker_kpi_values_period_end_date", table_name="ticker_kpi_values")
    op.drop_index("ix_ticker_kpi_values_ticker", table_name="ticker_kpi_values")
    op.drop_table("ticker_kpi_values")
