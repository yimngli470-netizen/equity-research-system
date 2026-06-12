"""Research note (roadmap 5.1) — the professional deliverable, assembled and archived.

One note per ticker per run-day: a Markdown document compiled DETERMINISTICALLY from artifacts the
pipeline already produced (decision, price target, forecast, dialectic, flags, journal — no new
analysis LLM calls), plus a structured payload and a field-level diff vs the prior note ("what
changed" is half the value of coverage). Immutable snapshots, like theses/forecasts/targets."""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ResearchNote(Base):
    __tablename__ = "research_notes"
    __table_args__ = (UniqueConstraint("ticker", "as_of", name="uq_note_ticker_asof"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)

    note_md: Mapped[str] = mapped_column(Text)            # the rendered note
    payload: Mapped[dict] = mapped_column(JSONB)          # structured fields (drives the diff)
    changes: Mapped[list | None] = mapped_column(JSONB)   # human-readable deltas vs prior note

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
