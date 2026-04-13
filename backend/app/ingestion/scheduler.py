"""Daily data ingestion scheduler.

Runs as a standalone process (the `scheduler` Docker service).
Triggers data collection for all active stocks after market close.
"""

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_daily_ingestion():
    """Main ingestion pipeline — runs once per day."""
    logger.info("Starting daily ingestion at %s", datetime.now().isoformat())
    # TODO: Phase 1 — implement ingestion steps:
    # 1. fetch_prices(tickers)
    # 2. fetch_fundamentals(tickers)
    # 3. fetch_news(tickers)
    # 4. fetch_earnings_events(tickers)
    # 5. fetch_transcripts(tickers)
    # 6. fetch_insider_trades(tickers)
    logger.info("Daily ingestion complete")


async def main():
    scheduler = AsyncIOScheduler()
    # Run at 5:30 PM ET (21:30 UTC) every weekday — 1.5 hrs after market close
    scheduler.add_job(run_daily_ingestion, "cron", day_of_week="mon-fri", hour=21, minute=30)
    scheduler.start()
    logger.info("Scheduler started — waiting for next run")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shutting down")


if __name__ == "__main__":
    asyncio.run(main())
