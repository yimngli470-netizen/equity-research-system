"""Per-ticker key metrics — what each company should be evaluated on.

Different companies have different KPIs. Data Center revenue YoY matters for
NVDA; HBM revenue matters for MU; bookings/take-rate matters for UBER. Storing
these per-ticker lets the earnings agent focus on what *actually* matters for
each name instead of producing generic financial summaries.

The agent loads these into its prompt context and reports back a structured
key_metrics array — one row per metric — with value, vs_target, trend, source.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class TickerKeyMetric(Base):
    __tablename__ = "ticker_key_metrics"
    __table_args__ = (
        UniqueConstraint("ticker", "metric_name", name="uq_key_metric_ticker_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    metric_name: Mapped[str] = mapped_column(String(120))
    definition: Mapped[str] = mapped_column(Text)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    # Optional human-readable target/threshold (e.g. ">40% YoY", "above $X B").
    # The agent uses this to decide beat/miss/in_line — null means "report value
    # only, no judgment".
    target_or_threshold: Mapped[str | None] = mapped_column(String(200))
    # Optional warning trip condition (e.g. "below 15%", "any decline",
    # "stalling commentary"). Distinct from target_or_threshold: target is the
    # bull case, warning is the bear-case red line that flips vs_target to
    # "warning" / "close". Null means the metric has no warning concept.
    warning_threshold: Mapped[str | None] = mapped_column(String(300))
    # 1 = most important. The agent orders its output by this.
    priority: Mapped[int] = mapped_column(Integer, server_default="3")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TickerKpiValue(Base):
    """Extracted VALUE of a key metric for a specific quarter (roadmap 0.5).

    Distinct from TickerKeyMetric, which is the *definition* of what to watch. This is the
    period-specific value pulled from the earnings transcript/IR materials, with the verbatim
    evidence quote and source so every reported number is auditable (no more unverifiable
    "Core Data Center +139%" claims). value="not disclosed" is a valid, honest answer.
    """

    __tablename__ = "ticker_kpi_values"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end_date", "metric_name", name="uq_kpi_val_ticker_period_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    period_end_date: Mapped[date] = mapped_column(Date, index=True)
    metric_name: Mapped[str] = mapped_column(String(120))
    value: Mapped[str | None] = mapped_column(String(200))        # "$X B", "+39% QoQ", "not disclosed"
    vs_target: Mapped[str | None] = mapped_column(String(20))     # beat | in_line | close | warning | miss | unknown
    trend: Mapped[str | None] = mapped_column(String(20))         # up | down | flat | unknown
    evidence_quote: Mapped[str | None] = mapped_column(Text)      # verbatim source line (auditability)
    source: Mapped[str | None] = mapped_column(String(20))        # transcript | ir | financials | unknown
    source_url: Mapped[str | None] = mapped_column(String(300))
    as_of: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
