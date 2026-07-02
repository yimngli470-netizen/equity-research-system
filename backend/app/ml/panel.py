"""M5 panel assembly — turn the point-in-time backtest features/labels into a flat (X, y) table.

This reuses `app.backtest.panel` (the SAME point-in-time feature + forward-return functions the
hand-screen backtest uses), so the ML panel is assembled IDENTICALLY to the +0.0174 baseline: same
rebalance dates, same universe, same 75-day reporting-lag gating, same label (forward EXCESS return
vs SPY). The only difference from the backtest is that we KEEP the raw per-(ticker, date) rows
instead of collapsing them into one IC per date.

No lookahead by construction — see the `app.backtest.panel` docstring for the two guards (reporting
lag on fundamentals; forward window strictly after the as-of date).

Output: a pandas DataFrame, one row per (ticker, rebalance_date):
    ticker · date · <12 raw features> · y_fwd_excess_vs_spy
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.evaluate import BENCHMARK
from app.backtest.panel import TickerSeries, features_asof, forward_return, load_series

# The ML feature set. Drops `pe` (2% coverage) and `eps_growth` (0.7%) — both depend on EDGAR's
# sparse per-share `eps` tag — and adds `earnings_yield` (E/P, ~76% coverage) as the robust
# valuation replacement (see Stage 1 coverage inspection).
FEATURE_COLS: list[str] = [
    "rev_growth",                                              # growth
    "gross_margin", "op_margin", "net_margin", "fcf_margin",  # profitability
    "ps", "fcf_yield", "earnings_yield",                      # valuation
    "mom_3m", "mom_6m", "mom_12m",                            # momentum
]
LABEL_COL = "y_fwd_excess_vs_spy"


def _rebalance_dates(spy: TickerSeries, horizon_days: int, rebalance_days: int) -> list[date]:
    """Same calendar the evaluator uses: SPY trading days, start after ~1y (momentum needs it),
    end a horizon before the last bar, stepping by `rebalance_days`."""
    px = spy.dates
    start_idx = 252
    end_idx = len(px) - horizon_days - 1
    return [px[i] for i in range(start_idx, end_idx + 1, rebalance_days)]


async def build_panel(
    db: AsyncSession,
    tickers: list[str],
    *,
    horizon_days: int = 63,
    rebalance_days: int = 63,
    membership: dict | None = None,  # M4: point-in-time membership gate (see run_backtest)
) -> pd.DataFrame:
    """Assemble the flat (X, y) panel. Mirrors `app.backtest.evaluate.run_backtest` row-for-row,
    but emits the raw (ticker, date) observations rather than per-date ICs."""
    series: dict[str, TickerSeries] = {}
    for t in {*[x.upper() for x in tickers], BENCHMARK}:
        series[t] = await load_series(db, t)
    spy = series[BENCHMARK]
    if not spy.dates:
        raise RuntimeError("no SPY benchmark prices — run benchmark ingest first")

    rb = _rebalance_dates(spy, horizon_days, rebalance_days)
    names = [t.upper() for t in tickers if t.upper() != BENCHMARK]

    rows: list[dict] = []
    for t in rb:
        spy_fwd = forward_return(spy, t, horizon_days)
        if spy_fwd is None:
            continue
        if membership is not None:
            from app.universe.history import constituents_asof
            active = set(constituents_asof(t, membership))
            cross = [n for n in names if n in active]
        else:
            cross = names
        for n in cross:
            feats = features_asof(series[n], t)
            if feats is None:
                continue
            fr = forward_return(series[n], t, horizon_days)
            if fr is None:
                continue
            rows.append({"ticker": n, "date": t.isoformat(), **feats, LABEL_COL: fr - spy_fwd})

    return pd.DataFrame(rows)
