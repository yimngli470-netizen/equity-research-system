"""Forecast model (roadmap 4.2) — the analyst's OWN numbers, point-in-time immutable.

Each row is one dated forecast: the LLM's basis-cited assumption paths (bull/base/bear) plus the
deterministically compiled quarterly projections and the vs-street deltas. Like `stock_theses`,
rows are snapshots — grading only fills `outcome`/`status`, never rewrites the original call. This
is the label stream ("our EPS vs actual vs street") that feeds calibration (M4b) and the panel.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (UniqueConstraint("ticker", "as_of", name="uq_forecast_ticker_asof"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    archetype: Mapped[str | None] = mapped_column(String(40))
    horizon_quarters: Mapped[int] = mapped_column(Integer, default=8)

    # The LLM's assumptions (scenario paths + per-assumption basis + rationale) — judgment, cited.
    assumptions: Mapped[dict] = mapped_column(JSONB)
    # The compiled quarterly lines per scenario — pure arithmetic from the assumptions.
    projections: Mapped[dict] = mapped_column(JSONB)

    # Headline numbers (base scenario), denormalized for cheap querying/feature extraction.
    base_next_q_eps: Mapped[float | None] = mapped_column(Float)
    base_ntm_eps: Mapped[float | None] = mapped_column(Float)        # next-12-months (4q sum)
    base_ntm_revenue: Mapped[float | None] = mapped_column(Float)
    street_next_q_eps: Mapped[float | None] = mapped_column(Float)   # consensus at forecast time
    eps_vs_street_next_q: Mapped[float | None] = mapped_column(Float)  # (ours-street)/|street|, fraction

    # Smart-cache fingerprint of the inputs (financials/transcript/estimates + prompt hash).
    input_fingerprint: Mapped[dict | None] = mapped_column(JSONB)

    # Grading (filled as forecasted quarters resolve). status: 'open' | 'graded'.
    status: Mapped[str] = mapped_column(String(20), default="open")
    graded_at: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
