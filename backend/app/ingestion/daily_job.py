"""Daily DATA refresh — the one scheduled thing in an otherwise pull-model system.

Why this doesn't violate the no-scheduler rule (CLAUDE.md, decision 2026-06-11): that rule exists
to prevent **unattended LLM spend**, and ANALYST_ROADMAP.md:649 already carves out the exception —
"the daily data job costs $0 in LLM; the pull model stays for all LLM analysis." This job calls
`ingest_ticker(..., data_only=True)`, which skips every LLM-touching step (bootstrap, archetype,
transcripts, KPI extraction). It runs no agents, no scoring, no decision.

What it buys: post-earnings detection. `earnings_watch.py` compares the newest reported quarter
against the quarter the earnings agent actually analyzed — but only if the newest quarter has been
ingested. Without a daily refresh, nothing notices a company reported until you click something,
which is precisely the notification the badge is supposed to give you.

The result is a notification, never an action: the watchlist shows "reported — analysis is behind"
and you decide whether to spend the Opus call.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# Sequential with a small gap: this is a background job with no deadline, and yfinance/EDGAR both
# rate-limit. Being slow and polite is strictly better than being fast and throttled.
_PAUSE_BETWEEN_TICKERS = 2.0

_last_run: dict | None = None


def get_last_run() -> dict | None:
    """Status of the most recent daily refresh, for the UI to show when data was last touched."""
    return _last_run


async def run_daily_data_refresh() -> dict:
    """Refresh market/filing data for every active ticker. ZERO LLM calls by construction."""
    global _last_run
    started = datetime.now(timezone.utc)

    async with async_session() as db:
        tickers = [
            t for (t,) in (
                await db.execute(select(Stock.ticker).where(Stock.active.is_(True)))
            ).all()
        ]

    logger.info("[daily] data-only refresh starting for %d ticker(s) — no LLM calls", len(tickers))

    from app.ingestion.pipeline import ingest_ticker

    ok, failed = 0, []
    for ticker in tickers:
        try:
            result = await ingest_ticker(ticker, data_only=True)
            if result.errors:
                logger.warning("[daily] %s finished with errors: %s", ticker, "; ".join(result.errors))
            ok += 1
        except Exception:
            # One bad ticker must never stop the sweep.
            logger.exception("[daily] refresh failed for %s", ticker)
            failed.append(ticker)
        await asyncio.sleep(_PAUSE_BETWEEN_TICKERS)

    # Report what newly went stale, so the reason for a badge appearing is in the logs.
    try:
        from app.earnings_watch import earnings_alerts
        async with async_session() as db:
            alerts = [a for a in await earnings_alerts(db) if a["stale"]]
        if alerts:
            logger.info(
                "[daily] %d name(s) now need an earnings refresh: %s",
                len(alerts), ", ".join(f"{a['ticker']} ({a['reason']})" for a in alerts),
            )
    except Exception:
        logger.exception("[daily] earnings-alert summary failed")
        alerts = []

    finished = datetime.now(timezone.utc)
    _last_run = {
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "tickers": len(tickers),
        "ok": ok,
        "failed": failed,
        "stale_after": [a["ticker"] for a in alerts],
    }
    logger.info(
        "[daily] data-only refresh done in %.0fs — %d ok, %d failed",
        (finished - started).total_seconds(), ok, len(failed),
    )
    return _last_run


_scheduler = None


def start_scheduler() -> None:
    """Start the daily data job if enabled. Called from the FastAPI lifespan."""
    global _scheduler
    if not settings.daily_data_job:
        logger.info("[daily] data job disabled (DAILY_DATA_JOB=false) — nothing scheduled")
        return
    if _scheduler is not None:
        return

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = AsyncIOScheduler(timezone=settings.daily_data_job_timezone)
    _scheduler.add_job(
        run_daily_data_refresh,
        CronTrigger(hour=settings.daily_data_job_hour, minute=0),
        id="daily_data_refresh",
        # If the container was down at the trigger time, run once on the next opportunity rather
        # than firing a backlog of missed runs.
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info(
        "[daily] data-only refresh scheduled for %02d:00 %s (no LLM calls; analysis stays pull-model)",
        settings.daily_data_job_hour, settings.daily_data_job_timezone,
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
