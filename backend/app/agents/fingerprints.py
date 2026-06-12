"""Input-fingerprint markers for smart agent caching (2026-06-11).

Each marker is a cheap deterministic DB read identifying the *current state* of one data source an
agent's context is built from. An agent's `compute_fingerprint` composes the markers it actually
reads; if none of them changed since the last report, the report is reused and the LLM call skipped.
No LLM, no heavy queries — a fingerprint costs a few indexed lookups.
"""

import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisReport
from app.models.document import Document
from app.models.earnings import EarningsEvent
from app.models.estimate import AnalystEstimate
from app.models.financial import Financial
from app.models.key_metric import TickerKpiValue
from app.models.price import DailyPrice
from app.models.stock import Stock
from app.models.transcript import EarningsTranscript
from app.models.valuation import Valuation


async def financial_marker(db: AsyncSession, ticker: str) -> str | None:
    """Latest reported quarter — a new filing is the single biggest invalidator."""
    v = (
        await db.execute(
            select(func.max(Financial.period_end_date)).where(Financial.ticker == ticker)
        )
    ).scalar_one_or_none()
    return v.isoformat() if v else None


async def transcript_marker(db: AsyncSession, ticker: str) -> str | None:
    row = (
        await db.execute(
            select(EarningsTranscript.year, EarningsTranscript.quarter)
            .where(EarningsTranscript.ticker == ticker)
            .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
            .limit(1)
        )
    ).first()
    return f"{row.year}-Q{row.quarter}" if row else None


async def surprise_marker(db: AsyncSession, ticker: str) -> str | None:
    v = (
        await db.execute(
            select(func.max(EarningsEvent.report_date)).where(EarningsEvent.ticker == ticker)
        )
    ).scalar_one_or_none()
    return v.isoformat() if v else None


async def kpi_marker(db: AsyncSession, ticker: str) -> str | None:
    v = (
        await db.execute(
            select(func.max(TickerKpiValue.as_of)).where(TickerKpiValue.ticker == ticker)
        )
    ).scalar_one_or_none()
    return str(v) if v else None


async def estimates_marker(db: AsyncSession, ticker: str) -> str | None:
    """Hash of the forward consensus rows (EPS to the cent, revenue to $10M) — revisions beyond
    rounding noise invalidate; tiny drift doesn't."""
    rows = (
        await db.execute(
            select(AnalystEstimate.period_end_date, AnalystEstimate.eps_consensus,
                   AnalystEstimate.revenue_consensus)
            .where(AnalystEstimate.ticker == ticker)
            .order_by(AnalystEstimate.period_end_date.asc())
            .limit(8)
        )
    ).all()
    if not rows:
        return None
    parts = [
        f"{r.period_end_date}|{round(r.eps_consensus, 2) if r.eps_consensus is not None else 'x'}"
        f"|{round(r.revenue_consensus / 1e7) if r.revenue_consensus is not None else 'x'}"
        for r in rows
    ]
    return hashlib.sha256(";".join(parts).encode()).hexdigest()[:12]


async def price_targets_marker(db: AsyncSession, ticker: str) -> str | None:
    row = (
        await db.execute(
            select(Valuation.target_mean_price, Valuation.target_median_price)
            .where(Valuation.ticker == ticker)
            .order_by(Valuation.date.desc())
            .limit(1)
        )
    ).first()
    if not row:
        return None
    mean_v = round(row.target_mean_price) if row.target_mean_price is not None else "x"
    med_v = round(row.target_median_price) if row.target_median_price is not None else "x"
    return f"{mean_v}|{med_v}"


async def price_marker(db: AsyncSession, ticker: str) -> float | None:
    """Latest close — compared with a RELATIVE tolerance (±5%) by the consuming agent, so daily
    wiggles don't invalidate a valuation thesis but a real move does."""
    return (
        await db.execute(
            select(DailyPrice.close).where(DailyPrice.ticker == ticker)
            .order_by(DailyPrice.date.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def news_marker(db: AsyncSession, ticker: str) -> str | None:
    """Newest news document (id + date) — any new article invalidates the NEWS agent only."""
    row = (
        await db.execute(
            select(Document.id, Document.date)
            .where(Document.ticker == ticker, Document.doc_type == "news")
            .order_by(Document.date.desc(), Document.id.desc())
            .limit(1)
        )
    ).first()
    return f"{row.id}|{row.date}" if row else None


async def archetype_marker(db: AsyncSession, ticker: str) -> str | None:
    return (
        await db.execute(select(Stock.archetype).where(Stock.ticker == ticker))
    ).scalar_one_or_none()


async def report_marker(db: AsyncSession, ticker: str, agent_type: str) -> str | None:
    """Identity (id.version) of the latest non-error report of another agent — lets downstream
    agents (debate, judge) invalidate exactly when an upstream report was regenerated."""
    row = (
        await db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.ticker == ticker, AnalysisReport.agent_type == agent_type)
            .order_by(AnalysisReport.run_date.desc(), AnalysisReport.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row or not isinstance(row.report, dict) or "error" in row.report:
        return None
    return f"{row.id}.{row.version}"


async def news_materiality(db: AsyncSession, ticker: str,
                           high_impact_threshold: float = 0.85) -> tuple[float | None, str | None]:
    """For the debate/judge materiality trigger: (overall_sentiment, high-impact marker).
    Routine news must NOT re-litigate the dialectic, so sentiment is compared with a ±0.3 band and
    the marker only changes when a NEW news report carrying a high-impact item appears."""
    row = (
        await db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.ticker == ticker, AnalysisReport.agent_type == "news")
            .order_by(AnalysisReport.run_date.desc(), AnalysisReport.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row or not isinstance(row.report, dict) or "error" in row.report:
        return None, None
    rep = row.report
    sentiment = rep.get("overall_sentiment")
    sentiment = float(sentiment) if isinstance(sentiment, (int, float)) else None
    items = rep.get("items") or []
    has_high_impact = any(
        isinstance(i, dict) and isinstance(i.get("impact_score"), (int, float))
        and abs(i["impact_score"]) >= high_impact_threshold
        for i in items
    )
    return sentiment, (f"{row.id}.{row.version}" if has_high_impact else None)
