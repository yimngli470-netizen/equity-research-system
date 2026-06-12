"""add research_notes table (roadmap 5.1)

Revision ID: e4b2c8d6f130
Revises: d2c8e6f4a510
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e4b2c8d6f130"
down_revision = "d2c8e6f4a510"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_notes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("ticker", sa.String(length=10), nullable=False, index=True),
        sa.Column("as_of", sa.Date(), nullable=False, index=True),
        sa.Column("note_md", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "as_of", name="uq_note_ticker_asof"),
    )


def downgrade() -> None:
    op.drop_table("research_notes")
