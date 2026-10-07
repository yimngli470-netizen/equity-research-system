"""Event-probability scores plus explicitly labeled legacy conviction diagnostics.

Generic conviction is not a probability of thesis success or a directional return.
Legacy arithmetic is retained for historical inspection, never used to size trades.
"""

import logging
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.thesis import StockThesis

logger = logging.getLogger(__name__)

# Conviction buckets for the reliability curve. The judge's gate (engine.py) hinges at 0.35/0.5/0.6,
# so the bucket edges line up with the decision-relevant bands.
_BUCKETS: list[tuple[float, float]] = [(0.0, 0.35), (0.35, 0.5), (0.5, 0.6), (0.6, 0.75), (0.75, 1.01)]

_BULL = {"bull", "strong_bull"}
_BEAR = {"bear", "strong_bear"}


def _directional_outcome(leaning: str | None, realized_return: float | None) -> float | None:
    """Did the *call* pay off? 1.0 if the price moved the way the call implied, else 0.0.

    Neutral leanings and missing returns are unscoreable (None) — only directional calls count."""
    if realized_return is None:
        return None
    lean = (leaning or "").lower()
    if lean in _BULL:
        return 1.0 if realized_return > 0 else 0.0
    if lean in _BEAR:
        return 1.0 if realized_return < 0 else 0.0
    return None


@dataclass
class CalibrationBucket:
    lo: float
    hi: float
    n: int = 0
    mean_conviction: float | None = None   # predicted (forecast probability)
    mean_hit_rate: float | None = None      # observed — prediction hit-rate view
    mean_directional: float | None = None   # observed — did the call make money


@dataclass
class CalibrationReport:
    segment: str                  # "all" or an archetype name
    n_graded: int                 # theses with a gradable outcome
    brier_hit: float | None       # Brier vs prediction hit-rate (lower better)
    brier_directional: float | None  # Brier vs directional (price) success
    mean_conviction: float | None
    mean_hit_rate: float | None
    mean_directional: float | None
    overconfidence_gap: float | None  # mean_conviction − mean_directional (>0 ⇒ overconfident)
    buckets: list[CalibrationBucket] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def _summarize(segment: str, rows: list[dict]) -> CalibrationReport:
    """rows: list of {conviction, hit_rate, directional} with conviction always present."""
    conv = [r["conviction"] for r in rows]
    hits = [r["hit_rate"] for r in rows if r["hit_rate"] is not None]
    dirs = [r["directional"] for r in rows if r["directional"] is not None]

    brier_hit = _mean([(r["conviction"] - r["hit_rate"]) ** 2 for r in rows if r["hit_rate"] is not None])
    brier_dir = _mean([(r["conviction"] - r["directional"]) ** 2 for r in rows if r["directional"] is not None])

    mean_conv, mean_dir = _mean(conv), _mean(dirs)
    gap = round(mean_conv - mean_dir, 4) if (mean_conv is not None and mean_dir is not None) else None

    buckets: list[CalibrationBucket] = []
    for lo, hi in _BUCKETS:
        b_rows = [r for r in rows if lo <= r["conviction"] < hi]
        if not b_rows:
            buckets.append(CalibrationBucket(lo=lo, hi=round(min(hi, 1.0), 2)))
            continue
        buckets.append(CalibrationBucket(
            lo=lo, hi=round(min(hi, 1.0), 2), n=len(b_rows),
            mean_conviction=_mean([r["conviction"] for r in b_rows]),
            mean_hit_rate=_mean([r["hit_rate"] for r in b_rows if r["hit_rate"] is not None]),
            mean_directional=_mean([r["directional"] for r in b_rows if r["directional"] is not None]),
        ))

    return CalibrationReport(
        segment=segment, n_graded=len(rows), brier_hit=brier_hit, brier_directional=brier_dir,
        mean_conviction=mean_conv, mean_hit_rate=_mean(hits), mean_directional=mean_dir,
        overconfidence_gap=gap, buckets=buckets,
    )


async def _graded_rows(db: AsyncSession) -> list[dict]:
    """Every graded thesis with a usable conviction, as flat rows (with its archetype)."""
    theses = (
        await db.execute(
            select(StockThesis).where(StockThesis.status == "graded")
        )
    ).scalars().all()
    rows: list[dict] = []
    for th in theses:
        if th.conviction is None:
            continue
        outcome = th.outcome or {}
        hit_rate = outcome.get("hit_rate")
        directional = _directional_outcome(th.leaning, outcome.get("realized_return"))
        if hit_rate is None and directional is None:
            continue  # nothing to score this thesis against
        rows.append({
            "archetype": th.archetype or "unknown",
            "conviction": float(th.conviction),
            "hit_rate": float(hit_rate) if hit_rate is not None else None,
            "directional": directional,
        })
    return rows


async def compute_calibration(db: AsyncSession) -> dict:
    """Overall + per-archetype calibration over all graded theses. Returns a JSON-able dict."""
    rows = await _graded_rows(db)
    overall = _summarize("all", rows)

    by_arch: dict[str, list[dict]] = {}
    for r in rows:
        by_arch.setdefault(r["archetype"], []).append(r)
    segments = [_summarize(arch, arch_rows).to_dict() for arch, arch_rows in sorted(by_arch.items())]

    from app.accountability.store import probability_report
    # Compatibility fields deliberately contain no probability scores derived from conviction.
    return {
        "overall": _summarize("all", []).to_dict(),
        "by_archetype": [],
        "event_probabilities": await probability_report(db),
        "legacy_diagnostics": {
        "semantics": "Legacy conviction/outcome squared differences, not probability calibration",
        "grading_version": "legacy-v1",
        "overall": overall.to_dict(),
        "by_archetype": segments,
        },
        "note": "Only registered event probabilities receive proper scores. Generic conviction remains a separate legacy diagnostic; it does not change position sizing.",
    }


async def calibration_shrink(db: AsyncSession, archetype: str | None) -> tuple[float, str | None]:
    """No sizing adjustment from an uncalibrated conviction/outcome comparison.

    A future event-score-to-risk policy needs a separate reviewed design; even a
    proper Brier score alone is not a validated sizing model.
    """
    return 1.0, None
