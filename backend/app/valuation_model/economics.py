"""Versioned valuation policies conditioned on economics, never on ticker names.

Policy coefficients are declared expert priors, not empirically calibrated probabilities.
Size affects comparability only; it cannot grant a growth premium or change growth duration.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date

from app.forecast.model import _add_months

MODEL_VERSION = "economics-2026-09-20.3"


def number(value) -> float | None:
    return float(value) if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) else None


def window_total(quarters: list[dict], start: date, end: date, key: str) -> float | None:
    """Calendar-aligned sum. Partial quarters are prorated, never extrapolated.

    The caller must disclose that modeled quarter-end dates and intra-quarter accrual are approximate.
    Missing periods/values fail closed; they must not be read as zero earnings.
    """
    if end <= start or not quarters:
        return None
    rows = sorted(quarters, key=lambda q: q["end_approx"])
    prev = _add_months(date.fromisoformat(rows[0]["end_approx"]), -3)
    covered, total = 0, 0.0
    for q in rows:
        stop = date.fromisoformat(q["end_approx"])
        if stop <= prev or not 75 <= (stop - prev).days <= 100:
            return None
        days = max(0, (min(stop, end) - max(prev, start)).days)
        if days:
            v = number(q.get(key))
            if v is None:
                return None
            total += v * days / (stop - prev).days
            covered += days
        prev = stop
    return total if covered == (end - start).days else None


@dataclass(frozen=True)
class Economics:
    ticker: str
    industry: str | None
    sector: str | None
    archetype: str | None
    revenue_growth: float
    operating_margin: float
    market_cap: float | None = None
    debt_to_equity_value: float = 0.0


@dataclass(frozen=True)
class ValuationPolicy:
    maturity_year: int
    terminal_growth: float
    dcf_weight: float
    rationale: str
    source: str = "declared policy conditioned on forecast economics"

    def to_dict(self):
        return asdict(self)


def select_policy(e: Economics) -> ValuationPolicy:
    if e.archetype == "financial":
        raise ValueError("Financial businesses require an equity-capital/distribution model")
    if e.archetype == "cyclical-commodity":
        return ValuationPolicy(5, .02, .25, "Cyclical: normalized earning power is primary; explicit cycle cash flows are secondary")
    g = max(-.5, min(.6, e.revenue_growth))
    if e.operating_margin <= 0 or e.archetype == "deep-value-turnaround":
        return ValuationPolicy(6, .02, 1.0, "Transition: cash-generation path required; no P/E on losses")
    # Growth duration varies even within the same archetype. Large market cap grants no premium.
    maturity = max(5, min(10, 5 + round(max(0, g - .05) * 15)))
    fast = g >= .15
    weight = .4 if fast else .65
    if e.archetype == "platform":
        weight = .5 if fast else .65
    return ValuationPolicy(maturity, .03 if fast else .025, weight,
                           f"Forecast revenue growth {g:.1%}, operating margin {e.operating_margin:.1%}: "
                           f"mature growth reached in year {maturity}; "
                           + ("forward earnings emphasized, with reinvestment-sensitive DCF" if fast
                              else "sustainable cash generation emphasized"))


def forecast_economics(stock, projection: dict, as_of: date, market_cap=None, debt=0) -> Economics | None:
    q = projection.get("quarters") or []
    y1, y2 = _add_months(as_of, 12), _add_months(as_of, 24)
    r1, r2 = window_total(q, as_of, y1, "revenue"), window_total(q, y1, y2, "revenue")
    oi = window_total(q, y1, y2, "operating_income")
    if r1 is None or r2 is None or oi is None or r1 <= 0 or r2 <= 0:
        return None
    return Economics(stock.ticker, stock.industry, stock.sector, stock.archetype,
                     r2 / r1 - 1, oi / r2, market_cap,
                     max(0, debt / market_cap) if market_cap and debt else 0)


def comparable_weight(subject: Economics, peer: Economics, measured_weight: float = 0) -> float:
    """Economic eligibility precedes distance. Unrelated universe names receive zero weight."""
    if subject.ticker == peer.ticker:
        return 0
    cyclical = lambda e: e.archetype == "cyclical-commodity"
    if cyclical(subject) != cyclical(peer) or peer.archetype == "financial":
        return 0
    same_industry = bool(subject.industry and subject.industry == peer.industry)
    # Broad labels such as "Technology / secular-grower" do not make an ad platform and
    # a chip designer economic peers. Require an actual industry match before weighting.
    if not same_industry or peer.operating_margin <= 0:
        return 0
    distance = (abs(subject.revenue_growth - peer.revenue_growth) / .20
                + abs(subject.operating_margin - peer.operating_margin) / .20
                + abs(subject.debt_to_equity_value - peer.debt_to_equity_value))
    economic = 1 / (1 + distance)
    # Size is a small, symmetric matching penalty, with no direction-dependent premium.
    size = 1.0
    if subject.market_cap and peer.market_cap and min(subject.market_cap, peer.market_cap) > 0:
        size = 1 / (1 + .1 * abs(math.log(subject.market_cap / peer.market_cap)))
    return (.8 * economic + .2 * max(0, min(1, measured_weight))) * size


def weighted_median(values: list[tuple[float, float]]) -> float | None:
    xs = sorted((v, w) for v, w in values if number(v) is not None and number(w) is not None and w > 0)
    total = sum(w for _, w in xs)
    cumulative = 0.0
    for v, w in xs:
        cumulative += w
        if cumulative >= total / 2:
            return v
    return None


def adjusted_multiple(anchor: float, subject: Economics, peer_growth: float, peer_margin: float) -> tuple[float, float]:
    """Bounded, explicit prior for growth/profitability differences INCLUDING the base scenario."""
    factor = max(.75, min(1.25, 1 + .75 * (subject.revenue_growth - peer_growth)
                           + .5 * (subject.operating_margin - peer_margin)))
    return anchor * factor, factor
