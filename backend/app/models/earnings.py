from datetime import date

from sqlalchemy import BigInteger, Date, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EarningsEvent(Base):
    __tablename__ = "earnings_events"
    __table_args__ = (UniqueConstraint("ticker", "report_date", name="uq_earn_ticker_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    eps_estimate: Mapped[float | None] = mapped_column(Float)
    eps_actual: Mapped[float | None] = mapped_column(Float)
    revenue_estimate: Mapped[float | None] = mapped_column(Float)
    revenue_actual: Mapped[float | None] = mapped_column(Float)
    guidance_direction: Mapped[str | None] = mapped_column(String(20))  # 'raise', 'cut', 'maintain'
    eps_surprise_pct: Mapped[float | None] = mapped_column(Float)
    revenue_surprise_pct: Mapped[float | None] = mapped_column(Float)
