from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, Text, UniqueConstraint
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
