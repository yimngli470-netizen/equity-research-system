from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class EarningsTranscript(Base):
    __tablename__ = "earnings_transcripts"
    __table_args__ = (
        UniqueConstraint("ticker", "year", "quarter", name="uq_transcript_ticker_yr_q"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    year: Mapped[int] = mapped_column(Integer)
    quarter: Mapped[int] = mapped_column(Integer)
    transcript_date: Mapped[date | None] = mapped_column(Date)
    full_text: Mapped[str] = mapped_column(Text)
    prepared_remarks: Mapped[str | None] = mapped_column(Text)
    qa_section: Mapped[str | None] = mapped_column(Text)
    speakers: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    # Provenance: "fmp" | "ir_pdf" | "ir_html" | "ir_pptx". Drives agent
    # confidence weighting — full FMP transcripts are richest, IR press releases
    # have no Q&A.
    source: Mapped[str] = mapped_column(String(20), server_default="fmp")
    source_url: Mapped[str | None] = mapped_column(Text)
    # False for press releases / slide decks that lack Q&A. Lets the earnings
    # agent skip Q&A-tone features when absent instead of inferring from silence.
    has_qa: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
