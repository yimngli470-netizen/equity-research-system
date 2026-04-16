"""Daily pipeline scheduler.

Runs as a standalone process (the `scheduler` Docker service).
After market close, runs the full pipeline for all active stocks:
  1. Data ingestion (prices, financials, valuation, news)
  2. AI research agents (news, earnings, industry, valuation)
  3. Quant scoring (feature extraction + composite score)
  4. Decision engine (risk flags + final signal)
"""

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.ingestion.pipeline import run_full_ingestion

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_scoring_for_ticker(ticker: str) -> dict:
    """Run scoring + decision for a single ticker."""
    from app.database import async_session
    from app.decision.engine import run_decision
    from app.scoring.calculator import calculate_score

    async with async_session() as db:
        score_result = await calculate_score(db, ticker)

    async with async_session() as db:
        decision_result = await run_decision(db, ticker)

    return {
        "ticker": ticker,
        "composite": score_result.composite_score,
        "signal": score_result.signal,
        "final_signal": decision_result.final_signal,
        "confidence": decision_result.confidence,
        "flags": len(decision_result.risk_flags),
    }


async def daily_job():
    """Full daily pipeline: ingestion → agents → scoring → decision."""
    from sqlalchemy import select

    from app.agents.orchestrator import run_all_agents
    from app.database import async_session
    from app.models.stock import Stock

    start = datetime.now()
    logger.info("=== Daily pipeline started at %s ===", start.isoformat())

    # Step 1: Data ingestion
    logger.info("--- Step 1/4: Data ingestion ---")
    try:
        ingestion_results = await run_full_ingestion()
        for r in ingestion_results:
            logger.info(
                "  [ingest] %s: prices=%d, financials=%d, news=%d, errors=%d",
                r.ticker, r.prices, r.financials, r.news, len(r.errors),
            )
    except Exception:
        logger.exception("Data ingestion failed — aborting pipeline")
        return

    # Get active tickers
    async with async_session() as db:
        result = await db.execute(
            select(Stock.ticker).where(Stock.active.is_(True))
        )
        tickers = [row[0] for row in result.all()]

    # Step 2: AI research agents
    logger.info("--- Step 2/4: AI research agents ---")
    for ticker in tickers:
        try:
            agent_result = await run_all_agents(ticker)
            statuses = [
                f"{r.agent_type}={'cached' if r.cached else 'ok' if r.success else 'FAILED'}"
                for r in agent_result.results
            ]
            logger.info("  [agents] %s: %s", ticker, ", ".join(statuses))
        except Exception:
            logger.exception("  [agents] %s: FAILED", ticker)

    # Step 3 & 4: Scoring + Decision
    logger.info("--- Step 3/4: Scoring + Decision ---")
    for ticker in tickers:
        try:
            result = await run_scoring_for_ticker(ticker)
            logger.info(
                "  [score] %s: composite=%.3f raw=%s final=%s confidence=%s flags=%d",
                result["ticker"],
                result["composite"],
                result["signal"],
                result["final_signal"],
                result["confidence"],
                result["flags"],
            )
        except Exception:
            logger.exception("  [score] %s: FAILED", ticker)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info("=== Daily pipeline complete in %.1fs for %d tickers ===", elapsed, len(tickers))


async def main():
    scheduler = AsyncIOScheduler()
    # Run at 5:30 PM ET (21:30 UTC) every weekday — 1.5 hrs after market close
    scheduler.add_job(daily_job, "cron", day_of_week="mon-fri", hour=21, minute=30)
    scheduler.start()
    logger.info("Scheduler started — daily pipeline at 21:30 UTC weekdays")
    logger.info("Pipeline: ingestion → agents → scoring → decision")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shutting down")


if __name__ == "__main__":
    asyncio.run(main())
