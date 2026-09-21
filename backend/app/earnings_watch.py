"""Post-earnings staleness detection — "this company reported; your analysis predates it."

Deliberately NOT an auto-runner. The system is pull-model for LLM work (CLAUDE.md: no scheduler,
decision 2026-06-11), so this module only ever *reports*; the user clicks Run Full Pipeline. The
one automated piece is `ingestion/daily_job.py`, which refreshes DATA (zero LLM calls) so this
detection has something current to compare against.

How staleness is decided — no heuristics, no date arithmetic:
every agent report is saved with the `input_fingerprint` it was built from (agents/base.py), and
the earnings agent's fingerprint contains `financials` = the latest reported period_end_date at
the time it ran. If the newest period in the DB is later than the one baked into the report, the
agent has not seen this quarter. That is exactly the condition smart mode would re-run on, so the
badge can never disagree with what clicking the button actually does.
"""

import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisReport
from app.models.financial import Financial
from app.models.stock import Stock
from app.models.transcript import EarningsTranscript

logger = logging.getLogger(__name__)


def _iso(d) -> str | None:
    return d.isoformat() if isinstance(d, date) else None


async def earnings_alerts(db: AsyncSession, tickers: list[str] | None = None) -> list[dict]:
    """One row per active ticker: has it reported since the earnings agent last ran?

    Bulk (three grouped queries, no per-ticker loop) because the dashboard calls this for the
    whole watchlist on every load.
    """
    if tickers is None:
        tickers = [
            t for (t,) in (
                await db.execute(select(Stock.ticker).where(Stock.active.is_(True)))
            ).all()
        ]
    else:
        tickers = [t.upper() for t in tickers]
    if not tickers:
        return []

    latest_period: dict[str, date] = dict(
        (
            await db.execute(
                select(Financial.ticker, func.max(Financial.period_end_date))
                .where(Financial.ticker.in_(tickers))
                .group_by(Financial.ticker)
            )
        ).all()
    )

    # Newest earnings report per ticker, with the fingerprint it was built from.
    reports = (
        await db.execute(
            select(AnalysisReport.ticker, AnalysisReport.run_date, AnalysisReport.input_fingerprint)
            .where(AnalysisReport.ticker.in_(tickers))
            .where(AnalysisReport.agent_type == "earnings")
            .order_by(AnalysisReport.ticker, AnalysisReport.run_date.desc(), AnalysisReport.id.desc())
        )
    ).all()
    latest_report: dict[str, tuple[date, dict | None]] = {}
    for tk, run_date, fp in reports:
        latest_report.setdefault(tk, (run_date, fp))

    transcripts = (
        await db.execute(
            select(EarningsTranscript.ticker, EarningsTranscript.year, EarningsTranscript.quarter)
            .where(EarningsTranscript.ticker.in_(tickers))
            .order_by(
                EarningsTranscript.ticker,
                EarningsTranscript.year.desc(),
                EarningsTranscript.quarter.desc(),
            )
        )
    ).all()
    latest_transcript: dict[str, str] = {}
    for tk, y, q in transcripts:
        latest_transcript.setdefault(tk, f"{y}-Q{q}")

    out: list[dict] = []
    for ticker in sorted(tickers):
        period = latest_period.get(ticker)
        run = latest_report.get(ticker)
        run_date, fp = run if run else (None, None)

        analyzed_raw = (fp or {}).get("financials") if isinstance(fp, dict) else None
        analyzed: date | None = None
        if isinstance(analyzed_raw, str):
            try:
                analyzed = date.fromisoformat(analyzed_raw)
            except ValueError:
                analyzed = None

        stale, reason = False, None
        if period is None:
            reason = "no financials ingested yet"
        elif run_date is None:
            stale = True
            reason = "earnings agent has never run on this name"
        elif analyzed is None:
            # Report predates fingerprinting, or was written by an older schema — can't prove it
            # covers the current quarter, so don't claim it's stale either.
            reason = f"last run {run_date} (no fingerprint to compare)"
        elif period > analyzed:
            stale = True
            reason = f"reported {period}; analysis covers {analyzed}"
        else:
            reason = f"analysis covers the latest quarter ({analyzed})"

        # A transcript landing after the report is a softer trigger — the numbers are unchanged
        # but management's commentary is new, and the earnings agent reads it.
        transcript_marker = latest_transcript.get(ticker)
        transcript_new = False
        if not stale and transcript_marker and isinstance(fp, dict):
            transcript_new = fp.get("transcript") != transcript_marker
            if transcript_new:
                reason = f"new transcript {transcript_marker} since the last run"

        out.append({
            "ticker": ticker,
            "stale": stale or transcript_new,
            "severity": "reported" if stale else ("transcript" if transcript_new else "ok"),
            "reason": reason,
            "latest_period": _iso(period),
            "analyzed_period": _iso(analyzed),
            "last_run": _iso(run_date),
            "latest_transcript": transcript_marker,
        })
    return out
