"""Fetch earnings surprise history from FMP and populate EarningsEvent."""

import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.fmp_client import get_fmp_client
from app.models.earnings import EarningsEvent

logger = logging.getLogger(__name__)


async def ingest_earnings_surprises(db: AsyncSession, ticker: str) -> int:
    """Fetch earnings surprise history from FMP.

    Maps to the existing EarningsEvent model with the new surprise_pct columns.
    Returns number of records upserted.
    """
    client = get_fmp_client()
    if not client:
        return 0

    logger.info("Fetching earnings surprises for %s", ticker)
    data = await client.get_earnings_surprises(ticker)

    if not data:
        logger.info("No earnings surprise data for %s", ticker)
        return 0

    rows = []
    for item in data:
        date_str = item.get("date")
        if not date_str:
            continue

        try:
            report_date = datetime.fromisoformat(date_str).date()
        except (ValueError, TypeError):
            continue

        actual_eps = item.get("actualEarningResult")
        estimated_eps = item.get("estimatedEarning")

        eps_surprise_pct = None
        if actual_eps is not None and estimated_eps and estimated_eps != 0:
            eps_surprise_pct = (actual_eps - estimated_eps) / abs(estimated_eps)

        rows.append({
            "ticker": ticker,
            "report_date": report_date,
            "eps_estimate": estimated_eps,
            "eps_actual": actual_eps,
            "eps_surprise_pct": eps_surprise_pct,
        })

    if not rows:
        return 0

    stmt = insert(EarningsEvent).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_earn_ticker_date",
        set_={
            "eps_estimate": stmt.excluded.eps_estimate,
            "eps_actual": stmt.excluded.eps_actual,
            "eps_surprise_pct": stmt.excluded.eps_surprise_pct,
        },
    )
    await db.execute(stmt)
    await db.commit()

    logger.info("Upserted %d earnings surprise records for %s", len(rows), ticker)
    return len(rows)
