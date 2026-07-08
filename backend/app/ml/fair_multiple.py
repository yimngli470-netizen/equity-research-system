"""M5b fair-multiple model (stage 2) — what does the market pay for these fundamentals?

DESCRIPTIVE, not predictive: per rebalance date, regress log(P/S) on that date's cross-section of
fundamentals (Fama–MacBeth style). The fit answers "what multiple do companies with these stats
trade at TODAY?"; the residual answers "how far above/below that is this name?". No alpha claim —
the residual is a triangulation anchor for the valuation layer, and a precise question for the
thesis layer (what justifies the premium, and is it durable?).

Design (see FINDINGS.md for the measured rationale):
  • One model PER DATE — the market's overall multiple level moves hugely across eras (median P/S
    2.1 in 2017 → 3.3 in 2021 → 3.7 in 2026); per-date fits make residuals era-relative by
    construction, and the coefficient/intercept time series doubles as a mix-adjusted
    "what the market pays" dashboard.
  • Label = log(P/S), winsorized 1%/99% per date. Log because multiples are right-skewed ratios
    (raw skew 68 → log skew 0.8 on panel v3); residuals in log space read as % premium/discount
    (resid r ⇒ trades e^r − 1 above fair).
  • X = FUNDAMENTALS ONLY by default. `ps` IS the label; `earnings_yield`/`fcf_yield` contain
    price (mechanical leakage); `size` (log mktcap) and momentum contain price too — offered as
    explicit variants so the leakage gradient is visible, not hidden.
  • Features z-scored per date (clipped ±3): coefficients then read as
    "+1σ of rev_growth ⇒ +β log-multiple ⇒ ×e^β on the fair P/S".
  • Validation = held-out NAMES (random 20% within each date), never held-out time — a
    descriptive model of a date's cross-section is validated within that cross-section.

Run:  docker compose exec backend python -m app.ml.fair_multiple --panel-version 3
"""

from __future__ import annotations

import argparse
import asyncio
import warnings

import numpy as np
import pandas as pd

from app.database import async_session
from app.ml.materialize import load_panel_version

LABEL = "ps"

# Price-free fundamentals — the primary X. net_margin/fcf_margin are deliberately ABSENT: they
# correlate 0.94–0.99 with op_margin (one feature in three coats), and OLS under collinearity
# splits their shared credit arbitrarily (net_margin drew a nonsense negative sign, 55% stable).
# gross_margin stays — nearly orthogonal (0.07 vs op_margin) because it prices the business MODEL
# (software vs retail), not this quarter's efficiency.
FUND_COLS = ["rev_growth", "gross_margin", "op_margin", "roe", "accruals", "leverage"]
# Price-containing add-ons, exposed as named variants (leakage made visible).
VARIANTS: dict[str, list[str]] = {
    "fundamentals": FUND_COLS,
    "+size": FUND_COLS + ["size"],
    "+size+momentum": FUND_COLS + ["size", "mom_12m"],
}

_WINSOR = (0.01, 0.99)
_HOLDOUT = 0.2
_SEED = 7


def _r2(y: np.ndarray, yhat: np.ndarray) -> float:
    ss_tot = float(((y - y.mean()) ** 2).sum())
    ss_res = float(((y - yhat) ** 2).sum())
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def _prep_date(sub: pd.DataFrame, cols: list[str]) -> pd.DataFrame | None:
    """One date's cross-section → winsorized log label + z-scored X.

    Missing features are imputed to z = 0 ("assume average") AFTER z-scoring over the names that
    have the value — complete-case would drop ~2/3 of the cross-section (gross_margin alone is
    absent for ~45%: banks/insurers file no cost-of-goods line), and a fair-value model that can't
    price half the index is not describing the market."""
    d = sub.dropna(subset=[LABEL]).copy()
    d = d[d[LABEL] > 0]
    if len(d) < 60:  # too thin a cross-section to fit honestly
        return None
    y = np.log(d[LABEL])
    lo, hi = y.quantile(_WINSOR[0]), y.quantile(_WINSOR[1])
    d["_y"] = y.clip(lo, hi)
    for c in cols:
        v = d[c]
        sd = v.std(ddof=0)
        d[c] = (((v - v.mean()) / sd).clip(-3, 3) if sd and sd > 0 else 0.0)
        d[c] = d[c].fillna(0.0)
    return d


def fit_date(sub: pd.DataFrame, cols: list[str], rng: np.random.Generator) -> dict | None:
    """OLS on one date. Returns in/out R², coefficients, intercept, and per-name residuals
    (residuals come from the ALL-ROWS fit; the 80/20 split exists only to measure overfit)."""
    d = _prep_date(sub, cols)
    if d is None:
        return None
    X = np.column_stack([d[c].values for c in cols] + [np.ones(len(d))])
    y = d["_y"].values

    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta

    idx = rng.permutation(len(d))
    k = max(1, int(len(d) * _HOLDOUT))
    te, tr = idx[:k], idx[k:]
    b_tr, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
    return {
        "date": d["date"].iloc[0],
        "n": len(d),
        "r2_in": _r2(y[tr], X[tr] @ b_tr),
        # per-date held-out R² on ~n/5 names is far too noisy to average (one bad draw → −100);
        # return held-out pairs for the caller to pool into ONE R². Demeaned by the date's train
        # mean so pooled R² stays WITHIN-date — otherwise the intercepts get credit for the era
        # drift (2017 cheap vs 2021 rich) and the number flatters.
        "holdout": (y[te] - y[tr].mean(), X[te] @ b_tr - y[tr].mean()),
        "coefs": dict(zip(cols, beta[:-1])),
        "intercept": float(beta[-1]),          # z-scored X ⇒ e^intercept = the date's typical P/S
        "residuals": pd.Series(resid, index=d["ticker"].values),
    }


def run_variant(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    rng = np.random.default_rng(_SEED)
    out = []
    for _, sub in df.groupby("date"):
        r = fit_date(sub, cols, rng)
        if r is not None:
            out.append(r)
    return out


def summarize(fits: list[dict], cols: list[str]) -> str:
    r2i = np.mean([f["r2_in"] for f in fits])
    y_out = np.concatenate([f["holdout"][0] for f in fits])
    yhat_out = np.concatenate([f["holdout"][1] for f in fits])
    r2o = _r2(y_out, yhat_out)   # ONE pooled held-out R² across all dates' test names
    lines = [f"  {len(fits)} dates · avg n/date {np.mean([f['n'] for f in fits]):.0f} · "
             f"R² in-sample {r2i:.3f} · held-out names (pooled) {r2o:.3f}"]
    lines.append(f"  {'coef (log P/S per +1σ)':26s} {'mean β':>8s} {'⇒ ×fair':>8s} {'sign-stable':>12s}")
    for c in cols:
        b = np.array([f["coefs"][c] for f in fits])
        stab = max((b > 0).mean(), (b < 0).mean())
        lines.append(f"    {c:24s} {b.mean():+8.3f} {np.exp(b.mean()):8.2f} {stab:11.0%}")
    return "\n".join(lines)


async def _main() -> None:
    ap = argparse.ArgumentParser(description="M5b fair-multiple per-date regression.")
    ap.add_argument("--panel-version", type=int, default=3)
    args = ap.parse_args()
    warnings.filterwarnings("ignore")

    async with async_session() as db:
        df, params = await load_panel_version(db, args.panel_version)

    print(f"panel v{args.panel_version}: {len(df)} rows · label log({LABEL}) winsorized "
          f"{int(_WINSOR[0]*100)}/{int(_WINSOR[1]*100)}%\n")

    fits_primary: list[dict] | None = None
    for name, cols in VARIANTS.items():
        fits = run_variant(df, cols)
        print(f"[{name}]")
        print(summarize(fits, cols) + "\n")
        if name == "fundamentals":
            fits_primary = fits

    # The market-level dashboard: e^intercept = the typical (mix-adjusted) P/S through time.
    print("[market level — e^intercept = typical P/S for an average-stats name]")
    by_year: dict[str, list[float]] = {}
    for f in fits_primary:
        by_year.setdefault(str(f["date"])[:4], []).append(np.exp(f["intercept"]))
    for yr in sorted(by_year):
        print(f"  {yr}: {np.mean(by_year[yr]):.2f}")

    # Latest-date residual extremes — the story-sense sanity check.
    last = fits_primary[-1]
    res = last["residuals"].sort_values()
    fmt = lambda s: "  ".join(f"{t} {np.exp(v)-1:+.0%}" for t, v in s.items())
    print(f"\n[latest date {last['date']} — residual = actual vs fair P/S]")
    print(f"  richest:  {fmt(res.tail(5)[::-1])}")
    print(f"  cheapest: {fmt(res.head(5))}")


if __name__ == "__main__":
    asyncio.run(_main())
