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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
