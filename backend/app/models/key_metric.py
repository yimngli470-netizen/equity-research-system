"""Per-ticker key metrics — what each company should be evaluated on.

Different companies have different KPIs. Data Center revenue YoY matters for
NVDA; HBM revenue matters for MU; bookings/take-rate matters for UBER. Storing
these per-ticker lets the earnings agent focus on what *actually* matters for
each name instead of producing generic financial summaries.

The agent loads these into its prompt context and reports back a structured
key_metrics array — one row per metric — with value, vs_target, trend, source.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint
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
    # 1 = most important. The agent orders its output by this.
    priority: Mapped[int] = mapped_column(Integer, server_default="3")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
