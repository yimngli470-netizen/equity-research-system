"""add peer_weights table

Roadmap 1.2 — measured peer-closeness weights (blend of fundamental-feature distance + trailing
return correlation; embedding cosine added later by ML M1). One row per ordered (ticker, peer)
pair; the input to peer-relative normalization (1.3).

Revision ID: c4f9a2d6b815
Revises: b2e7c1a4f309
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa

revision = "c4f9a2d6b815"
down_revision = "b2e7c1a4f309"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "peer_weights",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("peer", sa.String(length=10), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("fundamental_sim", sa.Float(), nullable=True),
        sa.Column("return_corr", sa.Float(), nullable=True),
        sa.Column("embedding_sim", sa.Float(), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "peer", name="uq_peer_ticker_peer"),
    )
    op.create_index("ix_peer_weights_ticker", "peer_weights", ["ticker"])
    op.create_index("ix_peer_weights_peer", "peer_weights", ["peer"])


def downgrade() -> None:
    op.drop_index("ix_peer_weights_peer", table_name="peer_weights")
    op.drop_index("ix_peer_weights_ticker", table_name="peer_weights")
    op.drop_table("peer_weights")
