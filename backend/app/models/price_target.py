"""Price target (roadmap 4.3) — the dated, auditable output of the deterministic valuation model.

Every component that produced the number rides along (probabilities + their source, WACC inputs,
method blend, per-scenario DCF/multiple values, sensitivity grid), so any PT can be re-derived by
hand. Point-in-time immutable, like forecasts and theses."""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PriceTarget(Base):
    __tablename__ = "price_targets"
    __table_args__ = (UniqueConstraint("ticker", "as_of", name="uq_pt_ticker_asof"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    archetype: Mapped[str | None] = mapped_column(String(40))
    horizon_months: Mapped[int] = mapped_column(Integer, default=12)

    fair_value: Mapped[float | None] = mapped_column(Float)      # probability-weighted, today
    price_target: Mapped[float | None] = mapped_column(Float)   # fair value grown at CoE to horizon
    price_at: Mapped[float | None] = mapped_column(Float)       # price when set
    upside: Mapped[float | None] = mapped_column(Float)         # PT / price − 1
    street_target_mean: Mapped[float | None] = mapped_column(Float)

    probabilities: Mapped[dict] = mapped_column(JSONB)          # P(bull/base/bear) + source
    scenarios: Mapped[dict] = mapped_column(JSONB)              # per-scenario DCF + multiple + blend
    method: Mapped[dict] = mapped_column(JSONB)                 # w_dcf, multiple basis, terminal g…
    wacc: Mapped[dict] = mapped_column(JSONB)                   # rf/beta/ERP/CoE + sources
    sensitivity: Mapped[dict] = mapped_column(JSONB)            # WACC × terminal-g grid

    forecast_as_of: Mapped[date | None] = mapped_column(Date)   # which forecast it consumed

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
