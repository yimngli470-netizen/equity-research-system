"""Normalized / mid-cycle earnings (roadmap 2.2) — the de-biasing measurement for cyclicals.

A memory cyclical at the top of its cycle shows peak margins (MU: gross margin swings ~20% → 74%)
and therefore a deceptively LOW spot P/E — valuing it on those earnings is the classic peak-earnings
trap. This computes the through-cycle (mid-cycle) margin from the EDGAR history and restates current
earnings onto it, plus a cycle-position read, so the valuation agent can value on normalized earnings
instead of spot. Per §4a this is stats, not LLM: a deterministic measurement the agent reasons over.

Mid-cycle margin = the MEDIAN TTM margin over the available history (robust to the boom/bust tails).
Normalized net income = current TTM revenue × mid-cycle net margin (normalizes the margin, which is
the dominant cyclical swing; revenue-trend normalization is a later refinement).
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.measurement.profile import _safe_div, _ttm
from app.models.financial import Financial

MAX_QUARTERS = 32
MIN_QUARTERS = 8  # need ~2 years of TTM points to say anything about a cycle

logger = logging.getLogger(__name__)


@dataclass
class NormalizedEarnings:
    n_quarters: int
    # basis decides whether mid-cycle normalization even APPLIES (it only does for true cyclicals):
    #   'cyclical'  — margin-mean-reverting commodity cyclical → value on normalized earnings.
    #   'stable'    — stable / secular margins → normalized ≈ spot; spot is the right basis. The
    #                 mid-cycle numbers are shown as context (esp. if current >> median) but NOT mandated.
    #   'inflection'— historical median margin ≤ 0 (e.g. losses → profits turnaround); median-reversion
    #                 is INVALID, so normalized_* are suppressed.
    basis: str = "stable"
    ttm_revenue: float | None = None
    ttm_net_income: float | None = None
    current_net_margin: float | None = None
    current_operating_margin: float | None = None
    midcycle_net_margin: float | None = None        # median TTM net margin over history
    midcycle_operating_margin: float | None = None
    peak_net_margin: float | None = None
    trough_net_margin: float | None = None
    margin_ratio: float | None = None               # current net margin / mid-cycle (>1 = above mid)
    cycle_position: str | None = None               # cyclical: 'peak'|'mid'|'trough'; else 'stable'|'inflection'
    normalized_net_income: float | None = None       # ttm_revenue × mid-cycle net margin (None when basis='inflection')
    normalized_factor: float | None = None           # normalized / current net income (≈ how much spot overstates)

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


# Archetypes whose margins mean-revert with a commodity cycle (median normalization applies).
_CYCLICAL_ARCHETYPES = {"cyclical-commodity"}
# Without an archetype, treat a name as cyclical only if margin volatility is genuinely high.
_CYCLICALITY_CV_THRESHOLD = 0.5


def _classify_basis(archetype: str | None, midcycle: float, cv: float | None) -> str:
    """Decide whether mid-cycle normalization applies — the fix for non-cyclical names."""
    if midcycle <= 0:
        return "inflection"                          # negative historical median → reversion is meaningless
    if archetype in _CYCLICAL_ARCHETYPES:
        return "cyclical"
    if archetype is not None:
        return "stable"                              # a classified non-cyclical archetype
    return "cyclical" if (cv is not None and cv > _CYCLICALITY_CV_THRESHOLD) else "stable"


def _round(x: float | None, nd: int = 4) -> float | None:
    return round(x, nd) if x is not None else None


async def compute_normalized_earnings(
    db: AsyncSession, ticker: str, archetype: str | None = None
) -> NormalizedEarnings | None:
    ticker = ticker.upper()
    rows = (
        await db.execute(
            select(Financial).where(Financial.ticker == ticker)
            .order_by(Financial.period_end_date.desc()).limit(MAX_QUARTERS)
        )
    ).scalars().all()
    if len(rows) < MIN_QUARTERS:
        return None

    rows = list(reversed(rows))  # oldest → newest
    n = len(rows)
    rev = [r.revenue for r in rows]
    ni = [r.net_income for r in rows]
    oi = [r.operating_income for r in rows]

    ttm_rev = [_ttm(rev, i) for i in range(n)]
    ttm_ni = [_ttm(ni, i) for i in range(n)]
    ttm_oi = [_ttm(oi, i) for i in range(n)]

    net_margins = [m for m in (_safe_div(ttm_ni[i], ttm_rev[i]) for i in range(n)) if m is not None]
    op_margins = [m for m in (_safe_div(ttm_oi[i], ttm_rev[i]) for i in range(n)) if m is not None]
    if len(net_margins) < 4:
        return None

    # Current TTM (latest complete window).
    cur_rev = next((v for v in reversed(ttm_rev) if v is not None), None)
    cur_ni = next((v for v in reversed(ttm_ni) if v is not None), None)
    cur_net_margin = net_margins[-1]
    cur_op_margin = op_margins[-1] if op_margins else None

    mid_net = statistics.median(net_margins)
    mid_op = statistics.median(op_margins) if op_margins else None
    mean_m = statistics.fmean(net_margins)
    std_m = statistics.pstdev(net_margins) if len(net_margins) >= 2 else 0.0
    cv = (std_m / abs(mean_m)) if mean_m else None

    # Does mid-cycle normalization even apply to this name? (The fix: don't treat stable compounders,
    # secular margin expanders, or loss→profit turnarounds as commodity cyclicals.)
    basis = _classify_basis(archetype, mid_net, cv)

    # Cycle position only means something for a genuine cyclical; a pure z-score on a stable name's
    # tiny margin wiggle would spuriously read "peak"/"trough".
    if basis == "cyclical" and std_m > 0:
        z = (cur_net_margin - mean_m) / std_m
        cycle = "peak" if z > 0.75 else "trough" if z < -0.75 else "mid"
    elif basis == "inflection":
        cycle = "inflection"
    else:
        cycle = "stable"

    # Suppress the normalized figures when reversion is invalid (negative historical median margin).
    if basis == "inflection":
        normalized_ni = normalized_factor = None
    else:
        normalized_ni = cur_rev * mid_net if cur_rev is not None else None
        normalized_factor = _safe_div(normalized_ni, cur_ni) if (normalized_ni is not None and cur_ni) else None

    return NormalizedEarnings(
        n_quarters=n,
        basis=basis,
        ttm_revenue=_round(cur_rev, 0),
        ttm_net_income=_round(cur_ni, 0),
        current_net_margin=_round(cur_net_margin),
        current_operating_margin=_round(cur_op_margin),
        midcycle_net_margin=_round(mid_net),
        midcycle_operating_margin=_round(mid_op),
        peak_net_margin=_round(max(net_margins)),
        trough_net_margin=_round(min(net_margins)),
        margin_ratio=_round(_safe_div(cur_net_margin, mid_net), 2),
        cycle_position=cycle,
        normalized_net_income=_round(normalized_ni, 0),
        normalized_factor=_round(normalized_factor, 3),
    )
