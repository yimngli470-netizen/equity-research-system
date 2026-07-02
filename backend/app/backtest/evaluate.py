"""Walk-forward rank-IC evaluator (roadmap 6.3d) — does the screen rank-order forward returns?

At each rebalance date: score the universe with the deterministic screen (point-in-time), then
measure the Spearman rank correlation (the "information coefficient", IC) between that score and each
name's FORWARD excess return vs SPY over the horizon. Walking forward gives an IC time series, whose
mean / t-stat / hit-rate / decile spread are the screen's evidence of edge.

Standard factor methodology. One caveat surfaced honestly in the report: when the rebalance interval
is shorter than the horizon, forward windows overlap and the IC t-stat is optimistic — so the default
rebalances at roughly the horizon length (near-non-overlapping).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.panel import TickerSeries, features_asof, forward_return, load_series
from app.backtest.screen import score_cross_section

logger = logging.getLogger(__name__)

BENCHMARK = "SPY"
MIN_NAMES = 30          # cross-section must be at least this wide to rank meaningfully
DECILE_MIN = 50         # need this many names before a top/bottom-decile spread is reported


def _rank(xs: list[float]) -> list[float]:
    """Average-tie ranks (1..n) — for Spearman via Pearson-on-ranks."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va == 0 or vb == 0:
        return None
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / (va ** 0.5 * vb ** 0.5)


def _spearman(a: list[float], b: list[float]) -> float | None:
    return _pearson(_rank(a), _rank(b))


def _first_idx_on_or_after(dates: list[date], d: date) -> int:
    from bisect import bisect_left
    return bisect_left(dates, d)


def _last_idx_on_or_before(dates: list[date], d: date) -> int:
    from bisect import bisect_right
    return bisect_right(dates, d) - 1


@dataclass
class BacktestResult:
    params: dict
    metrics: dict
    ic_series: list[dict] = field(default_factory=list)
    notes: str = ""


async def run_backtest(
    db: AsyncSession,
    tickers: list[str],
    *,
    horizon_days: int = 63,        # ~3 trading months
    rebalance_days: int = 63,      # ~quarterly → near-non-overlapping windows
    start: date | None = None,
    end: date | None = None,
    label: str | None = None,
    membership: dict | None = None,  # app.universe.history snapshot → point-in-time universe gate
) -> BacktestResult:
    """Walk-forward rank-IC of the deterministic screen vs forward excess return.

    With `membership` (the M4 stage-1 history snapshot), a name enters the cross-section on a date
    only if it was an index member ON that date — killing both survivorship bias (removed names
    stay in for the dates they were members) and its mirror (recent joiners no longer appear in
    years before they made the index). Without it, the pre-M4 behaviour: `tickers` on every date.
    """
    # Load every series once (prices + financials), including the benchmark.
    series: dict[str, TickerSeries] = {}
    for t in {*[t.upper() for t in tickers], BENCHMARK}:
        series[t] = await load_series(db, t)
    spy = series[BENCHMARK]
    if not spy.dates:
        raise RuntimeError("no SPY benchmark prices — run benchmark ingest first")

    # Rebalance on the BENCHMARK's trading calendar, stepping by `rebalance_days` index positions —
    # so rebalance + horizon are both in trading-day units (no calendar/trading mismatch). The window
    # starts after ~1y of history (momentum needs it) and ends a horizon before the last bar.
    px_dates = spy.dates  # ascending
    start_idx = 252 if start is None else max(0, _first_idx_on_or_after(px_dates, start))
    end_idx = len(px_dates) - horizon_days - 1
    if end is not None:
        end_idx = min(end_idx, _last_idx_on_or_before(px_dates, end))
    rb = [px_dates[i] for i in range(start_idx, end_idx + 1, rebalance_days)]
    start = rb[0] if rb else px_dates[start_idx]
    end = rb[-1] if rb else px_dates[max(start_idx, end_idx)]

    names = [t.upper() for t in tickers if t.upper() != BENCHMARK]
    ic_series: list[dict] = []
    spreads: list[float] = []
    coverage: list[int] = []

    for t in rb:
        if membership is not None:
            from app.universe.history import constituents_asof
            active = set(constituents_asof(t, membership))
            cross = [n for n in names if n in active]
        else:
            cross = names
        feats = {n: f for n in cross if (f := features_asof(series[n], t)) is not None}
        if len(feats) < MIN_NAMES:
            continue
        composite = score_cross_section(feats)
        spy_fwd = forward_return(spy, t, horizon_days)
        if spy_fwd is None:
            continue

        scores, excess = [], []
        for n, sc in composite.items():
            fr = forward_return(series[n], t, horizon_days)
            if fr is None:
                continue
            scores.append(sc)
            excess.append(fr - spy_fwd)   # forward EXCESS return vs SPY
        if len(scores) < MIN_NAMES:
            continue

        ic = _spearman(scores, excess)
        if ic is None:
            continue
        row = {"date": t.isoformat(), "ic": round(ic, 4), "n": len(scores)}

        # Top-minus-bottom decile spread on excess returns (when wide enough).
        if len(scores) >= DECILE_MIN:
            paired = sorted(zip(scores, excess), key=lambda p: p[0])
            k = max(1, len(paired) // 10)
            bot = sum(e for _, e in paired[:k]) / k
            top = sum(e for _, e in paired[-k:]) / k
            row["decile_spread"] = round(top - bot, 4)
            spreads.append(top - bot)

        ic_series.append(row)
        coverage.append(len(scores))

    metrics = _aggregate(ic_series, spreads, coverage, horizon_days)
    notes = (
        f"Point-in-time via exact SEC filed_date where present, else {_lag()}d reporting lag. "
        + ("Universe = POINT-IN-TIME S&P membership (M4): names enter only on dates they were members; "
           "residual bias = delisted names whose price history free sources no longer serve. "
           if membership is not None else
           "Universe = CURRENT index constituents (survivorship bias: dropped/delisted names absent). ")
        + "Validates the DETERMINISTIC hard-feature screen only; the LLM layer is excluded by design. "
        + ("Rebalance ≈ horizon ⇒ near-non-overlapping windows." if rebalance_days >= horizon_days
           else "Rebalance < horizon ⇒ OVERLAPPING windows; IC t-stat is optimistic.")
    )
    params = {
        "horizon_days": horizon_days, "rebalance_days": rebalance_days,
        "start": start.isoformat(), "end": end.isoformat(),
        "n_names": len(names), "reporting_lag_days": _lag(),
        "universe": "point-in-time" if membership is not None else "current-snapshot",
        "benchmark": BENCHMARK, "weighting": "hard-category, percentile-rank",
        "label": label,
    }
    return BacktestResult(params=params, metrics=metrics, ic_series=ic_series, notes=notes)


def _lag() -> int:
    from app.backtest.panel import REPORTING_LAG_DAYS
    return REPORTING_LAG_DAYS


def _aggregate(ic_series: list[dict], spreads: list[float], coverage: list[int], horizon_days: int) -> dict:
    ics = [r["ic"] for r in ic_series]
    n = len(ics)
    if n == 0:
        return {"n_periods": 0}
    mean_ic = sum(ics) / n
    std_ic = (sum((x - mean_ic) ** 2 for x in ics) / (n - 1)) ** 0.5 if n > 1 else 0.0
    t_stat = (mean_ic / std_ic * (n ** 0.5)) if std_ic > 0 else None
    hit = sum(1 for x in ics if x > 0) / n
    periods_per_year = 252 / horizon_days
    return {
        "n_periods": n,
        "mean_ic": round(mean_ic, 4),
        "ic_std": round(std_ic, 4),
        "ic_t_stat": round(t_stat, 2) if t_stat is not None else None,
        "ic_hit_rate": round(hit, 3),
        "mean_decile_spread": round(sum(spreads) / len(spreads), 4) if spreads else None,
        "decile_spread_annualized": round(sum(spreads) / len(spreads) * periods_per_year, 4) if spreads else None,
        "mean_names": round(sum(coverage) / len(coverage)) if coverage else 0,
    }
