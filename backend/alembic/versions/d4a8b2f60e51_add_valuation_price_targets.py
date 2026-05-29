"""add analyst price-target columns to valuations

Roadmap 0.4 refinement — price targets (distinct from forward EPS/revenue consensus) are
frequently way off, so they are stored as a LOW-WEIGHT divergence anchor. Forward consensus
keeps normal weight.

Revision ID: d4a8b2f60e51
Revises: c3f5a1e8b740
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "d4a8b2f60e51"
down_revision = "c3f5a1e8b740"
branch_labels = None
depends_on = None

_COLS = [
    ("target_mean_price", sa.Float()),
    ("target_median_price", sa.Float()),
    ("target_high_price", sa.Float()),
    ("target_low_price", sa.Float()),
    ("num_price_target_analysts", sa.BigInteger()),
]


def upgrade() -> None:
    for name, type_ in _COLS:
        op.add_column("valuations", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLS):
        op.drop_column("valuations", name)
