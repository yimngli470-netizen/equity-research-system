from datetime import date

from sqlalchemy import BigInteger, Date, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class QuantFeature(Base):
    __tablename__ = "quant_features"
    __table_args__ = (
        UniqueConstraint("ticker", "date", "feature_name", name="uq_qf_ticker_date_feature"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    feature_name: Mapped[str] = mapped_column(String(100))
    feature_value: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(50))  # 'growth', 'profitability', 'valuation', etc.


class StockScore(Base):
    __tablename__ = "stock_scores"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_score_ticker_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    growth_score: Mapped[float] = mapped_column(Float)
    profitability_score: Mapped[float] = mapped_column(Float)
    valuation_score: Mapped[float] = mapped_column(Float)
    momentum_score: Mapped[float] = mapped_column(Float)
    sentiment_score: Mapped[float] = mapped_column(Float)
    risk_score: Mapped[float] = mapped_column(Float)
    event_score: Mapped[float] = mapped_column(Float)
    composite_score: Mapped[float] = mapped_column(Float)
    signal: Mapped[str] = mapped_column(String(20))  # 'STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL'
