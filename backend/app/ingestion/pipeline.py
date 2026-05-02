"""Orchestrates the full ingestion pipeline for all active stocks."""

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.ingestion.fundamentals import ingest_financials, ingest_valuation
from app.ingestion.news import ingest_news
from app.ingestion.prices import ingest_prices
from app.models.stock import Stock

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    ticker: str
    prices: int = 0
    financials: int = 0
    valuation: bool = False
    news: int = 0
    transcripts: int = 0
    earnings_surprises: int = 0
    analyst_estimates: int = 0
    errors: list[str] = field(default_factory=list)


async def _update_stock_info(ticker: str) -> None:
    """Populate sector, industry, and name from yfinance if missing."""
    import yfinance as yf

    async with async_session() as db:
        stock = await db.get(Stock, ticker)
        if not stock:
            return

        # Skip if already populated
        if stock.sector and stock.industry:
            return

        try:
            info = await asyncio.to_thread(lambda: yf.Ticker(ticker).info)
            if info:
                if not stock.sector:
                    stock.sector = info.get("sector")
                if not stock.industry:
                    stock.industry = info.get("industry")
                # Also update name if it's just the ticker
                if stock.name == ticker or not stock.name:
                    stock.name = info.get("longName") or info.get("shortName") or stock.name
                await db.commit()
                logger.info("Updated stock info for %s: sector=%s, industry=%s", ticker, stock.sector, stock.industry)
        except Exception:
            logger.exception("Failed to update stock info for %s", ticker)


async def ingest_ticker(ticker: str) -> IngestionResult:
    """Run all ingestion steps for a single ticker."""
    result = IngestionResult(ticker=ticker)

    # Auto-populate sector/industry from yfinance
    await _update_stock_info(ticker)

    async with async_session() as db:
        # Prices
        try:
            result.prices = await ingest_prices(db, ticker)
        except Exception as e:
            logger.exception("Price ingestion failed for %s", ticker)
            result.errors.append(f"prices: {e}")

        # Quarterly financials — yfinance for the daily path (free, no FMP budget).
        # FMP financials are available on demand via /api/ingestion/backfill (saves the
        # 250-call/day budget for transcripts, which are FMP's unique value-add).
        try:
            result.financials = await ingest_financials(db, ticker)
        except Exception as e:
            logger.exception("Financials ingestion failed for %s", ticker)
            result.errors.append(f"financials: {e}")

        # Valuation snapshot
        try:
            result.valuation = await ingest_valuation(db, ticker)
        except Exception as e:
            logger.exception("Valuation ingestion failed for %s", ticker)
            result.errors.append(f"valuation: {e}")

        # News
        try:
            result.news = await ingest_news(db, ticker)
        except Exception as e:
            logger.exception("News ingestion failed for %s", ticker)
            result.errors.append(f"news: {e}")

        # FMP data (gated behind API key)
        if settings.fmp_api_key:
            from app.ingestion.analyst_estimates import ingest_analyst_estimates
            from app.ingestion.earnings_surprises import ingest_earnings_surprises
            from app.ingestion.transcripts import ingest_transcripts

            try:
                result.transcripts = await ingest_transcripts(db, ticker)
            except Exception as e:
                logger.exception("Transcript ingestion failed for %s", ticker)
                result.errors.append(f"transcripts: {e}")

            try:
                result.earnings_surprises = await ingest_earnings_surprises(db, ticker)
            except Exception as e:
                logger.exception("Earnings surprise ingestion failed for %s", ticker)
                result.errors.append(f"earnings_surprises: {e}")

            try:
                result.analyst_estimates = await ingest_analyst_estimates(db, ticker)
            except Exception as e:
                logger.exception("Analyst estimates ingestion failed for %s", ticker)
                result.errors.append(f"analyst_estimates: {e}")

    return result


async def run_full_ingestion(tickers: list[str] | None = None) -> list[IngestionResult]:
    """Run the full ingestion pipeline.

    Args:
        tickers: Specific tickers to ingest. If None, ingests all active stocks.

    Returns:
        List of IngestionResult for each ticker.
    """
    if tickers is None:
        async with async_session() as db:
            result = await db.execute(
                select(Stock.ticker).where(Stock.active.is_(True))
            )
            tickers = [row[0] for row in result.all()]

    if not tickers:
        logger.warning("No active tickers to ingest")
        return []

    logger.info("Starting ingestion for %d tickers: %s", len(tickers), tickers)

    results = []
    for ticker in tickers:
        r = await ingest_ticker(ticker)
        results.append(r)
        logger.info(
            "%s: prices=%d, financials=%d, valuation=%s, news=%d, transcripts=%d, surprises=%d, estimates=%d, errors=%d",
            r.ticker, r.prices, r.financials, r.valuation, r.news,
            r.transcripts, r.earnings_surprises, r.analyst_estimates, len(r.errors),
        )

    return results
