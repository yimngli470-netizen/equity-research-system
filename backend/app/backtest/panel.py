"""Point-in-time panel (roadmap 6.3c) — what was knowable on each rebalance date, no lookahead.

The cardinal sin of a backtest is using data that wasn't public yet. Two guards here:
  • FUNDAMENTALS are gated by the exact SEC `filed_date` when the row carries one (M4): a quarter
    becomes "available" the day after its original 10-Q/10-K was filed. Rows without it fall back
    to the v1 blanket lag — `period_end + REPORTING_LAG_DAYS` (a 10-Q files ~40d after quarter-end,
    a 10-K ~60d; 75 calendar days is conservative, biased the safe direction).
  • PRICES use only bars on/before the as-of date; FORWARD returns look strictly after it.

For efficiency each ticker's full price + financial series is loaded ONCE; features for every
rebalance date are then computed in-memory by the pure functions below (no per-date DB round-trips).
Features are RAW here; the evaluator cross-sectionally rank-normalizes them (peer-relative by
construction), so this module carries no absolute-bound calibration.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Financial
from app.models.price import DailyPrice

REPORTING_LAG_DAYS = 75   # conservative blanket lag before a quarter's filing is "public"
_TRADING_DAYS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}


@dataclass
class TickerSeries:
    """A ticker's full history, loaded once and reused across every rebalance date."""
    ticker: str
    dates: list[date]          # price dates, ascending
    closes: list[float]        # raw close, aligned to dates
    adj: list[float]           # adjusted close (for returns), aligned to dates
    financials: list[Financial]  # ascending by period_end_date


async def load_series(db: AsyncSession, ticker: str) -> TickerSeries:
    prows = (
        await db.execute(
            select(DailyPrice.date, DailyPrice.close, DailyPrice.adj_close)
            .where(DailyPrice.ticker == ticker).order_by(DailyPrice.date.asc())
        )
    ).all()
    fins = (
        await db.execute(
            select(Financial).where(Financial.ticker == ticker)
            .order_by(Financial.period_end_date.asc())
        )
    ).scalars().all()
    return TickerSeries(
        ticker=ticker,
        dates=[r[0] for r in prows],
        closes=[float(r[1]) if r[1] is not None else float("nan") for r in prows],
        adj=[float(r[2]) if r[2] is not None else float("nan") for r in prows],
        financials=list(fins),
    )


def _price_idx_asof(s: TickerSeries, asof: date) -> int | None:
    """Index of the last price bar on/before `asof`, or None if none exists."""
    i = bisect_right(s.dates, asof) - 1
    return i if i >= 0 else None


def price_asof(s: TickerSeries, asof: date) -> float | None:
    i = _price_idx_asof(s, asof)
    if i is None:
        return None
    v = s.adj[i]
    return v if v == v else None  # NaN guard


def _available_financials(s: TickerSeries, asof: date) -> list[Financial]:
    """Quarters whose filing would have been public by `asof`, newest-first.

    M4: rows carrying the exact SEC `filed_date` gate on it directly (public the day after filing —
    filings often land after the close). Rows without it (yfinance-sourced, or pre-backfill) fall
    back to the conservative blanket lag."""
    cutoff = asof - timedelta(days=REPORTING_LAG_DAYS)
    avail = [
        f for f in s.financials
        if (f.filed_date < asof if f.filed_date is not None else f.period_end_date <= cutoff)
    ]
    return list(reversed(avail))  # newest first


def _ttm(rows_newest_first: list[Financial], field: str) -> float | None:
    """Trailing-4-quarter sum of a field; None if fewer than 4 quarters or any value missing."""
    if len(rows_newest_first) < 4:
        return None
    vals = [getattr(r, field) for r in rows_newest_first[:4]]
    if any(v is None for v in vals):
        return None
    return sum(vals)


def _volatility(s: TickerSeries, asof: date, window: int = 63) -> float | None:
    """Annualized stdev of daily returns over the trailing `window` bars — the low-vol factor
    input. None when history is too short or too gappy to be meaningful."""
    i = _price_idx_asof(s, asof)
    if i is None or i < window:
        return None
    rets = []
    for j in range(i - window + 1, i + 1):
        a, b = s.adj[j - 1], s.adj[j]
        if a == a and b == b and a > 0:
            rets.append(b / a - 1.0)
    if len(rets) < int(window * 0.8):
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return (var ** 0.5) * (252 ** 0.5)


def _momentum(s: TickerSeries, asof: date) -> dict[str, float | None]:
    i = _price_idx_asof(s, asof)
    out: dict[str, float | None] = {}
    if i is None:
        return {f"mom_{k}": None for k in ("3m", "6m", "12m")}
    cur = s.adj[i]
    for label, lag in (("3m", _TRADING_DAYS["3m"]), ("6m", _TRADING_DAYS["6m"]), ("12m", _TRADING_DAYS["12m"])):
        j = i - lag
        if j >= 0 and cur == cur and s.adj[j] == s.adj[j] and s.adj[j] > 0:
            out[f"mom_{label}"] = cur / s.adj[j] - 1.0
        else:
            out[f"mom_{label}"] = None
    return out


def features_asof(s: TickerSeries, asof: date) -> dict[str, float] | None:
    """Raw point-in-time features for one name on one date. None if too little is knowable.

    Categories mirror the live SCREEN's hard features: growth, profitability, valuation, momentum.
    Valuation metrics are returned as-is (cheap = low P/E); the evaluator inverts them when ranking.
    """
    px = price_asof(s, asof)
    if px is None:
        return None
    avail = _available_financials(s, asof)
    if len(avail) < 8:   # need TTM now + TTM a year ago for growth
        return None

    ttm_rev = _ttm(avail, "revenue")
    ttm_rev_prior = _ttm(avail[4:], "revenue")
    ttm_eps = _ttm(avail, "eps")
    ttm_eps_prior = _ttm(avail[4:], "eps")
    ttm_gp = _ttm(avail, "gross_profit")
    ttm_oi = _ttm(avail, "operating_income")
    ttm_ni = _ttm(avail, "net_income")
    ttm_fcf = _ttm(avail, "free_cash_flow")
    shares = next((f.shares_outstanding for f in avail if f.shares_outstanding), None)

    feats: dict[str, float] = {}

    # Growth
    if ttm_rev and ttm_rev_prior and ttm_rev_prior > 0:
        feats["rev_growth"] = ttm_rev / ttm_rev_prior - 1.0
    if ttm_eps is not None and ttm_eps_prior not in (None, 0) and ttm_eps_prior > 0:
        feats["eps_growth"] = ttm_eps / ttm_eps_prior - 1.0

    # Profitability (margins on TTM revenue)
    if ttm_rev and ttm_rev > 0:
        if ttm_gp is not None:
            feats["gross_margin"] = ttm_gp / ttm_rev
        if ttm_oi is not None:
            feats["op_margin"] = ttm_oi / ttm_rev
        if ttm_ni is not None:
            feats["net_margin"] = ttm_ni / ttm_rev
        if ttm_fcf is not None:
            feats["fcf_margin"] = ttm_fcf / ttm_rev

    # Valuation (market cap from price × shares available at asof)
    mktcap = px * shares if shares else None
    if ttm_eps and ttm_eps > 0:
        feats["pe"] = px / ttm_eps
    if mktcap and ttm_rev and ttm_rev > 0:
        feats["ps"] = mktcap / ttm_rev
    if mktcap and mktcap > 0 and ttm_fcf is not None:
        feats["fcf_yield"] = ttm_fcf / mktcap
    # Earnings yield (E/P) = the robust valuation feature: uses aggregate net income (well-populated)
    # not the sparse per-share `eps` tag, and is DEFINED for negative earnings (ranks low, as it
    # should) where P/E explodes. ~76% coverage vs pe's ~2%.
    if mktcap and mktcap > 0 and ttm_ni is not None:
        feats["earnings_yield"] = ttm_ni / mktcap

    # Momentum
    for k, v in _momentum(s, asof).items():
        if v is not None:
            feats[k] = v

    # Quality (M4 feature expansion) — classic factors, all from EDGAR fields already in the DB.
    # Balance-sheet items are instants: take the NEWEST available quarter that filed the field.
    ttm_ocf = _ttm(avail, "operating_cash_flow")
    equity = next((f.total_equity for f in avail if f.total_equity is not None), None)
    assets = next((f.total_assets for f in avail if f.total_assets is not None), None)
    debt = next((f.total_debt for f in avail if f.total_debt is not None), None)
    if ttm_ni is not None and equity is not None and equity > 0:
        feats["roe"] = ttm_ni / equity          # profitability quality (negative equity → undefined)
    if ttm_ni is not None and ttm_ocf is not None and assets and assets > 0:
        # Sloan accruals: earnings NOT backed by cash, scaled by assets. LOW = high earnings quality.
        feats["accruals"] = (ttm_ni - ttm_ocf) / assets
    if debt is not None and assets and assets > 0:
        # debt/assets, not debt/equity: bounded and defined for buyback-driven negative equity.
        feats["leverage"] = debt / assets

    # Size (log market cap — the small-cap factor input; log because caps span 3 orders of magnitude)
    if mktcap and mktcap > 0:
        feats["size"] = math.log(mktcap)

    # Volatility (trailing 3m realized, annualized — the low-vol anomaly input)
    if (vol := _volatility(s, asof)) is not None:
        feats["vol_3m"] = vol

    return feats or None


def forward_return(s: TickerSeries, asof: date, horizon_days: int) -> float | None:
    """Total return from the bar on/before `asof` to the bar ~horizon_days later. None if unavailable."""
    i = _price_idx_asof(s, asof)
    if i is None:
        return None
    j = i + horizon_days
    if j >= len(s.adj):
        return None
    a, b = s.adj[i], s.adj[j]
    if a == a and b == b and a > 0:
        return b / a - 1.0
    return None
