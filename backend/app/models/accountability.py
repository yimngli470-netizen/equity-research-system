"""Append-only evidence, event forecasts and resolution attempts (accountability-v2).

Legacy journal/forecast outcomes remain on their original rows. These records never
retrofit those outcomes with a probability or an invented source vintage.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def new_id():
    return str(uuid4())


class ResearchEvidence(Base):
    __tablename__ = "research_evidence"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # canonical payload SHA256
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchEvent(Base):
    __tablename__ = "research_events"
    __table_args__ = (UniqueConstraint("ticker", "event_key", name="uq_research_event_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    event_key: Mapped[str] = mapped_column(String(200))
    contract: Mapped[dict] = mapped_column(JSONB)
    contract_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchSubmission(Base):
    __tablename__ = "research_submissions"
    __table_args__ = (UniqueConstraint("event_id", "fingerprint", name="uq_research_submission"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("research_events.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("research_evidence.id"))
    revision_of: Mapped[str | None] = mapped_column(ForeignKey("research_submissions.id"))
    thesis_id: Mapped[int | None] = mapped_column(ForeignKey("stock_theses.id"))
    forecast_id: Mapped[int | None] = mapped_column(ForeignKey("forecasts.id"))
    payload: Mapped[dict] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchResolution(Base):
    __tablename__ = "research_resolutions"
    __table_args__ = (UniqueConstraint("event_id", "packet_sha256", name="uq_research_resolution_packet"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("research_events.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("research_evidence.id"))
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("research_resolutions.id"))
    status: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSONB)
    packet_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchGradeCall(Base):
    __tablename__ = "research_grade_calls"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # exact request key; no reroll
    request: Mapped[dict] = mapped_column(JSONB)
    response: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
