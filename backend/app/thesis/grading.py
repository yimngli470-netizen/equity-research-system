"""Outcome grading (roadmap 3.2) — grade a thesis's predictions once they come due.

Runs as a step of Run-Full-Pipeline (called from `run_decision`), NOT a background scheduler (per
user). On each run it finds OPEN theses whose kill-criteria `by_date` has passed and grades the due
ones hit/miss/partial against the freshly-ingested data (an LLM pass — the predictions are
natural-language), plus a deterministic price-vs-fair-value check. It's cheap when nothing is due
(a query + date parse, no LLM). Grading only fills `outcome`/`status`; it never rewrites the call.
"""

import asyncio
import json
import logging
import re
from datetime import date, timedelta

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.financial import Financial
from app.models.price import DailyPrice
from app.models.thesis import StockThesis

logger = logging.getLogger(__name__)

MODEL = settings.sonnet_model

_FQ = re.compile(r"Q([1-4])\s*FY\s*'?(\d{2,4})", re.I)
_QEND = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _parse_by_date(s) -> date | None:
    """Parse a kill-criterion date: ISO (2026-09-30) or fiscal quarter (Q4 FY2026)."""
    if not s:
        return None
    s = str(s).strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = _FQ.search(s)
    if m:
        q, y = int(m.group(1)), int(m.group(2))
        if y < 100:
            y += 2000
        mo, d = _QEND[q]
        return date(y, mo, d)
    return None


_GRADE_SYS = """You grade falsifiable predictions made in a stock thesis. For EACH prediction, using
ONLY the data provided (which post-dates the thesis), decide whether it came true:
  "hit"          — clearly happened as predicted
  "miss"         — clearly did not happen
  "partial"      — partially / ambiguously happened
  "undetermined" — the provided data is insufficient to judge
Cite the specific evidence. Do not speculate beyond the data.

Respond with JSON only: {"grades":[{"index":int,"result":"hit|miss|partial|undetermined","evidence":"string"}]}"""


def _grade_llm(thesis_date, predictions: list[tuple[int, dict]], context: str) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    pred_lines = "\n".join(
        f'  index {i}: "{kc.get("prediction","")}" (watch: {kc.get("watch_metric","")}; '
        f'by {kc.get("by_date","")}; would confirm: {kc.get("would_confirm","")})'
        for i, kc in predictions
    )
    user = (f"Thesis written {thesis_date}. Grade these predictions:\n{pred_lines}\n\n"
            f"DATA SINCE THE THESIS:\n{context}\n\nJSON only.")
    resp = client.messages.create(model=MODEL, max_tokens=1500, system=_GRADE_SYS,
                                  messages=[{"role": "user", "content": user}])
    content = resp.content[0].text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


async def _benchmark_close_at(db: AsyncSession, on: date) -> float | None:
    """SPY close on/just before `on` (nearest prior trading day)."""
    from app.ingestion.prices import BENCHMARK_TICKER
    return (
        await db.execute(
            select(DailyPrice.close)
            .where(DailyPrice.ticker == BENCHMARK_TICKER, DailyPrice.date <= on)
            .order_by(DailyPrice.date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _context_since(db: AsyncSession, ticker: str, since: date, price_now: float | None,
                         price_at: float | None) -> str:
    """Quarterly financials reported around/after the thesis + the price move — the resolving data."""
    rows = (
        await db.execute(
            select(Financial).where(Financial.ticker == ticker,
                                    Financial.period_end_date >= since - timedelta(days=200))
            .order_by(Financial.period_end_date.desc()).limit(6)
        )
    ).scalars().all()
    lines = ["Quarterly financials (most recent first):"]
    for r in rows:
        gm = (r.gross_profit / r.revenue) if (r.gross_profit and r.revenue) else None
        lines.append(
            f"  {r.period} (end {r.period_end_date}): "
            f"revenue {f'${r.revenue/1e9:.2f}B' if r.revenue else 'n/a'}, "
            f"net income {f'${r.net_income/1e9:.2f}B' if r.net_income else 'n/a'}, "
            f"gross margin {f'{gm:.1%}' if gm is not None else 'n/a'}"
        )
    if price_at and price_now:
        lines.append(f"Price: {price_at:.2f} at thesis → {price_now:.2f} now "
                     f"({(price_now/price_at-1):+.1%}).")
    return "\n".join(lines)


async def grade_due_theses(db: AsyncSession, ticker: str) -> int:
    """Grade any open thesis for `ticker` with past-due, ungraded predictions. Returns # graded."""
    ticker = ticker.upper()
    today = date.today()
    theses = (
        await db.execute(
            select(StockThesis).where(StockThesis.ticker == ticker, StockThesis.status == "open")
        )
    ).scalars().all()
    if not theses:
        return 0

    price_now = (
        await db.execute(
            select(DailyPrice.close).where(DailyPrice.ticker == ticker)
            .order_by(DailyPrice.date.desc()).limit(1)
        )
    ).scalar_one_or_none()

    graded_count = 0
    for th in theses:
        kcs = th.kill_criteria or []
        if not kcs:
            continue
        outcome = dict(th.outcome or {})
        graded = dict(outcome.get("predictions") or {})  # keyed by str(index)

        due = [(i, kc) for i, kc in enumerate(kcs)
               if str(i) not in graded
               and (_parse_by_date(kc.get("by_date")) or date.max) <= today]
        if not due:
            continue
        if not settings.anthropic_api_key:
            return graded_count

        context = await _context_since(db, ticker, th.as_of, price_now, th.price_at)
        try:
            out = await asyncio.to_thread(_grade_llm, th.as_of, due, context)
        except Exception:
            logger.exception("[thesis] grading LLM failed for %s thesis %s", ticker, th.as_of)
            continue

        for g in out.get("grades", []):
            idx = g.get("index")
            if idx is None:
                continue
            graded[str(idx)] = {
                "result": str(g.get("result", "undetermined")).lower(),
                "evidence": (g.get("evidence") or "")[:600],
                "graded_on": today.isoformat(),
            }

        # Deterministic price + fair-value record.
        if th.price_at and price_now:
            outcome["realized_return"] = round(price_now / th.price_at - 1, 4)
            # Benchmark-relative (4.1): "BUY worked" must mean BEAT THE INDEX over the window,
            # not just "went up". SPY return over the same thesis window → excess return.
            spy_then = await _benchmark_close_at(db, th.as_of)
            spy_now = await _benchmark_close_at(db, today)
            if spy_then and spy_now:
                spy_ret = round(spy_now / spy_then - 1, 4)
                outcome["benchmark_return"] = spy_ret
                outcome["excess_return"] = round(outcome["realized_return"] - spy_ret, 4)
        if th.fair_value and th.price_at:
            outcome["fair_value_gap_at_thesis"] = round(th.fair_value / th.price_at - 1, 4)
        results = [v["result"] for v in graded.values()]
        scored = [r for r in results if r in ("hit", "miss", "partial")]
        if scored:
            outcome["hit_rate"] = round(
                sum(1.0 if r == "hit" else 0.5 if r == "partial" else 0.0 for r in scored) / len(scored), 3
            )
        outcome["predictions"] = graded

        th.outcome = outcome
        if len(graded) >= len(kcs):
            th.status = "graded"
            th.graded_at = today
        graded_count += 1
        logger.info("[thesis] graded %s thesis %s: %d/%d predictions, hit_rate=%s status=%s",
                    ticker, th.as_of, len(graded), len(kcs), outcome.get("hit_rate"), th.status)

    await db.commit()
    return graded_count
