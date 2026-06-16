"""Add modes (GAAP/operating dual basis) to price_targets

Revision ID: c5f1a9b3e740
Revises: b3e8c1a7f240
Create Date: 2026-06-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c5f1a9b3e740"
down_revision: Union[str, None] = "b3e8c1a7f240"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("price_targets", sa.Column("modes", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("price_targets", "modes")
