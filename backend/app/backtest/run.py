"""Backtest CLI (roadmap 6.3e) — `python -m app.backtest.run`.

The offline entry point: assemble the universe, walk the screen forward, persist the run to
`backtest_runs`, and print a markdown report. NOT wired into the app — this is the evaluation
harness, run on demand (and re-run as a monitor to watch whether the edge decays).

    python -m app.backtest.run                       # defaults: 3m horizon, quarterly rebalance
    python -m app.backtest.run --horizon 126 --rebalance 126 --label "6m"
    python -m app.backtest.run --no-save             # don't persist, just print
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.backtest.evaluate import BacktestResult, run_backtest
from app.database import async_session
from app.models.backtest import BacktestRun

logging.disable(logging.WARNING)


async def _universe_tickers(membership: dict | None = None) -> list[str]:
    """Screening universe. Point-in-time (M4): every name that was an S&P member at ANY point in
    the window ∪ whatever's in `stocks` (the per-DATE membership gate is applied downstream by the
    evaluator). Legacy: committed SPX+NDX snapshot ∪ `stocks`."""
    from datetime import date

    from sqlalchemy import select

    from app.models.stock import Stock
    from app.universe.constituents import load_universe
    names: set[str] = set()
    if membership is not None:
        from app.universe.history import all_members_between
        names |= set(all_members_between(date(2016, 1, 1), date.today(), membership))
    else:
        try:
            names |= set(load_universe())
        except Exception:
            pass
    async with async_session() as db:
        names |= {r[0] for r in (await db.execute(select(Stock.ticker))).all()}
    names.discard("SPY")
    return sorted(names)


def _report(r: BacktestResult) -> str:
    p, m = r.params, r.metrics
    L = ["# Screen backtest — rank-IC\n"]
    L.append(f"*{p['n_names']} names · {p['start']} → {p['end']} · "
             f"{p['horizon_days']}d horizon · {p['rebalance_days']}d rebalance*\n")
    if m.get("n_periods", 0) == 0:
        L.append("**No evaluable periods** — check price/financial coverage over the window.")
        return "\n".join(L)
    L.append("| metric | value | reading |")
    L.append("|---|---|---|")
    ic, t = m["mean_ic"], m.get("ic_t_stat")
    L.append(f"| Mean rank-IC | **{ic:+.4f}** | {_ic_reading(ic)} |")
    L.append(f"| IC t-stat | {t if t is not None else '—'} | {_t_reading(t)} |")
    L.append(f"| IC hit rate | {m['ic_hit_rate']:.1%} | periods with IC > 0 |")
    L.append(f"| Decile spread (per {p['horizon_days']}d) | "
             f"{_fmt_pct(m.get('mean_decile_spread'))} | top-decile minus bottom, excess vs SPY |")
    L.append(f"| Decile spread (annualized) | {_fmt_pct(m.get('decile_spread_annualized'))} | |")
    L.append(f"| Periods · avg names | {m['n_periods']} · {m['mean_names']} | |")
    L.append(f"\n_{r.notes}_")
    return "\n".join(L)


def _ic_reading(ic: float) -> str:
    a = abs(ic)
    band = ("noise" if a < 0.02 else "weak" if a < 0.05 else "decent (equity-factor range)"
            if a < 0.10 else "strong")
    return f"{'positive' if ic > 0 else 'negative'} edge, {band}"


def _t_reading(t: float | None) -> str:
    if t is None:
        return "—"
    return "significant (>2)" if abs(t) > 2 else "suggestive" if abs(t) > 1 else "not significant"


def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:+.2f}%"


async def main_async(args: argparse.Namespace) -> None:
    membership: dict | None = None
    if not args.no_pit:
        from app.universe.history import load_history
        try:
            membership = load_history()
        except FileNotFoundError:
            print("[backtest] no membership_history.json — falling back to current-snapshot universe.")
    tickers = await _universe_tickers(membership)
    mode = "point-in-time" if membership is not None else "current-snapshot"
    print(f"[backtest] universe: {len(tickers)} names ({mode}); running…", flush=True)
    result = await async_run(tickers, args, membership)

    print("\n" + _report(result) + "\n")

    if not args.no_save:
        async with async_session() as db:
            row = BacktestRun(label=args.label, params=result.params,
                              metrics=result.metrics, ic_series=result.ic_series, notes=result.notes)
            db.add(row)
            await db.commit()
            await db.refresh(row)
        print(f"[backtest] saved run #{row.id} to backtest_runs.", flush=True)


async def async_run(tickers: list[str], args: argparse.Namespace,
                    membership: dict | None = None) -> BacktestResult:
    async with async_session() as db:
        return await run_backtest(
            db, tickers, horizon_days=args.horizon, rebalance_days=args.rebalance,
            label=args.label, membership=membership)


def main() -> None:
    ap = argparse.ArgumentParser(description="Walk-forward rank-IC backtest of the deterministic screen.")
    ap.add_argument("--horizon", type=int, default=63, help="forward-return horizon in trading days (~63=3mo)")
    ap.add_argument("--rebalance", type=int, default=63, help="rebalance interval in trading days")
    ap.add_argument("--label", type=str, default=None)
    ap.add_argument("--no-save", action="store_true", help="print only; don't persist to backtest_runs")
    ap.add_argument("--no-pit", action="store_true",
                    help="legacy mode: current-snapshot universe (survivorship-biased) instead of "
                         "point-in-time membership")
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
