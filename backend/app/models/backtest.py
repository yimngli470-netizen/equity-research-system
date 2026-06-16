"""Backtest results (roadmap 6.3) — the evaluation harness's output, persisted + timestamped.

A backtest is NOT part of the live decision path; it's the offline evaluator that asks "does the
deterministic screen actually rank-order forward returns?" Each run records its parameters (so a
result is reproducible) and its metrics (mean rank-IC, IC t-stat, hit rate, decile spread) plus the
full IC time series. This is the baseline any future ML model (M5) must beat out-of-sample.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    label: Mapped[str | None] = mapped_column(String(120))

    params: Mapped[dict] = mapped_column(JSONB)     # horizon, freq, lag, universe, weighting, window
    metrics: Mapped[dict] = mapped_column(JSONB)    # mean_ic, ic_t_stat, hit_rate, decile_spread, …
    ic_series: Mapped[list] = mapped_column(JSONB)  # [{date, ic, n}] per rebalance
    notes: Mapped[str | None] = mapped_column(String(2000))  # caveats / simplifying assumptions
