"""add panel_versions + panel_rows (M4 stage 3 — materialized feature/label store)

Revision ID: e9b3d5f1c820
Revises: d7a2c4e8b910
Create Date: 2026-07-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "e9b3d5f1c820"
down_revision = "d7a2c4e8b910"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "panel_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.String(2000), nullable=True),
    )
    op.create_table(
        "panel_rows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("version_id", sa.BigInteger(),
                  sa.ForeignKey("panel_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("features", JSONB, nullable=False),
        sa.Column("label", sa.Float(), nullable=True),
    )
    op.create_index("ix_panel_rows_version_id", "panel_rows", ["version_id"])
    op.create_index("ix_panel_rows_version_date", "panel_rows", ["version_id", "date"])


def downgrade() -> None:
    op.drop_table("panel_rows")
    op.drop_table("panel_versions")
