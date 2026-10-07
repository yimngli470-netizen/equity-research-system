"""Resolve explicit registered events; preserve legacy EPS grades without regrading.

Compiler `end_approx` is useful for projections, NOT an exact issuer quarter. The
legacy mutable Financial table cannot prove a first-release vintage or GAAP basis.
New registered events use app.accountability's exact contracts and captured sources.
The compatibility entry point stays cheap and deterministic, with no model calls.
"""
from app.accountability.store import resolve_events


async def grade_due_forecasts(db, ticker: str) -> int:
    count = await resolve_events(db, ticker.upper())
    await db.commit()
    return count
