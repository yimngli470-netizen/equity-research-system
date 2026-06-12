"""WACC built from data, not vibes (roadmap 4.3).

Every component is measured or a declared constant — never LLM-emitted:
- risk-free: the 10Y Treasury yield (^TNX via yfinance; declared fallback when unreachable)
- beta: OUR regression of the ticker's weekly returns on SPY's (both already in daily_prices)
- ERP: a declared constant (5.0%) — the one genuinely irreducible assumption, stated openly
- cost of debt: rf + a fixed spread, after-tax; weights from the actual capital structure (4.1's
  total_debt vs market cap)
"""

import asyncio
import logging
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price import DailyPrice

logger = logging.getLogger(__name__)

EQUITY_RISK_PREMIUM = 0.05
DEBT_SPREAD = 0.015
TAX_RATE = 0.21
RISK_FREE_FALLBACK = 0.042
# Raw regression betas on momentum-y price series measure the runup, not systematic risk.
# Blume-adjust toward 1 (the standard mean-reversion correction), THEN clamp.
BLUME_WEIGHT = 0.67
BETA_BOUNDS = (0.8, 2.0)
BENCHMARK = "SPY"


@dataclass
class WaccInputs:
    risk_free: float
    beta: float
    erp: float
    cost_of_equity: float
    cost_of_debt_after_tax: float
    equity_weight: float
    wacc: float
    beta_source: str  # "regression" | "fallback"
    risk_free_source: str  # "^TNX" | "fallback"

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def _fetch_risk_free() -> float | None:
    """Latest 10Y Treasury yield from yfinance (^TNX quotes in percent)."""
    import yfinance as yf
    h = yf.Ticker("^TNX").history(period="5d")
    if h is None or h.empty:
        return None
    v = float(h["Close"].iloc[-1]) / 100.0
    return v if 0.0 < v < 0.15 else None


async def compute_beta(db: AsyncSession, ticker: str, weeks: int = 104) -> float | None:
    """OLS slope of the ticker's weekly returns on SPY's, from our own price history."""
    async def closes(t: str) -> dict:
        rows = (
            await db.execute(
                select(DailyPrice.date, DailyPrice.close)
                .where(DailyPrice.ticker == t)
                .order_by(DailyPrice.date.desc())
                .limit(weeks * 5 + 10)
            )
        ).all()
        return {d: c for d, c in rows}

    own, spy = await closes(ticker), await closes(BENCHMARK)
    common = sorted(set(own) & set(spy))
    if len(common) < 60:
        return None
    # weekly sampling (every 5th common trading day)
    samples = common[::5]
    r_own, r_spy = [], []
    for a, b in zip(samples, samples[1:]):
        if own[a] and spy[a]:
            r_own.append(own[b] / own[a] - 1)
            r_spy.append(spy[b] / spy[a] - 1)
    if len(r_spy) < 30:
        return None
    mean_o, mean_s = sum(r_own) / len(r_own), sum(r_spy) / len(r_spy)
    var_s = sum((x - mean_s) ** 2 for x in r_spy)
    if var_s == 0:
        return None
    cov = sum((x - mean_s) * (y - mean_o) for x, y in zip(r_spy, r_own))
    return cov / var_s


async def build_wacc(db: AsyncSession, ticker: str,
                     market_cap: float | None, total_debt: float | None) -> WaccInputs:
    try:
        rf = await asyncio.to_thread(_fetch_risk_free)
    except Exception:
        rf = None
    rf_source = "^TNX" if rf is not None else "fallback"
    rf = rf if rf is not None else RISK_FREE_FALLBACK

    beta_raw = await compute_beta(db, ticker)
    beta_source = "regression(Blume-adj)" if beta_raw is not None else "fallback"
    if beta_raw is not None:
        beta = BLUME_WEIGHT * beta_raw + (1 - BLUME_WEIGHT) * 1.0
        beta = max(BETA_BOUNDS[0], min(BETA_BOUNDS[1], beta))
    else:
        beta = 1.0

    coe = rf + beta * EQUITY_RISK_PREMIUM
    cod = (rf + DEBT_SPREAD) * (1 - TAX_RATE)
    if market_cap and total_debt and market_cap > 0:
        ew = market_cap / (market_cap + total_debt)
    else:
        ew = 1.0
    wacc = ew * coe + (1 - ew) * cod
    return WaccInputs(risk_free=rf, beta=beta, erp=EQUITY_RISK_PREMIUM, cost_of_equity=coe,
                      cost_of_debt_after_tax=cod, equity_weight=ew, wacc=wacc,
                      beta_source=beta_source, risk_free_source=rf_source)
