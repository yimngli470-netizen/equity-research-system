from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Stock(Base):
    __tablename__ = "stocks"

    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(200))
    added_date: Mapped[date] = mapped_column(Date, default=date.today)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Coverage tier (roadmap 6.1) — the two-tier universe. "watchlist" names get the full pull-model
    # pipeline (agents, forecast, PT, journal) and show on Coverage. "universe" names are batch
    # tier-1: EDGAR + prices + rule-based archetype + the hard-feature screen only, ~zero LLM. A
    # universe name is *promoted* to watchlist on demand (sets active=True + runs the full pipeline).
    coverage_tier: Mapped[str] = mapped_column(String(20), default="watchlist", server_default="watchlist")

    # Business-model archetype (roadmap 1.1) — a grounded label that conditions peer-relative
    # normalization (1.3) and archetype weight profiles (1.4). Grounded on `archetype_features`
    # (the measured quant profile) so the label is auditable, not a guess. Re-runnable.
    archetype: Mapped[str | None] = mapped_column(String(40))
    # How the label was assigned: "llm" (grounded-LLM, watchlist) or "rules" (deterministic tier-1,
    # 6.1b). Promotion upgrades a "rules" label to "llm". Lets the screen flag provisional labels.
    archetype_source: Mapped[str | None] = mapped_column(String(10))
    archetype_features: Mapped[dict | None] = mapped_column(JSONB)   # the QuantProfile it was grounded on
    archetype_rationale: Mapped[str | None] = mapped_column(String(1000))
    archetype_as_of: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
