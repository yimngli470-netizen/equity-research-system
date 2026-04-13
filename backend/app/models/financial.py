from datetime import date

from sqlalchemy import BigInteger, Date, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Financial(Base):
    __tablename__ = "financials"
    __table_args__ = (UniqueConstraint("ticker", "period_end_date", name="uq_fin_ticker_period"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    period: Mapped[str] = mapped_column(String(20))  # e.g. "Q2 FY2026"
    period_end_date: Mapped[date] = mapped_column(Date)

    # Income statement
    revenue: Mapped[float | None] = mapped_column(Float)
    gross_profit: Mapped[float | None] = mapped_column(Float)
    operating_income: Mapped[float | None] = mapped_column(Float)
    net_income: Mapped[float | None] = mapped_column(Float)
    eps: Mapped[float | None] = mapped_column(Float)

    # Cash flow
    free_cash_flow: Mapped[float | None] = mapped_column(Float)
    operating_cash_flow: Mapped[float | None] = mapped_column(Float)

    # Balance sheet
    total_debt: Mapped[float | None] = mapped_column(Float)
    cash_and_equivalents: Mapped[float | None] = mapped_column(Float)
    total_assets: Mapped[float | None] = mapped_column(Float)
    total_equity: Mapped[float | None] = mapped_column(Float)
    shares_outstanding: Mapped[float | None] = mapped_column(Float)


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end_date", "segment_name", name="uq_seg_ticker_period_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    period_end_date: Mapped[date] = mapped_column(Date)
    segment_name: Mapped[str] = mapped_column(String(200))
    revenue: Mapped[float | None] = mapped_column(Float)
    growth_yoy: Mapped[float | None] = mapped_column(Float)
