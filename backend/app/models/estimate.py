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
