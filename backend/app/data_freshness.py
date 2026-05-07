"""Deterministic freshness reporting (Phase 3 of AI_REPORTING_IMPROVEMENT_PLAN).

After ingestion, we want to answer per-category: is the data we have actually
the latest? Today the agents reason on whatever's in the DB without knowing
how stale it is — so claims about "current" / "latest" data aren't grounded.

This module is pure code (no LLM). It reads existing tables and returns a
status per category. Agent prompts get warnings prepended; the API surfaces
the report; the frontend can render a status panel.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.estimate import AnalystEstimate
from app.models.financial import Financial
from app.models.price import DailyPrice
from app.models.transcript import EarningsTranscript
from app.models.valuation import Valuation

logger = logging.getLogger(__name__)


class Status(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass
class CategoryFreshness:
    status: Status
    message: str
    latest_date: date | None = None
    expected_date: date | None = None
    days_stale: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        if self.latest_date:
            d["latest_date"] = self.latest_date.isoformat()
        if self.expected_date:
            d["expected_date"] = self.expected_date.isoformat()
        return d


@dataclass
class FreshnessReport:
    ticker: str
    run_date: date
    categories: dict[str, CategoryFreshness] = field(default_factory=dict)

    @property
    def warnings(self) -> list[str]:
        """Human-readable warnings worth surfacing to agents and the UI."""
        out = []
        for name, c in self.categories.items():
            if c.status in (Status.STALE, Status.MISSING):
                out.append(f"{name}: {c.message}")
        return out

    @property
    def has_issues(self) -> bool:
        return any(
            c.status in (Status.STALE, Status.MISSING)
            for c in self.categories.values()
        )

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "run_date": self.run_date.isoformat(),
            "categories": {k: v.to_dict() for k, v in self.categories.items()},
            "warnings": self.warnings,
            "has_issues": self.has_issues,
        }


# ────────────────────────────────────────────────────────────────────────────
# Date helpers
# ────────────────────────────────────────────────────────────────────────────


def _latest_expected_trading_day(today: date | None = None) -> date:
    """Latest US trading day that should have a completed bar.

    V1: roll back from today to the most recent weekday. Doesn't handle
    holidays (Thanksgiving, MLK Day, etc.) — those will produce a
    1-day-stale false positive a few times per year. Acceptable for V1;
    swap in a real exchange calendar later.
    """
    today = today or date.today()
    d = today
    # Roll back through Sat/Sun
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# ────────────────────────────────────────────────────────────────────────────
# Per-category checks
# ────────────────────────────────────────────────────────────────────────────


async def _check_price(db: AsyncSession, ticker: str) -> CategoryFreshness:
    result = await db.execute(
        select(DailyPrice.date)
        .where(DailyPrice.ticker == ticker)
        .order_by(DailyPrice.date.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    expected = _latest_expected_trading_day()

    if latest is None:
        return CategoryFreshness(
            status=Status.MISSING,
            message="No daily price rows in DB",
            expected_date=expected,
        )

    days_stale = (expected - latest).days
    if days_stale <= 0:
        return CategoryFreshness(
            status=Status.FRESH,
            message=f"Latest price {latest} matches expected trading day",
            latest_date=latest,
            expected_date=expected,
            days_stale=0,
        )
    if days_stale <= 1:
        # Common case: market hasn't closed yet today, so yfinance may not
        # have today's bar yet. Treat as fresh-ish.
        return CategoryFreshness(
            status=Status.FRESH,
            message=f"Latest price {latest} is 1 trading day old (acceptable)",
            latest_date=latest,
            expected_date=expected,
            days_stale=1,
        )
    return CategoryFreshness(
        status=Status.STALE,
        message=f"Latest price {latest} is {days_stale} trading days behind expected {expected}",
        latest_date=latest,
        expected_date=expected,
        days_stale=days_stale,
    )


async def _check_financials(db: AsyncSession, ticker: str) -> CategoryFreshness:
    result = await db.execute(
        select(Financial)
        .where(Financial.ticker == ticker)
        .order_by(Financial.period_end_date.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    today = date.today()

    if latest is None:
        return CategoryFreshness(
            status=Status.MISSING,
            message="No financials in DB",
        )

    age_days = (today - latest.period_end_date).days
    if age_days <= 100:
        return CategoryFreshness(
            status=Status.FRESH,
            message=f"Latest period {latest.period} ({latest.period_end_date}) is {age_days} days old — within reporting window",
            latest_date=latest.period_end_date,
            days_stale=age_days,
        )
    if age_days <= 140:
        return CategoryFreshness(
            status=Status.STALE,
            message=f"Latest period {latest.period} is {age_days} days old — a newer quarter may have been reported",
            latest_date=latest.period_end_date,
            days_stale=age_days,
        )
    return CategoryFreshness(
        status=Status.STALE,
        message=f"Latest period {latest.period} is {age_days} days old — almost certainly stale, missing recent earnings",
        latest_date=latest.period_end_date,
        days_stale=age_days,
    )


async def _check_valuation(db: AsyncSession, ticker: str) -> CategoryFreshness:
    val_result = await db.execute(
        select(Valuation.date)
        .where(Valuation.ticker == ticker)
        .order_by(Valuation.date.desc())
        .limit(1)
    )
    val_date = val_result.scalar_one_or_none()

    price_result = await db.execute(
        select(DailyPrice.date)
        .where(DailyPrice.ticker == ticker)
        .order_by(DailyPrice.date.desc())
        .limit(1)
    )
    price_date = price_result.scalar_one_or_none()

    if val_date is None:
        return CategoryFreshness(
            status=Status.MISSING,
            message="No valuation snapshot in DB",
        )

    if price_date and val_date < price_date:
        days_stale = (price_date - val_date).days
        return CategoryFreshness(
            status=Status.STALE,
            message=f"Valuation snapshot {val_date} predates latest price {price_date} by {days_stale} days",
            latest_date=val_date,
            expected_date=price_date,
            days_stale=days_stale,
        )

    return CategoryFreshness(
        status=Status.FRESH,
        message=f"Valuation snapshot {val_date} is current",
        latest_date=val_date,
    )


async def _check_news(db: AsyncSession, ticker: str) -> CategoryFreshness:
    result = await db.execute(
        select(Document.date)
        .where(Document.ticker == ticker)
        .where(Document.doc_type == "news")
        .order_by(Document.date.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    today = date.today()

    if latest is None:
        return CategoryFreshness(
            status=Status.MISSING,
            message="No news documents in DB",
        )

    age_days = (today - latest).days
    if age_days <= 14:
        return CategoryFreshness(
            status=Status.FRESH,
            message=f"Latest news from {latest} ({age_days} days ago)",
            latest_date=latest,
            days_stale=age_days,
        )
    if age_days <= 30:
        return CategoryFreshness(
            status=Status.STALE,
            message=f"Latest news from {latest} ({age_days} days ago) — sentiment may be outdated",
            latest_date=latest,
            days_stale=age_days,
        )
    return CategoryFreshness(
        status=Status.STALE,
        message=f"Latest news from {latest} ({age_days} days ago) — sentiment significantly stale",
        latest_date=latest,
        days_stale=age_days,
    )


async def _check_transcripts(db: AsyncSession, ticker: str) -> CategoryFreshness:
    """Fresh if the latest transcript matches the latest financial period."""
    fin_result = await db.execute(
        select(Financial)
        .where(Financial.ticker == ticker)
        .order_by(Financial.period_end_date.desc())
        .limit(1)
    )
    latest_fin = fin_result.scalar_one_or_none()

    tr_result = await db.execute(
        select(EarningsTranscript)
        .where(EarningsTranscript.ticker == ticker)
        .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
        .limit(1)
    )
    latest_tr = tr_result.scalar_one_or_none()

    if latest_tr is None:
        return CategoryFreshness(
            status=Status.MISSING,
            message="No earnings transcripts in DB",
        )

    if latest_fin is None:
        return CategoryFreshness(
            status=Status.UNKNOWN,
            message=f"Have transcript Q{latest_tr.quarter} {latest_tr.year} but no financials to compare against",
        )

    fin_q = (latest_fin.period_end_date.month - 1) // 3 + 1
    fin_y = latest_fin.period_end_date.year

    if (latest_tr.year, latest_tr.quarter) >= (fin_y, fin_q):
        return CategoryFreshness(
            status=Status.FRESH,
            message=f"Transcript Q{latest_tr.quarter} {latest_tr.year} matches latest period",
            latest_date=latest_tr.transcript_date,
        )
    return CategoryFreshness(
        status=Status.STALE,
        message=(
            f"Transcript Q{latest_tr.quarter} {latest_tr.year} is older than "
            f"latest financial period Q{fin_q} {fin_y}"
        ),
        latest_date=latest_tr.transcript_date,
    )


async def _check_analyst_estimates(db: AsyncSession, ticker: str) -> CategoryFreshness:
    """Fresh if at least one future-dated estimate exists."""
    today = date.today()
    result = await db.execute(
        select(AnalystEstimate)
        .where(AnalystEstimate.ticker == ticker)
        .where(AnalystEstimate.period_end_date >= today)
        .order_by(AnalystEstimate.period_end_date.asc())
        .limit(1)
    )
    future = result.scalar_one_or_none()

    if future is not None:
        return CategoryFreshness(
            status=Status.FRESH,
            message=f"Forward estimates available through {future.period_end_date}",
            latest_date=future.period_end_date,
        )

    # No future estimates — check if we have any at all
    any_result = await db.execute(
        select(AnalystEstimate.period_end_date)
        .where(AnalystEstimate.ticker == ticker)
        .order_by(AnalystEstimate.period_end_date.desc())
        .limit(1)
    )
    last = any_result.scalar_one_or_none()
    if last is None:
        return CategoryFreshness(
            status=Status.MISSING,
            message="No analyst estimates in DB",
        )
    return CategoryFreshness(
        status=Status.STALE,
        message=f"All estimates are in the past (latest period {last})",
        latest_date=last,
    )


async def _check_summarizer(db: AsyncSession, ticker: str) -> CategoryFreshness:
    """Whether the latest transcript has been LLM-summarized.

    Affects the 3 consumer agents (earnings/industry/valuation) since they
    skip transcript context entirely if the latest transcript has no summary.
    """
    result = await db.execute(
        select(EarningsTranscript)
        .where(EarningsTranscript.ticker == ticker)
        .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    if latest is None:
        return CategoryFreshness(
            status=Status.MISSING,
            message="No transcript to summarize",
        )
    if latest.summary is None:
        return CategoryFreshness(
            status=Status.STALE,
            message=(
                f"Latest transcript Q{latest.quarter} {latest.year} has no LLM summary — "
                "earnings/industry/valuation agents will skip transcript context"
            ),
        )
    return CategoryFreshness(
        status=Status.FRESH,
        message=f"Transcript Q{latest.quarter} {latest.year} is summarized",
    )


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────


CATEGORY_CHECKS = {
    "price": _check_price,
    "financials": _check_financials,
    "valuation": _check_valuation,
    "news": _check_news,
    "transcripts": _check_transcripts,
    "analyst_estimates": _check_analyst_estimates,
    "transcript_summary": _check_summarizer,
}


async def build_freshness_report(db: AsyncSession, ticker: str) -> FreshnessReport:
    report = FreshnessReport(ticker=ticker, run_date=date.today())
    for name, check_fn in CATEGORY_CHECKS.items():
        try:
            report.categories[name] = await check_fn(db, ticker)
        except Exception as e:
            logger.exception("[freshness] %s check failed for %s", name, ticker)
            report.categories[name] = CategoryFreshness(
                status=Status.UNKNOWN,
                message=f"Check failed: {e}",
            )
    return report


def format_freshness_warnings(report: FreshnessReport) -> str:
    """Render warnings as a short prefix block for agent prompts.

    Returns empty string when everything is fresh — the goal is signal,
    not noise. Only stale/missing categories surface here.
    """
    if not report.has_issues:
        return ""

    lines = ["DATA FRESHNESS WARNINGS — treat affected categories with caution:"]
    for name, c in report.categories.items():
        if c.status in (Status.STALE, Status.MISSING):
            lines.append(f"  - {name} [{c.status.value}]: {c.message}")
    lines.append(
        "Do NOT call any of the above categories 'current' or 'latest'. "
        "Caveat any claim that depends on them."
    )
    return "\n".join(lines)
