"""M5 end-to-end, reproducibly: panel → preprocess → purged walk-forward → LightGBM → OOS rank-IC,
measured against the original hand-screen over the SAME out-of-sample periods.

Run:
    docker compose exec backend python -m app.ml.run
"""

from __future__ import annotations

import asyncio
import warnings

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.evaluate import _spearman
from app.backtest.run import _universe_tickers
from app.backtest.screen import score_cross_section
from app.database import async_session
from app.ml.panel import FEATURE_COLS, LABEL_COL, build_panel
from app.ml.preprocess import rank_features, winsorize_label
from app.ml.split import walk_forward_folds
from app.ml.train import train_fold


def _tstat(ics: list[float]) -> float:
    a = np.asarray(ics, float)
    n = len(a)
    s = a.std(ddof=1)
    return float(a.mean() / s * np.sqrt(n)) if s > 0 and n > 1 else float("nan")


async def evaluate_m5(
    db: AsyncSession, *, horizon: int = 63, rebalance: int = 63, min_train: int = 12, n_test: int = 4
) -> dict:
    """Run the whole walk-forward and return a results dict (per-date ICs, summary metrics,
    feature importances). Pure — no I/O beyond the DB read; the report layer renders it."""
    tickers = await _universe_tickers()
    raw = await build_panel(db, tickers, horizon_days=horizon, rebalance_days=rebalance)
    proc = rank_features(raw, FEATURE_COLS)                 # cross-sectional ranks (for the model)
    proc, _clip = winsorize_label(proc, LABEL_COL)          # clipped label (for TRAINING only)
    dates = sorted(raw.date.unique())
    folds = walk_forward_folds(
        dates, min_train=min_train, n_test=n_test, horizon_days=horizon, rebalance_days=rebalance
    )

    # LightGBM walk-forward: train on each fold's past, predict its (strictly-later) test rows.
    oos: list[tuple] = []
    imp = np.zeros(len(FEATURE_COLS))
    for f in folds:
        tr = proc[proc.date.isin(f.train_dates)]
        te = proc[proc.date.isin(f.test_dates)]
        model, pred = train_fold(tr[FEATURE_COLS].values, tr[LABEL_COL].values, te[FEATURE_COLS].values)
        imp += model.feature_importances_
        ytrue = raw.loc[te.index, LABEL_COL].values          # evaluate vs RAW (un-clipped) return
        oos.extend(zip(te.date.values, te.ticker.values, pred, ytrue))
    oos = pd.DataFrame(oos, columns=["date", "ticker", "pred", "y"])
    imp /= len(folds)
    test_dates = sorted(oos.date.unique())
    gbm_ic = {d: _spearman(list(g.pred), list(g.y)) for d, g in oos.groupby("date")}

    # Baseline: the ORIGINAL hand-screen (score_cross_section) over the SAME OOS dates.
    base_ic: dict[str, float] = {}
    meta = [c for c in raw.columns if c in ("ticker", "date", LABEL_COL)]
    feat_cols_all = [c for c in raw.columns if c not in meta]
    for d in test_dates:
        sub = raw[raw.date == d]
        feats = {
            r.ticker: {c: getattr(r, c) for c in feat_cols_all if pd.notna(getattr(r, c))}
            for r in sub.itertuples()
        }
        comp = score_cross_section(feats)
        ymap = dict(zip(sub.ticker, sub[LABEL_COL]))
        names = list(comp)
        base_ic[d] = _spearman([comp[t] for t in names], [ymap[t] for t in names])

    g = [gbm_ic[d] for d in test_dates]
    b = [base_ic[d] for d in test_dates]
    return {
        "test_dates": test_dates,
        "gbm_ic": g,
        "base_ic": b,
        "gbm": {"mean_ic": float(np.mean(g)), "t": _tstat(g), "hit": float(np.mean(np.array(g) > 0))},
        "base": {"mean_ic": float(np.mean(b)), "t": _tstat(b), "hit": float(np.mean(np.array(b) > 0))},
        "importances": dict(zip(FEATURE_COLS, imp.tolist())),
        "folds": [(f.k, f.test_dates[0], f.test_dates[-1]) for f in folds],
    }


async def _main() -> None:
    warnings.filterwarnings("ignore")
    async with async_session() as db:
        r = await evaluate_m5(db)
    print(f"OOS {r['test_dates'][0]} → {r['test_dates'][-1]} ({len(r['test_dates'])} periods)")
    for k, lbl in (("gbm", "LightGBM   "), ("base", "Hand-screen")):
        m = r[k]
        print(f"  {lbl}: IC {m['mean_ic']:+.4f}   t {m['t']:.2f}   hit {m['hit']:.0%}")


if __name__ == "__main__":
    asyncio.run(_main())
