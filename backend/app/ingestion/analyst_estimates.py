"""Fetch consensus analyst estimates from FMP."""

import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.fmp_client import get_fmp_client
from app.models.estimate import AnalystEstimate

logger = logging.getLogger(__name__)


async def ingest_analyst_estimates(db: AsyncSession, ticker: str) -> int:
    """Fetch consensus analyst estimates from FMP.

    Returns number of estimate records upserted.
    """
    client = get_fmp_client()
    if not client:
        return 0

    logger.info("Fetching analyst estimates for %s", ticker)
    data = await client.get_analyst_estimates(ticker, period="quarter")

    if not data:
        logger.info("No analyst estimate data for %s", ticker)
        return 0

    rows = []
    for item in data:
        date_str = item.get("date")
        if not date_str:
            continue

        try:
            period_end = datetime.fromisoformat(date_str).date()
        except (ValueError, TypeError):
            continue

        rows.append({
            "ticker": ticker,
            "period_end_date": period_end,
            "eps_consensus": item.get("estimatedEpsAvg"),
            "eps_high": item.get("estimatedEpsHigh"),
            "eps_low": item.get("estimatedEpsLow"),
            "revenue_consensus": item.get("estimatedRevenueAvg"),
            "revenue_high": item.get("estimatedRevenueHigh"),
            "revenue_low": item.get("estimatedRevenueLow"),
            "number_of_analysts": item.get("numberAnalystEstimatedEps"),
        })

    if not rows:
        return 0

    stmt = insert(AnalystEstimate).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_est_ticker_period",
        set_={
            "eps_consensus": stmt.excluded.eps_consensus,
            "eps_high": stmt.excluded.eps_high,
            "eps_low": stmt.excluded.eps_low,
            "revenue_consensus": stmt.excluded.revenue_consensus,
            "revenue_high": stmt.excluded.revenue_high,
            "revenue_low": stmt.excluded.revenue_low,
            "number_of_analysts": stmt.excluded.number_of_analysts,
        },
    )
    await db.execute(stmt)
    await db.commit()

    logger.info("Upserted %d analyst estimate records for %s", len(rows), ticker)
    return len(rows)
