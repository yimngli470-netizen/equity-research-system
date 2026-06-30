"""Stage 2 preprocessing for the M5 panel.

Two transforms, each with a specific job:

1. `rank_features` — CROSS-SECTIONAL percentile rank (per rebalance date). This is the key one.
   • Kills outliers: a P/S of 1.8M just becomes "rank 1.0 (most expensive that day)", not a number
     that dominates everything.
   • Fights non-stationarity: a percentile means the same thing in 2017 and 2024, whereas raw
     margins/valuations drift over a decade. (Note: it's NOT just "trees want it" — a *global*
     monotonic transform wouldn't change a tree; but a *per-date* rank removes time trends, which
     genuinely changes the data and is the whole point.)
   • Peer-relative by construction — the same framing the hand-screen uses.
   NaN stays NaN (LightGBM routes missing values itself), so a 76%-covered feature is ranked among
   the names that have it and left missing elsewhere.

2. `winsorize_label` — clip the label's extreme tails. The +489% excess-return moonshots would
   otherwise dominate a squared-error regression loss; clipping focuses the model on the typical
   range. Rank-IC evaluation is barely affected (it's rank-based), but training is much steadier.
"""

from __future__ import annotations

import pandas as pd


def rank_features(df: pd.DataFrame, feature_cols: list[str], date_col: str = "date") -> pd.DataFrame:
    """Return a copy with each feature replaced by its cross-sectional percentile (0..1) within its
    rebalance date. NaN is preserved."""
    out = df.copy()
    for c in feature_cols:
        out[c] = df.groupby(date_col)[c].rank(pct=True)
    return out


def winsorize_label(
    df: pd.DataFrame, label_col: str, lo: float = 0.01, hi: float = 0.99
) -> tuple[pd.DataFrame, tuple[float, float]]:
    """Return (clipped copy, (low_clip, high_clip)) — label clipped to its [lo, hi] quantiles."""
    out = df.copy()
    ql, qh = df[label_col].quantile([lo, hi])
    out[label_col] = df[label_col].clip(ql, qh)
    return out, (float(ql), float(qh))
