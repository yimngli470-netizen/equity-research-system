"""Quant profile — measurable business-model signals derived from the EDGAR financials spine.

This is the *grounding* input for archetype classification (roadmap 1.1). The archetype LABEL is
an LLM judgment, but it must be grounded on numbers, not guessed from a ticker — so we compute a
small, robust profile here first and feed it to the model. The same profile feeds peer-similarity
(1.2) and archetype clustering (ML M2).

All figures are computed on a trailing-twelve-month (TTM) basis where seasonality would otherwise
distort the signal (margins, growth, cyclicality), so a Q4-heavy retailer and a flat SaaS name are
compared on like terms. Pure statistics — no LLM, no network.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Financial

# How many of the most recent quarters to profile over. ~8yr — long enough to span a full
# semiconductor / commodity cycle, short enough that a decade-old business model doesn't dominate.
MAX_QUARTERS = 32
# Minimum quarters required to say anything; below this the profile is too thin to ground a label.
MIN_QUARTERS = 6


@dataclass
class QuantProfile:
    """Business-model fingerprint. Every field is a ratio/fraction unless noted (_pct = 0..1)."""

    n_quarters: int

    # Growth & cyclicality (TTM YoY) — the cyclical-vs-secular discriminators.
    revenue_growth_mean: float | None = None   # avg TTM YoY revenue growth
    revenue_growth_std: float | None = None    # volatility of that growth → cyclicality
    revenue_growth_min: float | None = None    # worst TTM YoY contraction
    revenue_max_drawdown: float | None = None  # peak-to-trough decline in TTM revenue (0..1)

    # Profitability level & stability (TTM).
    gross_margin_mean: float | None = None
    gross_margin_std: float | None = None
    operating_margin_mean: float | None = None
    operating_margin_std: float | None = None
    net_margin_mean: float | None = None
    loss_quarter_pct: float | None = None      # fraction of quarters with negative net income

    # Capital model.
    capex_intensity_mean: float | None = None  # (OCF - FCF) / revenue, TTM — asset-heaviness

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _stats(xs: list[float]) -> tuple[float | None, float | None, float | None]:
    """(mean, sample-stdev, min) for a list, tolerant of short lists."""
    if not xs:
        return None, None, None
    mean = statistics.fmean(xs)
    std = statistics.stdev(xs) if len(xs) >= 2 else 0.0
    return mean, std, min(xs)


def _ttm(series: list[float | None], i: int) -> float | None:
    """Trailing-4-quarter sum ending at index i (inclusive). None if any quarter missing."""
    if i < 3:
        return None
    window = series[i - 3 : i + 1]
    if any(v is None for v in window):
        return None
    return sum(window)  # type: ignore[arg-type]


async def compute_quant_profile(db: AsyncSession, ticker: str) -> QuantProfile | None:
    """Compute the quant profile for a ticker from its stored quarterly financials.

    Returns None when there's too little history to be meaningful (< MIN_QUARTERS).
    """
    ticker = ticker.upper()
    rows = (
        await db.execute(
            select(Financial)
            .where(Financial.ticker == ticker)
            .order_by(Financial.period_end_date.desc())
            .limit(MAX_QUARTERS)
        )
    ).scalars().all()

    if len(rows) < MIN_QUARTERS:
        return None

    # Oldest → newest so YoY (t vs t-4) and drawdowns read forward in time.
    rows = list(reversed(rows))
    n = len(rows)

    rev = [r.revenue for r in rows]
    gp = [r.gross_profit for r in rows]
    oi = [r.operating_income for r in rows]
    ni = [r.net_income for r in rows]
    ocf = [r.operating_cash_flow for r in rows]
    fcf = [r.free_cash_flow for r in rows]

    # TTM series (None where a 4Q window is incomplete).
    ttm_rev = [_ttm(rev, i) for i in range(n)]
    ttm_gp = [_ttm(gp, i) for i in range(n)]
    ttm_oi = [_ttm(oi, i) for i in range(n)]
    ttm_ni = [_ttm(ni, i) for i in range(n)]
    ttm_ocf = [_ttm(ocf, i) for i in range(n)]
    ttm_fcf = [_ttm(fcf, i) for i in range(n)]

    # TTM YoY revenue growth: ttm[i] vs ttm[i-4].
    growth: list[float] = []
    for i in range(4, n):
        cur, prior = ttm_rev[i], ttm_rev[i - 4]
        if cur is not None and prior is not None and prior > 0:
            growth.append(cur / prior - 1.0)
    g_mean, g_std, g_min = _stats(growth)

    # Peak-to-trough drawdown of TTM revenue (cyclicality).
    max_dd: float | None = None
    peak = None
    for v in ttm_rev:
        if v is None:
            continue
        if peak is None or v > peak:
            peak = v
        if peak and peak > 0:
            dd = (peak - v) / peak
            max_dd = dd if max_dd is None else max(max_dd, dd)

    # TTM margins (level + stability).
    gm = [m for m in (_safe_div(ttm_gp[i], ttm_rev[i]) for i in range(n)) if m is not None]
    om = [m for m in (_safe_div(ttm_oi[i], ttm_rev[i]) for i in range(n)) if m is not None]
    nm = [m for m in (_safe_div(ttm_ni[i], ttm_rev[i]) for i in range(n)) if m is not None]
    gm_mean, gm_std, _ = _stats(gm)
    om_mean, om_std, _ = _stats(om)
    nm_mean, _, _ = _stats(nm)

    # Loss quarters (on raw quarterly net income — captures any single bad quarter).
    ni_present = [v for v in ni if v is not None]
    loss_pct = (
        sum(1 for v in ni_present if v < 0) / len(ni_present) if ni_present else None
    )

    # Capex intensity: (OCF - FCF) / revenue, TTM. OCF - FCF ≈ capex (+ a small tail of other
    # investing flows depending on the FCF definition) — good enough to rank asset-heaviness.
    capex_int = []
    for i in range(n):
        if ttm_ocf[i] is not None and ttm_fcf[i] is not None and ttm_rev[i]:
            capex_int.append((ttm_ocf[i] - ttm_fcf[i]) / ttm_rev[i])
    capex_mean, _, _ = _stats(capex_int)

    def _r(x: float | None, nd: int = 4) -> float | None:
        return round(x, nd) if x is not None else None

    return QuantProfile(
        n_quarters=n,
        revenue_growth_mean=_r(g_mean),
        revenue_growth_std=_r(g_std),
        revenue_growth_min=_r(g_min),
        revenue_max_drawdown=_r(max_dd),
        gross_margin_mean=_r(gm_mean),
        gross_margin_std=_r(gm_std),
        operating_margin_mean=_r(om_mean),
        operating_margin_std=_r(om_std),
        net_margin_mean=_r(nm_mean),
        loss_quarter_pct=_r(loss_pct),
        capex_intensity_mean=_r(capex_mean),
    )
