"""Deterministic EPS-surprise statistics from `earnings_events`.

`beat_miss_history` used to be authored by the earnings LLM, which emitted `avg_surprise_pct` in
ambiguous units (it averaged the displayed PERCENTS, e.g. 11.45 meaning 11.45%). Downstream both
mis-read it: the normalizer treats the field as a FRACTION (±0.10 bounds) so 11.45 pinned the feature
to max, and the UI multiplies by 100 so 11.45 rendered as "+1145%". Surprise stats are a pure
measurement, so we compute them here from the raw `eps_surprise_pct` (already a fraction in the DB)
and overwrite the LLM's numbers — one source of truth, correct units everywhere.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.earnings import EarningsEvent

_WINDOW = 4  # trailing quarters that "last_4q" / the average summarise


@dataclass
class SurpriseStats:
    last_4q_eps_beats: int          # how many of the last 4 reported quarters beat consensus
    avg_surprise_pct: float         # mean EPS surprise over those quarters, as a FRACTION (0.117 = +11.7%)
    trend: str                      # improving | stable | deteriorating (recent 2 vs prior 2)


async def eps_surprise_stats(db: AsyncSession, ticker: str) -> SurpriseStats | None:
    """Compute trailing EPS-surprise stats from `earnings_events`, or None if there's no data."""
    rows = (
        await db.execute(
            select(EarningsEvent.eps_surprise_pct)
            .where(EarningsEvent.ticker == ticker, EarningsEvent.eps_surprise_pct.is_not(None))
            .order_by(EarningsEvent.report_date.desc())
            .limit(8)
        )
    ).scalars().all()
    surprises = [float(s) for s in rows]
    if not surprises:
        return None

    window = surprises[:_WINDOW]
    beats = sum(1 for s in window if s >= 0)
    avg = sum(window) / len(window)

    # Trend: the most recent two quarters vs the two before them (needs ≥4 to judge).
    trend = "stable"
    if len(surprises) >= 4:
        recent = sum(surprises[:2]) / 2
        prior = sum(surprises[2:4]) / 2
        if recent > prior + 0.02:
            trend = "improving"
        elif recent < prior - 0.02:
            trend = "deteriorating"

    return SurpriseStats(last_4q_eps_beats=beats, avg_surprise_pct=round(avg, 4), trend=trend)
