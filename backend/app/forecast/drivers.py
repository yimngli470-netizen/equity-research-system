"""Driver history (roadmap 4.2) — the deterministic substrate the forecast model is built on.

Pure arithmetic over the EDGAR `financials` spine (no LLM): per-quarter driver series (revenue YoY,
gross margin, opex ratio, below-operating net factor, diluted shares, SBC intensity) plus
through-cycle medians — the medians are the reversion ANCHOR fed to the assumptions prompt
(M3b's hand-built precursor: the LLM must justify deviating from them, not invent its own base rate).
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Financial

logger = logging.getLogger(__name__)

MIN_QUARTERS = 6  # below this, a driver-based forecast is not honest


@dataclass
class DriverQuarter:
    period: str
    end: date
    revenue: float | None
    revenue_yoy: float | None        # vs the quarter 4 back (fraction)
    gross_margin: float | None       # fraction
    opex_ratio: float | None         # (gross_profit − operating_income) / revenue
    net_factor: float | None         # net_income / operating_income (taxes + below-the-line)
    eps: float | None
    shares: float | None             # diluted shares outstanding
    sbc_pct: float | None            # SBC / revenue


@dataclass
class DriverHistory:
    ticker: str
    quarters: list[DriverQuarter] = field(default_factory=list)  # chronological (oldest → newest)
    medians: dict = field(default_factory=dict)                  # through-cycle anchors

    @property
    def latest(self) -> DriverQuarter:
        return self.quarters[-1]

    def last_n(self, n: int) -> list[DriverQuarter]:
        return self.quarters[-n:]


def _ratio(a: float | None, b: float | None) -> float | None:
    if a is None or not b:
        return None
    return a / b


def _median(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


async def build_driver_history(db: AsyncSession, ticker: str, lookback: int = 24) -> DriverHistory | None:
    """Build the chronological driver series. None if the history is too thin to model."""
    rows = (
        await db.execute(
            select(Financial)
            .where(Financial.ticker == ticker.upper(), Financial.revenue.is_not(None))
            .order_by(Financial.period_end_date.desc())
            .limit(lookback)
        )
    ).scalars().all()
    rows = list(reversed(rows))  # chronological
    if len(rows) < MIN_QUARTERS:
        return None

    by_idx: list[DriverQuarter] = []
    for i, r in enumerate(rows):
        yoy = None
        if i >= 4 and rows[i - 4].revenue:
            yoy = r.revenue / rows[i - 4].revenue - 1
        oi, ni = r.operating_income, r.net_income
        net_factor = (ni / oi) if (oi and oi > 0 and ni is not None) else None
        by_idx.append(DriverQuarter(
            period=r.period,
            end=r.period_end_date,
            revenue=r.revenue,
            revenue_yoy=round(yoy, 4) if yoy is not None else None,
            gross_margin=round(_ratio(r.gross_profit, r.revenue), 4) if _ratio(r.gross_profit, r.revenue) is not None else None,
            opex_ratio=round(_ratio((r.gross_profit - oi) if (r.gross_profit is not None and oi is not None) else None, r.revenue), 4)
            if (r.gross_profit is not None and oi is not None and r.revenue) else None,
            net_factor=round(net_factor, 4) if net_factor is not None else None,
            eps=r.eps,
            shares=r.shares_outstanding,
            sbc_pct=round(_ratio(r.stock_based_comp, r.revenue), 4) if _ratio(r.stock_based_comp, r.revenue) is not None else None,
        ))

    hist = DriverHistory(ticker=ticker.upper(), quarters=by_idx)
    hist.medians = {
        "gross_margin": _median([q.gross_margin for q in by_idx]),
        "opex_ratio": _median([q.opex_ratio for q in by_idx]),
        "net_factor": _median([q.net_factor for q in by_idx]),
        "revenue_yoy": _median([q.revenue_yoy for q in by_idx]),
        "sbc_pct": _median([q.sbc_pct for q in by_idx]),
    }
    return hist


def format_drivers_for_llm(h: DriverHistory) -> str:
    """A compact driver table + the through-cycle anchors, for the assumptions prompt."""
    lines = ["--- DRIVER HISTORY (EDGAR-derived; chronological) ---",
             "period | revenue | rev YoY | gross margin | opex ratio | net factor | EPS | dil. shares"]
    for q in h.last_n(12):
        def f(v, pct=False, money=False, big=False):
            if v is None:
                return "n/a"
            if money:
                return f"${v / 1e9:.2f}B"
            if big:
                return f"{v / 1e9:.3f}B"
            return f"{v:+.1%}" if pct else f"{v:.3f}"
        lines.append(
            f"{q.period} | {f(q.revenue, money=True)} | {f(q.revenue_yoy, pct=True)} | "
            f"{f(q.gross_margin)} | {f(q.opex_ratio)} | {f(q.net_factor)} | "
            f"{('$' + format(q.eps, '.2f')) if q.eps is not None else 'n/a'} | {f(q.shares, big=True)}"
        )
    m = h.medians
    lines.append("")
    lines.append("--- THROUGH-CYCLE MEDIANS (your reversion anchor — justify any deviation) ---")
    lines.append(
        f"gross margin {m['gross_margin']:.3f} | opex ratio {m['opex_ratio']:.3f} | "
        f"net factor {m['net_factor']:.3f} | revenue YoY {m['revenue_yoy']:+.1%}"
        if all(m.get(k) is not None for k in ("gross_margin", "opex_ratio", "net_factor", "revenue_yoy"))
        else f"medians (partial): {m}"
    )
    return "\n".join(lines)
