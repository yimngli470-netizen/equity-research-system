"""Thesis journal writer (roadmap 3.1).

`snapshot_thesis` captures the current verdict as an immutable record. It runs as the last step of
Run-Full-Pipeline (called from the decision engine) — NOT on a background scheduler. One thesis per
ticker per day (upsert by date), so re-running the pipeline the same day refreshes that day's call
rather than spamming the journal.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisReport
from app.models.price import DailyPrice
from app.models.score import StockScore
from app.models.stock import Stock
from app.models.thesis import StockThesis

logger = logging.getLogger(__name__)


async def _latest_report(db: AsyncSession, ticker: str, agent_type: str) -> dict | None:
    row = (
        await db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.ticker == ticker, AnalysisReport.agent_type == agent_type)
            .order_by(AnalysisReport.run_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row and isinstance(row.report, dict) and "error" not in row.report:
        return row.report
    return None


def _fair_value(valuation: dict | None) -> float | None:
    """Pull the agent's base fair value from triangulation → target mid → DCF base."""
    if not valuation:
        return None
    tri = valuation.get("triangulation") or {}
    for v in (tri.get("your_fair_value"),
              (valuation.get("target_price_range") or {}).get("mid"),
              (valuation.get("dcf_analysis") or {}).get("intrinsic_value_base")):
        if isinstance(v, (int, float)):
            return float(v)
    return None


async def snapshot_thesis(db: AsyncSession, ticker: str, decision_signal: str | None = None) -> StockThesis | None:
    """Write an immutable thesis snapshot for today. No-op (returns None) without a judge verdict."""
    ticker = ticker.upper()
    judge = await _latest_report(db, ticker, "judge")
    if not judge:
        return None  # no dialectic verdict → nothing worth journaling

    valuation = await _latest_report(db, ticker, "valuation")
    stock = await db.get(Stock, ticker)
    score = (
        await db.execute(
            select(StockScore).where(StockScore.ticker == ticker)
            .order_by(StockScore.date.desc()).limit(1)
        )
    ).scalar_one_or_none()
    price = (
        await db.execute(
            select(DailyPrice.close).where(DailyPrice.ticker == ticker)
            .order_by(DailyPrice.date.desc()).limit(1)
        )
    ).scalar_one_or_none()

    conviction = judge.get("conviction")
    values = {
        "ticker": ticker,
        "as_of": date.today(),
        "archetype": stock.archetype if stock else None,
        "leaning": judge.get("leaning"),
        "conviction": float(conviction) if isinstance(conviction, (int, float)) else None,
        "verdict_summary": (judge.get("verdict_summary") or judge.get("synthesis") or "")[:2000] or None,
        "fair_value": _fair_value(valuation),
        "price_at": float(price) if price is not None else None,
        "composite": score.composite_score if score else None,
        "signal": score.signal if score else None,
        "decision_signal": decision_signal,
        "kill_criteria": judge.get("kill_criteria") or [],
        "status": "open",
    }

    # Upsert today's thesis. Don't clobber grading already done for today.
    stmt = insert(StockThesis).values(**values).on_conflict_do_update(
        constraint="uq_thesis_ticker_asof",
        set_={k: values[k] for k in (
            "archetype", "leaning", "conviction", "verdict_summary", "fair_value",
            "price_at", "composite", "signal", "decision_signal", "kill_criteria",
        )},
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("[thesis] snapshot %s as_of=%s leaning=%s conviction=%s kills=%d",
                ticker, values["as_of"], values["leaning"], values["conviction"],
                len(values["kill_criteria"]))
    return (
        await db.execute(
            select(StockThesis).where(StockThesis.ticker == ticker, StockThesis.as_of == date.today())
        )
    ).scalar_one_or_none()
