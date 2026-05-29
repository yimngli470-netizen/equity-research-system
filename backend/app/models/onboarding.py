"""DEVELOPER-ONLY debug table — auto-bootstrap status for new stocks. NOT a product table.

When a new ticker is added, the app auto-generates its KPI definitions (LLM) and tries to
auto-discover its IR source. This records how that went so the DEVELOPER can see which tickers
need manual attention and why (bad URL vs IP block), and decide to fix the URL or run the
scraper from a residential IP. The same info is logged at WARNING level (`docker compose logs`);
this table is just the durable copy (Docker logs are lost on `docker compose down`). One
upsert row per ticker — it does not grow over time. Safe to drop if a real log sink is added.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class DevTickerBootstrapStatus(Base):
    # Prefixed "dev_" to make clear this is a developer/debug table, not a product table.
    __tablename__ = "dev_ticker_bootstrap_status"
    __table_args__ = (UniqueConstraint("ticker", name="uq_dev_bootstrap_ticker"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)

    # ok | skipped (already configured) | failed
    kpi_status: Mapped[str | None] = mapped_column(String(20))
    kpi_count: Mapped[int | None] = mapped_column(Integer)

    # ok | skipped | unreachable (timeout/403 — likely IP block, URL may be fine)
    #             | not_found (404/DNS — URL likely wrong) | failed (LLM/other)
    ir_status: Mapped[str | None] = mapped_column(String(20))
    ir_url: Mapped[str | None] = mapped_column(String(300))
    ir_artifact_type: Mapped[str | None] = mapped_column(String(30))

    # Human-readable, ACTIONABLE detail for the developer (what to check / do).
    message: Mapped[str | None] = mapped_column(Text)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
