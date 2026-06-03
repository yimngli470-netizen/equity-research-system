"""add judge leaning + conviction to stock_decisions

Roadmap 2.4 — the dialectic judge (2.1) now binds the decision: its leaning/conviction can cap the
final signal and confidence. Persist them so the UI can show why the signal was adjusted.

Revision ID: d7b3e9c4a210
Revises: c4f9a2d6b815
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "d7b3e9c4a210"
down_revision = "c4f9a2d6b815"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_decisions", sa.Column("judge_leaning", sa.String(length=20), nullable=True))
    op.add_column("stock_decisions", sa.Column("judge_conviction", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_decisions", "judge_conviction")
    op.drop_column("stock_decisions", "judge_leaning")
