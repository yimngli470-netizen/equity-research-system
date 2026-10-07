"""Compatibility grading entry point. No automatic inference from vague legacy criteria.

Fundamental and price events now resolve separately via exact registered contracts.
Qualitative adjudication is explicitly supplied to accountability.resolve_events by
an approved research workflow; the ordinary pipeline never starts an extra grader.
Old outcomes remain byte-for-byte on their original thesis IDs.
"""
from datetime import date
from app.accountability.contracts import exact_fiscal_end
from app.accountability.store import resolve_events
from app.thesis.market_marks import mark_thesis_returns


def _parse_by_date(value, declared_periods=None):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)  # exact ISO only; no truncation or quarter guessing
    except ValueError:
        return exact_fiscal_end(value, declared_periods or {})


async def grade_due_theses(db, ticker: str) -> int:
    # A price diagnostic is separate from event truth and never enters its packet.
    await mark_thesis_returns(db, ticker)
    count = await resolve_events(db, ticker.upper())
    await db.commit()
    return count
