"""Add source/source_url/has_qa columns to earnings_transcripts

Revision ID: d4a2878873fc
Revises: 4cc0d92dd20c
Create Date: 2026-05-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a2878873fc"
down_revision: Union[str, None] = "4cc0d92dd20c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "earnings_transcripts",
        sa.Column("source", sa.String(length=20), nullable=False, server_default="fmp"),
    )
    op.add_column(
        "earnings_transcripts",
        sa.Column("source_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "earnings_transcripts",
        sa.Column("has_qa", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("earnings_transcripts", "has_qa")
    op.drop_column("earnings_transcripts", "source_url")
    op.drop_column("earnings_transcripts", "source")
