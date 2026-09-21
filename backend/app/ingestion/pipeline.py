"""Orchestrates the full ingestion pipeline for all active stocks."""

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.ingestion.edgar import ingest_financials_edgar
from app.ingestion.estimates_yf import ingest_estimates_yf
from app.ingestion.fundamentals import ingest_financials, ingest_valuation
from app.ingestion.news import ingest_news
from app.ingestion.prices import ingest_benchmark_prices, ingest_prices
from app.models.stock import Stock

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    ticker: str
    prices: int = 0
    financials: int = 0
    valuation: bool = False
    archetype: str | None = None
    news: int = 0
    transcripts: int = 0
    earnings_surprises: int = 0
    analyst_estimates: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # non-fatal, user-facing (e.g. IR auto-discovery)


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


async def ingest_ticker(ticker: str, *, data_only: bool = False) -> IngestionResult:
    """Run all ingestion steps for a single ticker.

    data_only=True skips every step that makes an LLM call — bootstrap (KPI/kill-signal
    generation), archetype classification, transcript fetch (the summarizer runs inline), and KPI
    value extraction. What remains is pure API/scrape work: prices, EDGAR financials, valuation,
    consensus, news, segments, surprises. This is what the unattended daily job runs, so that job
    can be stated flatly to cost ZERO LLM tokens — see ingestion/daily_job.py.
    """
    result = IngestionResult(ticker=ticker)

    # Auto-populate sector/industry from yfinance
    await _update_stock_info(ticker)

    async with async_session() as db:
        # Auto-bootstrap a new ticker (idempotent; no cost once configured): generate its
        # KPI definitions + auto-discover its IR source. Surfaces warnings to the UI when IR
        # discovery can't be confirmed; full detail recorded in ticker_onboarding.
        if not data_only:
            try:
                from app.ingestion.bootstrap import bootstrap_ticker
                boot = await bootstrap_ticker(db, ticker)
                result.warnings.extend(boot.warnings)
            except Exception as e:
                logger.exception("Bootstrap failed for %s", ticker)
                result.warnings.append(f"bootstrap: {e}")

        # Prices
        try:
            result.prices = await ingest_prices(db, ticker)
        except Exception as e:
            logger.exception("Price ingestion failed for %s", ticker)
            result.errors.append(f"prices: {e}")

        # Benchmark prices (roadmap 4.1): keep SPY history fresh so grading can score every thesis
        # BENCHMARK-RELATIVE ("beat the index", not "went up"). At most once per day; best-effort.
        try:
            await ingest_benchmark_prices(db)
        except Exception as e:
            logger.warning("Benchmark (SPY) ingestion failed: %s", e)

        # Quarterly financials — EDGAR (authoritative filed XBRL, full history) is the
        # source of truth; yfinance is the fallback if EDGAR is unavailable (no CIK,
        # network, etc.). Both free. See ANALYST_ROADMAP.md 0.1-0.3.
        try:
            result.financials = await ingest_financials_edgar(db, ticker)
        except Exception as e:
            logger.warning("EDGAR financials failed for %s (%s); falling back to yfinance", ticker, e)
            try:
                result.financials = await ingest_financials(db, ticker)
            except Exception as e2:
                logger.exception("Financials ingestion failed for %s", ticker)
                result.errors.append(f"financials: {e2}")

        # Business-model archetype (roadmap 1.1) — grounded-LLM label computed from the EDGAR
        # financials just ingested. Idempotent: the LLM call only fires once per ticker (or on
        # force). Conditions peer-relative normalization (1.3) + archetype weights (1.4).
        if not data_only:
            try:
                from app.ingestion.archetype import classify_archetype
                arch = await classify_archetype(db, ticker)
                result.archetype = arch.archetype
                if arch.status == "insufficient_data":
                    result.warnings.append(f"{ticker}: too little financial history to classify archetype.")
            except Exception as e:
                logger.exception("Archetype classification failed for %s", ticker)
                result.errors.append(f"archetype: {e}")

        # Valuation snapshot
        try:
            result.valuation = await ingest_valuation(db, ticker)
        except Exception as e:
            logger.exception("Valuation ingestion failed for %s", ticker)
            result.errors.append(f"valuation: {e}")

        # Analyst consensus — yfinance (free), replaces the FMP path. Treated as a
        # low-weight, staleness-aware divergence check (roadmap 0.4).
        try:
            result.analyst_estimates = await ingest_estimates_yf(db, ticker)
        except Exception as e:
            logger.exception("Estimate ingestion failed for %s", ticker)
            result.errors.append(f"estimates: {e}")

        # News
        try:
            result.news = await ingest_news(db, ticker)
        except Exception as e:
            logger.exception("News ingestion failed for %s", ticker)
            result.errors.append(f"news: {e}")

        # Transcripts run unconditionally — orchestrator falls back to IR scraper
        # when FMP is unavailable or doesn't cover the ticker.
        if not data_only:
            from app.ingestion.transcripts import ingest_transcripts
            try:
                result.transcripts = await ingest_transcripts(db, ticker)
            except Exception as e:
                logger.exception("Transcript ingestion failed for %s", ticker)
                result.errors.append(f"transcripts: {e}")

        # Per-ticker KPI value extraction (roadmap 0.5) — pull defined-KPI values from the
        # transcript with evidence + provenance. Idempotent per (ticker, period): the LLM
        # call only fires once per new quarter.
        if not data_only:
            try:
                from app.ingestion.kpi_extractor import extract_kpis
                await extract_kpis(db, ticker)
            except Exception as e:
                logger.exception("KPI extraction failed for %s", ticker)
                result.errors.append(f"kpi_extraction: {e}")

        # Kill-signal evaluation — did any pre-registered sell condition actually happen this
        # quarter? One Sonnet call, idempotent per (ticker, period), runs after KPI extraction so
        # it can use the extracted values as evidence. A `tripped` verdict flips the signal
        # automatically; see kill_signals/evaluator.py for why it never un-trips.
        if not data_only:
            try:
                from app.kill_signals import evaluate_kill_signals
                await evaluate_kill_signals(db, ticker)
            except Exception as e:
                logger.exception("Kill-signal evaluation failed for %s", ticker)
                result.warnings.append(f"kill_signals: {e}")

        # Segment persistence (roadmap 4.1) — deterministic parse of the transcript summary's
        # segment breakouts into the `segments` table (no LLM; the summarizer extracted once).
        try:
            from app.ingestion.segments import persist_segments
            await persist_segments(db, ticker)
        except Exception as e:
            logger.exception("Segment persistence failed for %s", ticker)
            result.warnings.append(f"segments: {e}")

        # Other FMP-only data (gated behind API key). Analyst estimates now come from
        # yfinance above; FMP is retained only for earnings surprises (its unique value-add).
        if settings.fmp_api_key:
            from app.ingestion.fmp_client import FMPAccessError
            from app.ingestion.earnings_surprises import ingest_earnings_surprises

            try:
                result.earnings_surprises = await ingest_earnings_surprises(db, ticker)
            except FMPAccessError as e:
                logger.warning("Earnings surprise ingestion unavailable for %s: %s", ticker, e)
                result.errors.append(f"earnings_surprises: {e}")
            except Exception as e:
                logger.exception("Earnings surprise ingestion failed for %s", ticker)
                result.errors.append(f"earnings_surprises: {e}")

    return result


async def run_full_ingestion(
    tickers: list[str] | None = None,
    *,
    recompute_peers: bool | None = None,
) -> list[IngestionResult]:
    """Run the full ingestion pipeline.

    Args:
        tickers: Specific tickers to ingest. If None, ingests all active stocks.
        recompute_peers: Whether to recompute the cross-sectional peer-weight grid afterwards.
            None (default) = auto: only on a full-universe run. See the recompute block below.

    Returns:
        List of IngestionResult for each ticker.
    """
    full_run = tickers is None
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
            "%s: prices=%d, financials=%d, valuation=%s, archetype=%s, news=%d, transcripts=%d, surprises=%d, estimates=%d, errors=%d",
            r.ticker, r.prices, r.financials, r.valuation, r.archetype, r.news,
            r.transcripts, r.earnings_surprises, r.analyst_estimates, len(r.errors),
        )

    # Peer-closeness weights (roadmap 1.2) are CROSS-SECTIONAL — they depend on the whole
    # universe, so recompute once after every ticker is ingested, not per-ticker.
    #
    # But ONLY on a full-universe run. The grid is O(n²) (~357k rows / minutes of CPU at 598
    # names), and refreshing one ticker barely moves it — so the per-stock "Run Full Pipeline"
    # button used to pay the whole cost for a 6s ingest, wedging the UI for ~3 minutes.
    # Pass recompute_peers=True to force it (e.g. from a scheduled/maintenance job).
    should_recompute = full_run if recompute_peers is None else recompute_peers
    if should_recompute:
        try:
            from app.measurement.peers import recompute_peer_weights
            async with async_session() as db:
                await recompute_peer_weights(db)
        except Exception:
            logger.exception("Peer-weight recompute failed")
    else:
        logger.info(
            "[peers] skipped recompute for partial ingest (%d ticker(s)) — cross-sectional "
            "weights refresh on a full run or with recompute_peers=True", len(tickers),
        )

    return results
