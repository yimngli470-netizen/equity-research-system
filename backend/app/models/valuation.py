from datetime import date

from sqlalchemy import BigInteger, Date, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Valuation(Base):
    """Point-in-time valuation snapshot — captured daily from yfinance."""

    __tablename__ = "valuations"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_val_ticker_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)

    # Valuation multiples
    forward_pe: Mapped[float | None] = mapped_column(Float)
    trailing_pe: Mapped[float | None] = mapped_column(Float)
    peg_ratio: Mapped[float | None] = mapped_column(Float)
    price_to_sales: Mapped[float | None] = mapped_column(Float)
    price_to_book: Mapped[float | None] = mapped_column(Float)
    ev_to_revenue: Mapped[float | None] = mapped_column(Float)
    ev_to_ebitda: Mapped[float | None] = mapped_column(Float)

    # Per-share metrics
    trailing_eps: Mapped[float | None] = mapped_column(Float)
    forward_eps: Mapped[float | None] = mapped_column(Float)

    # Growth rates (from info)
    earnings_growth: Mapped[float | None] = mapped_column(Float)
    revenue_growth: Mapped[float | None] = mapped_column(Float)

    # Margins
    gross_margins: Mapped[float | None] = mapped_column(Float)
    operating_margins: Mapped[float | None] = mapped_column(Float)
    profit_margins: Mapped[float | None] = mapped_column(Float)

    # Size
    market_cap: Mapped[float | None] = mapped_column(Float)
    enterprise_value: Mapped[float | None] = mapped_column(Float)
    shares_outstanding: Mapped[float | None] = mapped_column(Float)

    # Analyst PRICE TARGETS (roadmap 0.4). Distinct from forward EPS/revenue consensus:
    # price targets are frequently way off, so they are a LOW-WEIGHT divergence anchor only.
    target_mean_price: Mapped[float | None] = mapped_column(Float)
    target_median_price: Mapped[float | None] = mapped_column(Float)
    target_high_price: Mapped[float | None] = mapped_column(Float)
    target_low_price: Mapped[float | None] = mapped_column(Float)
    num_price_target_analysts: Mapped[int | None] = mapped_column(BigInteger)
