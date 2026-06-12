from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class AnalystEstimate(Base):
    __tablename__ = "analyst_estimates"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end_date", name="uq_est_ticker_period"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    period_end_date: Mapped[date] = mapped_column(Date, index=True)
    eps_consensus: Mapped[float | None] = mapped_column(Float)
    eps_high: Mapped[float | None] = mapped_column(Float)
    eps_low: Mapped[float | None] = mapped_column(Float)
    revenue_consensus: Mapped[float | None] = mapped_column(Float)
    revenue_high: Mapped[float | None] = mapped_column(Float)
    revenue_low: Mapped[float | None] = mapped_column(Float)
    number_of_analysts: Mapped[int | None] = mapped_column(Integer)

    # Provenance + staleness (roadmap 0.4). Consensus lags reality (esp. cyclicals) and can
    # sit un-revised for months — so we down-weight it, and treat it as STALE when our copy is
    # old or analysts haven't revised recently. `revisions_30d` = count of analyst up+down
    # revisions in the last 30 days; 0 ⇒ nobody is actively maintaining this estimate.
    source: Mapped[str | None] = mapped_column(String(20))        # "yfinance" | "fmp"
    as_of: Mapped[date | None] = mapped_column(Date, index=True)  # date we fetched it
    revisions_30d: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConsensusSnapshot(Base):
    """APPEND-ONLY consensus history (roadmap 4.1) — one row per (ticker, fetch-date, period).

    `analyst_estimates` is the upsert-in-place CURRENT view; this table never updates, so the
    revisions time-series accrues from 2026-06 onward. It is the raw material for revisions-momentum
    features and the point-in-time panel (ML M4) — the data that cannot be backfilled later.
    """

    __tablename__ = "consensus_snapshots"
    __table_args__ = (
        UniqueConstraint("ticker", "as_of", "period_end_date", name="uq_consensus_snap"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)         # fetch date
    period_end_date: Mapped[date] = mapped_column(Date)           # which forward period
    eps_consensus: Mapped[float | None] = mapped_column(Float)
    revenue_consensus: Mapped[float | None] = mapped_column(Float)
    num_analysts: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
