"""Daily data ingestion scheduler.

Runs as a standalone process (the `scheduler` Docker service).
Triggers data collection for all active stocks after market close.
"""

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.ingestion.pipeline import run_full_ingestion

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def daily_job():
    """Scheduled daily ingestion for all active stocks."""
    logger.info("=== Daily ingestion started at %s ===", datetime.now().isoformat())
    try:
        results = await run_full_ingestion()
        logger.info("=== Daily ingestion complete: %s ===", results)
    except Exception:
        logger.exception("Daily ingestion failed")


async def main():
    scheduler = AsyncIOScheduler()
    # Run at 5:30 PM ET (21:30 UTC) every weekday — 1.5 hrs after market close
    scheduler.add_job(daily_job, "cron", day_of_week="mon-fri", hour=21, minute=30)
    scheduler.start()
    logger.info("Scheduler started — next run at 21:30 UTC weekdays")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shutting down")


if __name__ == "__main__":
    asyncio.run(main())
