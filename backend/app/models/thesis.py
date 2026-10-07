"""Thesis journal (roadmap 3.1) — an immutable per-run snapshot of the analyst's verdict.

Each changed pipeline result appends one thesis revision per ticker: the judge's leaning +
conviction + DATED kill-criteria, the valuation fair value, and the price/composite/decision at the
time. This is the record the accountability loop grades against later (3.2 grades the kill-criteria
once their `by_date` passes; 3.3 turns the graded history into calibration). Snapshots are immutable
inputs — grading only fills the `outcome`/`status` fields, never rewrites the original call.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, String, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockThesis(Base):
    __tablename__ = "stock_theses"

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

    # Immutable revisions. Legacy rows retain their IDs, original outcomes and null hashes.
    writer_version: Mapped[str] = mapped_column(String(30), default="legacy-v1", server_default="legacy-v1")
    revision_of: Mapped[int | None] = mapped_column(ForeignKey("stock_theses.id"))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("research_evidence.id"))

    # Grading (filled by 3.2 once predictions come due). status: 'open' | 'graded'.
    status: Mapped[str] = mapped_column(String(20), default="open")
    graded_at: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
