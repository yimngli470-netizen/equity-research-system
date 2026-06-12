"""Deterministic DCF (roadmap 4.3) — an artifact, not a gesture.

Consumes the forecast model's quarterly net-income path (4.2), converts to FCF via the company's
own HISTORICAL FCF/NI conversion (measured, not assumed), extends years 3-5 by fading growth toward
an archetype-bounded terminal rate, and discounts at the data-built WACC. Same inputs ⇒ identical
fair value; the sensitivity grid is a first-class output so the answer's fragility is visible.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Financial

logger = logging.getLogger(__name__)

# Terminal growth caps per archetype — a cyclical does not compound at GDP+1 forever.
TERMINAL_G = {
    "cyclical-commodity": 0.020,
    "deep-value-turnaround": 0.015,
    "mature-compounder": 0.025,
    "financial": 0.025,
    "secular-grower": 0.030,
    "platform": 0.030,
}
DEFAULT_TERMINAL_G = 0.025
FCF_CONVERSION_BOUNDS = (0.40, 1.20)
FCF_CONVERSION_FALLBACK = 0.85
# Steady state: capex ≈ D&A, so terminal conversion approaches ~0.85. Applying a boom-time
# conversion (heavy build-cycle capex) FOREVER retains earnings into eternity while crediting only
# terminal-g growth for them — internally inconsistent and it annihilates terminal value.
TERMINAL_FCF_CONVERSION = 0.85
EXPLICIT_YEARS = 5  # 2 from the forecast model + 3 faded


@dataclass
class DcfResult:
    fair_value_per_share: float | None
    enterprise_value: float | None
    equity_value: float | None
    fcf_conversion: float
    fcf_years: list[float] = field(default_factory=list)   # explicit-period annual FCF
    ni_years: list[float] = field(default_factory=list)    # the earnings path behind it
    terminal_growth: float = DEFAULT_TERMINAL_G
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "fair_value_per_share": round(self.fair_value_per_share, 2) if self.fair_value_per_share else None,
            "enterprise_value": round(self.enterprise_value, 0) if self.enterprise_value else None,
            "equity_value": round(self.equity_value, 0) if self.equity_value else None,
            "fcf_conversion": round(self.fcf_conversion, 3),
            "fcf_years": [round(f, 0) for f in self.fcf_years],
            "ni_years": [round(n, 0) for n in self.ni_years],
            "terminal_growth": self.terminal_growth,
            "notes": self.notes,
        }


async def historical_fcf_conversion(db: AsyncSession, ticker: str) -> tuple[float, str]:
    """Median FCF/NI over filed history (positive-NI quarters) — measured, clamped, with source."""
    rows = (
        await db.execute(
            select(Financial.free_cash_flow, Financial.net_income)
            .where(Financial.ticker == ticker,
                   Financial.free_cash_flow.is_not(None),
                   Financial.net_income > 0)
            .order_by(Financial.period_end_date.desc())
            .limit(24)
        )
    ).all()
    ratios = sorted(f / n for f, n in rows if n)
    if len(ratios) < 4:
        return FCF_CONVERSION_FALLBACK, "fallback (thin FCF history)"
    med = ratios[len(ratios) // 2]
    lo, hi = FCF_CONVERSION_BOUNDS
    return max(lo, min(hi, med)), f"median of {len(ratios)} quarters"


def run_dcf(
    quarterly_net_income: list[float],   # 8 quarters from the forecast scenario
    fcf_conversion: float,
    wacc: float,
    terminal_growth: float,
    net_debt: float,
    shares: float,
) -> DcfResult:
    """Pure function: forecast NI path → fair value per share."""
    notes: list[str] = []
    if wacc <= terminal_growth + 0.005:
        # Gordon blows up as WACC → g; floor the spread rather than emit a fantasy number.
        wacc = terminal_growth + 0.005
        notes.append("WACC floored to terminal g + 0.5% (Gordon stability)")

    # Earnings path: 2 modeled years, then growth fades into the terminal rate.
    ni_years = [sum(quarterly_net_income[:4]), sum(quarterly_net_income[4:8])]
    growth_exit = (ni_years[1] / ni_years[0] - 1) if ni_years[0] > 0 else terminal_growth
    growth_exit = max(-0.5, min(1.0, growth_exit))
    g = growth_exit
    for i in range(3):
        g = g + (terminal_growth - g) * (i + 1) / 3
        ni_years.append(ni_years[-1] * (1 + g))

    # FCF conversion: measured (boom-time) in year 1, fading linearly to steady state by year 5 —
    # the terminal economics use TERMINAL_FCF_CONVERSION, not the build-cycle capex burden.
    term_conv = (TERMINAL_FCF_CONVERSION if fcf_conversion < TERMINAL_FCF_CONVERSION
                 else min(fcf_conversion, 0.95))
    fcf_years = [
        ni * (fcf_conversion + (term_conv - fcf_conversion) * i / (EXPLICIT_YEARS - 1))
        for i, ni in enumerate(ni_years)
    ]

    pv = sum(f / (1 + wacc) ** (i + 1) for i, f in enumerate(fcf_years))
    tv = fcf_years[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_tv = tv / (1 + wacc) ** EXPLICIT_YEARS
    ev = pv + pv_tv
    equity = ev - net_debt
    fvps = equity / shares if shares else None
    if fvps is not None and fvps < 0:
        notes.append("negative equity value — debt exceeds DCF enterprise value")
        fvps = 0.0
    return DcfResult(fair_value_per_share=fvps, enterprise_value=ev, equity_value=equity,
                     fcf_conversion=fcf_conversion, fcf_years=fcf_years, ni_years=ni_years,
                     terminal_growth=terminal_growth, notes=notes)


def sensitivity_grid(
    quarterly_net_income: list[float], fcf_conversion: float, wacc: float,
    terminal_growth: float, net_debt: float, shares: float,
) -> dict:
    """Fair value at WACC ±1% × terminal g ±0.5% — the answer's fragility, visible."""
    grid: dict[str, dict[str, float | None]] = {}
    for dw in (-0.01, 0.0, 0.01):
        row = {}
        for dg in (-0.005, 0.0, 0.005):
            r = run_dcf(quarterly_net_income, fcf_conversion, wacc + dw,
                        terminal_growth + dg, net_debt, shares)
            row[f"g{terminal_growth + dg:+.3f}"] = (
                round(r.fair_value_per_share, 2) if r.fair_value_per_share is not None else None)
        grid[f"wacc{wacc + dw:+.3f}"] = row
    return grid
