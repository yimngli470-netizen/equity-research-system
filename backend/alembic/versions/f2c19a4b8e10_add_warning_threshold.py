"""Add warning_threshold to ticker_key_metrics

Revision ID: f2c19a4b8e10
Revises: e87a1c5b2f44
Create Date: 2026-05-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2c19a4b8e10"
down_revision: Union[str, None] = "e87a1c5b2f44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ticker_key_metrics",
        sa.Column("warning_threshold", sa.String(length=300), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ticker_key_metrics", "warning_threshold")
