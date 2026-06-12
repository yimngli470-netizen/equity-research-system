"""Shared context builders for the bull / bear / judge dialectic (roadmap 2.1).

The dialectic is a *synthesis* layer: it reasons over the analytical agents' outputs (news,
earnings, industry, valuation) plus the financial spine and the archetype, rather than re-deriving
them. Bull and bear both see the same evidence pack; the judge sees the bull case and the bear case
and must reconcile them. Keeping the context assembly here ensures bull and bear argue from an
identical evidence base — the disagreement should come from interpretation, not different inputs.
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.computed_metrics import format_for_llm, get_computed_metrics
from app.models.analysis import AnalysisReport
from app.models.score import StockScore
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# The analytical agents the dialectic synthesizes, and the fields worth carrying forward.
_CONDENSE: dict[str, list[str]] = {
    "news": ["overall_sentiment", "summary"],
    "earnings": ["earnings_quality_score", "trend_analysis", "forward_outlook", "risks",
                 "beat_miss_history", "summary"],
    "industry": ["demand_cyclicality", "cycle_position", "cycle_assessment", "competitive_position",
                 "theme_exposures", "industry_risks", "summary"],
    "valuation": ["valuation_verdict", "valuation_score", "target_price_range", "margin_of_safety",
                  "multiples_analysis", "consensus_comparison", "dcf_analysis", "summary"],
}


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


def _condense(agent_type: str, report: dict) -> dict:
    keys = _CONDENSE.get(agent_type, [])
    return {k: report[k] for k in keys if k in report and report[k] is not None}


async def _archetype_and_screen(db: AsyncSession, ticker: str) -> str:
    stock = await db.get(Stock, ticker)
    parts = []
    if stock and stock.archetype:
        parts.append(f"Business-model archetype: {stock.archetype}"
                     + (f" — {stock.archetype_rationale}" if stock.archetype_rationale else ""))
    score = (
        await db.execute(
            select(StockScore).where(StockScore.ticker == ticker)
            .order_by(StockScore.date.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if score:
        parts.append(
            f"Quant SCREEN (a peer-relative rank, NOT a verdict): composite={score.composite_score:.2f} "
            f"signal={score.signal}. Treat this as one input, not the answer."
        )
    return "\n".join(parts)


async def build_evidence_pack(db: AsyncSession, ticker: str) -> str:
    """The shared evidence base bull and bear both argue from."""
    snapshot = await get_computed_metrics(db, ticker)
    financials = format_for_llm(snapshot)

    sections = [financials, ""]
    meta = await _archetype_and_screen(db, ticker)
    if meta:
        sections += [meta, ""]

    sections.append("=== ANALYST AGENT FINDINGS (synthesize these — do not re-derive) ===")
    any_report = False
    for agent_type in ("news", "earnings", "industry", "valuation"):
        report = await _latest_report(db, ticker, agent_type)
        if report is None:
            sections.append(f"\n[{agent_type}] — no report available")
            continue
        any_report = True
        sections.append(f"\n--- {agent_type.upper()} ---")
        sections.append(json.dumps(_condense(agent_type, report), indent=2, default=str))
    if not any_report:
        logger.warning("[dialectic] %s: no analyst agent reports to synthesize", ticker)

    return "\n".join(sections)


async def build_judge_context(db: AsyncSession, ticker: str) -> str:
    """The bull case + the bear case the judge must reconcile (plus a short data anchor), and the
    judge's OWN PRIOR RECORD on this name (5.3) — each fresh verdict is written knowing how the
    last one scored."""
    bull = await _latest_report(db, ticker, "bull")
    bear = await _latest_report(db, ticker, "bear")
    meta = await _archetype_and_screen(db, ticker)
    record = await _own_track_record(db, ticker)

    sections = []
    if meta:
        sections += [meta, ""]
    sections.append("=== BULL CASE ===")
    sections.append(json.dumps(bull, indent=2, default=str) if bull else "[bull case unavailable]")
    sections.append("\n=== BEAR CASE ===")
    sections.append(json.dumps(bear, indent=2, default=str) if bear else "[bear case unavailable]")
    if record:
        sections.append("\n=== YOUR PRIOR RECORD ON THIS NAME (graded — calibrate against it) ===")
        sections.append(record)
    return "\n".join(sections)


async def _own_track_record(db: AsyncSession, ticker: str) -> str | None:
    """The judge's previous calls on this ticker: graded kill-criteria outcomes + the standing open
    call. Deterministic context, no LLM cost — accountability feeding back into judgment."""
    from app.models.thesis import StockThesis

    theses = (
        await db.execute(
            select(StockThesis).where(StockThesis.ticker == ticker)
            .order_by(StockThesis.as_of.desc()).limit(4)
        )
    ).scalars().all()
    if not theses:
        return None
    lines: list[str] = []
    for th in theses:
        head = (f"- {th.as_of}: leaning={th.leaning} conviction={th.conviction} "
                f"decision={th.decision_signal} (price then ${th.price_at:.2f})" if th.price_at else
                f"- {th.as_of}: leaning={th.leaning} conviction={th.conviction} decision={th.decision_signal}")
        lines.append(head)
        outcome = th.outcome or {}
        if th.status == "graded" or outcome.get("predictions"):
            for idx, p in sorted((outcome.get("predictions") or {}).items()):
                kc = (th.kill_criteria or [])
                pred_txt = kc[int(idx)].get("prediction", "?")[:90] if int(idx) < len(kc) else "?"
                lines.append(f"    [{p.get('result', '?').upper()}] \"{pred_txt}\"")
            if outcome.get("realized_return") is not None:
                xr = outcome.get("excess_return")
                lines.append(f"    return {outcome['realized_return']:+.1%}"
                             + (f" (vs SPY {xr:+.1%})" if xr is not None else ""))
        else:
            lines.append("    [still open — not yet graded]")
    return "\n".join(lines)
