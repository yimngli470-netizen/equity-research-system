"""Materialized point-in-time panel (M4 stage 3) — the persisted feature/label store.

Before M4 the (ticker, date) → features → label panel was recomputed IN MEMORY on every backtest or
M5 run: not reproducible (data underneath keeps moving), not auditable (nothing to query when a
number looks wrong), and slow (full recompute each time). Materializing fixes all three: a training
run can pin the EXACT rows a model saw (`panel_version_id`), leakage checks run once against the
stored table, and downstream consumers just read.

Versioning, not overwriting: each build writes a new `PanelVersion` with its full recipe (params,
universe mode, feature list, gating) plus the rows. Old versions stay — that's what makes results
reproducible after the underlying data or code changes.

Features live in one JSONB column rather than typed columns: the feature set is expected to grow
(quality/size/volatility are next) and per-version feature lists are already recorded in the recipe.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PanelVersion(Base):
    __tablename__ = "panel_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    label: Mapped[str | None] = mapped_column(String(120))

    # The full recipe: horizon/rebalance days, universe mode (point-in-time | current-snapshot),
    # gating (filed_date | 75d-lag), feature_cols, label_col, n_tickers — enough to rebuild.
    params: Mapped[dict] = mapped_column(JSONB)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    notes: Mapped[str | None] = mapped_column(String(2000))


class PanelRow(Base):
    __tablename__ = "panel_rows"
    __table_args__ = (Index("ix_panel_rows_version_date", "version_id", "date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("panel_versions.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(10))
    date: Mapped[date] = mapped_column(Date)

    features: Mapped[dict] = mapped_column(JSONB)          # raw point-in-time features (pre-ranking)
    label: Mapped[float | None] = mapped_column(Float)     # forward excess return vs SPY
