"""Persist transcript-summary segment revenue into the `segments` table (roadmap 4.1).

The transcript summarizer already extracts segment breakouts ("Data Center: $75 billion, +92% YoY")
into the summary JSONB; until now they never reached the relational `segments` table. This module
parses those strings DETERMINISTICALLY (no LLM — the LLM extracted once; code does the arithmetic)
and upserts rows keyed (ticker, period_end_date, segment_name). Honest parsing: anything that
doesn't parse cleanly stays NULL rather than guessed.
"""

import logging
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Financial, Segment
from app.models.transcript import EarningsTranscript

logger = logging.getLogger(__name__)

_MONEY = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)\s*(billion|million|thousand|bn|b|mm|m|k)?", re.I)
_MULT = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6,
         "thousand": 1e3, "k": 1e3}
_YOY = re.compile(r"([+\-−]?\s*[\d.]+)\s*%\s*(?:yoy|y/y|year[- ]over[- ]year)", re.I)


def _parse_money(s) -> float | None:
    """'$75 billion' → 75e9; '$6.4B' → 6.4e9; 'not disclosed' → None."""
    if not s or not isinstance(s, str):
        return None
    m = _MONEY.search(s)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    val *= _MULT.get(unit, 1.0)
    # A bare small number with no unit ("75") is ambiguous — reject rather than guess.
    if not unit and val < 1e6:
        return None
    return val


def _parse_growth_yoy(s) -> float | None:
    """'+92% YoY, +21% QoQ' → 0.92. Only YoY-labeled figures count; a lone '+31% QoQ' is None."""
    if not s or not isinstance(s, str):
        return None
    m = _YOY.search(s)
    if not m:
        return None
    try:
        return round(float(m.group(1).replace("−", "-").replace(" ", "")) / 100.0, 4)
    except ValueError:
        return None


async def persist_segments(db: AsyncSession, ticker: str) -> int:
    """Parse the latest transcript summary's segments into `segments` rows. Returns rows upserted.

    period_end_date = the most recent filed quarter ending on/before the call date (an earnings
    call discusses the just-ended quarter)."""
    ticker = ticker.upper()
    t = (
        await db.execute(
            select(EarningsTranscript)
            .where(EarningsTranscript.ticker == ticker)
            .order_by(EarningsTranscript.year.desc(), EarningsTranscript.quarter.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not t or not isinstance(t.summary, dict):
        return 0
    raw_segments = t.summary.get("segments") or []
    if not raw_segments:
        return 0

    anchor = t.transcript_date or date.today()
    period_end = (
        await db.execute(
            select(Financial.period_end_date)
            .where(Financial.ticker == ticker, Financial.period_end_date <= anchor)
            .order_by(Financial.period_end_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if period_end is None:
        return 0

    rows = []
    for s in raw_segments:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        rows.append({
            "ticker": ticker,
            "period_end_date": period_end,
            "segment_name": str(s["name"])[:200],
            "revenue": _parse_money(s.get("revenue")),
            "growth_yoy": _parse_growth_yoy(s.get("growth")),
        })
    if not rows:
        return 0

    stmt = insert(Segment).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_seg_ticker_period_name",
        set_={"revenue": stmt.excluded.revenue, "growth_yoy": stmt.excluded.growth_yoy},
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("[segments] %s: %d segment rows for %s", ticker, len(rows), period_end)
    return len(rows)
