"""Thesis journal (roadmap 3.1) — an immutable per-run snapshot of the analyst's verdict.

Each Run-Full-Pipeline writes one thesis per ticker (deduped by date): the judge's leaning +
conviction + DATED kill-criteria, the valuation fair value, and the price/composite/decision at the
time. This is the record the accountability loop grades against later (3.2 grades the kill-criteria
once their `by_date` passes; 3.3 turns the graded history into calibration). Snapshots are immutable
inputs — grading only fills the `outcome`/`status` fields, never rewrites the original call.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockThesis(Base):
    __tablename__ = "stock_theses"
    __table_args__ = (UniqueConstraint("ticker", "as_of", name="uq_thesis_ticker_asof"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)

    # The verdict as it stood (the immutable call).
    archetype: Mapped[str | None] = mapped_column(String(40))
    leaning: Mapped[str | None] = mapped_column(String(20))
    conviction: Mapped[float | None] = mapped_column(Float)
    verdict_summary: Mapped[str | None] = mapped_column(Text)
    fair_value: Mapped[float | None] = mapped_column(Float)      # valuation agent's base fair value
    price_at: Mapped[float | None] = mapped_column(Float)        # price when the thesis was written
    composite: Mapped[float | None] = mapped_column(Float)       # quant screen composite
    signal: Mapped[str | None] = mapped_column(String(20))       # screen signal
    decision_signal: Mapped[str | None] = mapped_column(String(20))  # binding decision

    # The falsifiable, dated predictions from the judge (2.5) — what gets graded.
    kill_criteria: Mapped[list] = mapped_column(JSONB, default=list)

    # Grading (filled by 3.2 once predictions come due). status: 'open' | 'graded'.
    status: Mapped[str] = mapped_column(String(20), default="open")
    graded_at: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
