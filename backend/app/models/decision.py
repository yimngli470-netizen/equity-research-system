"""Decision model — stores final signal, risk flags, and reasoning per ticker."""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockDecision(Base):
    __tablename__ = "stock_decisions"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_decision_ticker_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)

    # Raw signal from scoring (before risk adjustment)
    raw_signal: Mapped[str] = mapped_column(String(20))
    raw_composite: Mapped[float] = mapped_column(Float)

    # Final signal after risk flag adjustments
    final_signal: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[str] = mapped_column(String(20))  # 'high', 'moderate', 'low'

    # Risk flags as JSONB array
    # Each flag: {level, rule, message, category}
    risk_flags: Mapped[list] = mapped_column(JSONB, default=list)

    # Reasoning — why the final signal was chosen
    reasoning: Mapped[str] = mapped_column(String(1000))

    # The dialectic judge's verdict (roadmap 2.4) — binds the decision: a bearish or low-conviction
    # judge caps the final signal/confidence even when the quant screen is high.
    judge_leaning: Mapped[str | None] = mapped_column(String(20))
    judge_conviction: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
