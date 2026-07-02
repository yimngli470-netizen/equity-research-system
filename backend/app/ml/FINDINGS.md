# M5 (LightGBM screen-ranker) — findings

**Date:** 2026-06-30 · **Verdict:** ❌ No stable out-of-sample edge over the hand-screen at this data
scale. Do **not** deploy M5 to replace the hand-screen. Keep the deterministic hand-screen as the
screen-rank signal; revisit M5 only with *new data or new features*, not tuning.

> Scope: this concerns output ① the **screen-rank** only. It says nothing about the LLM signal (②)
> or the DCF price target (③), which are graded prospectively by the accountability loop.

---

## 2026-07-01 update — M4 re-measurement: half the baseline was survivorship bias

M4 shipped the point-in-time panel (see `ANALYST_ROADMAP.md`): **historical S&P membership**
(727 names were members at some point 2016–2026; the old universe saw only the 503 survivors —
98 of the 224 removed names recovered with full free price history, universe 503 → 617 with data)
and **exact SEC filed-date gating** (median real filing lag 35d vs the blanket 75d assumption;
99.6% of EDGAR rows now carry `filed_date`). Panels are now materialized + versioned
(`panel_versions`/`panel_rows`, `python -m app.ml.materialize`); results below pin versions 1–2.

Two single-variable comparisons on the hand-screen (36 quarters, 2017–2026):

| Universe | Gating | Mean rank-IC | t | What changed |
|---|---|---|---|---|
| current-snapshot (old) | 75d lag | **+0.0174** | 1.14 | the original baseline |
| current-snapshot (old) | filed-date | +0.0170 | 1.1 | gating alone: ~no effect |
| **point-in-time (M4)** | filed-date | **+0.0090** | 0.5 | **universe fix: edge halves** |

And M5 vs the hand-screen on the honest (PIT) panels, same purged walk-forward:

| Panel | OOS periods | GBM IC (t) | Hand-screen IC (t) |
|---|---|---|---|
| v1 quarterly | 24 | −0.0015 (−0.09) | −0.0023 (−0.11) |
| v2 monthly | 92 | −0.0113 (−1.08) | −0.0004 (−0.03) |

**Reading.** (1) Roughly **half the hand-screen's measured edge was survivorship bias** — scoring
only the names that survived to 2026 flattered the screen by ~0.008 IC. (2) What remains
(+0.0090 full-sample) is front-loaded in 2017–2020; over the 2020+ OOS windows both the GBM and
the hand-screen are statistically zero. (3) The GBM's illusory quarterly +0.0168 (already shown
to be retraining variance) does not reappear on the corrected data — the original verdict stands,
now on cleaner evidence. (4) Residual optimism remains: ~126 removed names (acquired/private/
delisted) have no free price history, so even the PIT numbers are slightly flattered — the
bankruptcy-shaped hole free data cannot fill.

**Consequence.** The bar for M5 didn't move — it dropped: there is now *less* proven edge in the
hand-screen to beat, and less apparent signal in these 11 features overall. The improvement path
is unchanged (new features next: quality/size/volatility are computable free from data already in
the DB; estimate-revisions accrue in `consensus_snapshots`), but any future claim of edge must be
made on a pinned PIT panel version, never the legacy universe.

## Question
Can a LightGBM, learning the feature combination from history, rank the ~500-name universe by
forward 3-month excess-vs-SPY return **better than the hand-authored, fixed-weight screen** —
out-of-sample, with honest statistics?

## Method
Point-in-time panel (`app/ml/panel.py`) reusing the backtest's leakage-gated features (75-day
reporting lag); features cross-sectionally rank-transformed; label = forward 63-day excess return vs
SPY (winsorized for training). Purged walk-forward CV with an embargo of `ceil(horizon/rebalance)`.
Scored by Spearman **rank-IC** and its t-stat (naive and Newey-West, overlap-adjusted). Baseline =
the original hand-screen (`app/backtest/screen.py`) over the **same** OOS periods. Entrypoint:
`python -m app.ml.run`; report: `python -m app.ml.report`.

## Results — measured three independent ways
| Method | GBM rank-IC | t-stat (NW) | Hand-screen (same window) |
|---|---|---|---|
| Quarterly walk-forward (24 OOS q) | **+0.0168** | 0.77 (0.79) | +0.0065 |
| Monthly walk-forward (60 OOS m) | **−0.0063** | −0.38 (−0.27) | +0.0087 |
| Single frozen split (train ’17–’20 → test ’20–’26) | **−0.0197** | — | +0.0102 |

(Hand-screen reference, all 36 quarters 2017–2026: +0.0174, t 1.14.)

Only the quarterly walk-forward flattered the GBM. The other two — and the honest, overlap-adjusted
t-stats — do not. **No configuration clears statistical significance (|t| < 2).**

## The robustness test that settled it
The GBM's mean IC **flipped sign** between quarterly (+0.0168) and monthly (−0.0063) sampling, while
the hand-screen stayed stably small-positive (+0.0065 → +0.0087). To isolate the cause we trained
**one frozen GBM** and scored it on both date grids:

```
                                 all monthly dates   quarterly dates
ONE frozen GBM (no retraining)        −0.0197           −0.0105     ← aligned
hand-screen (control)                 +0.0102           +0.0054     ← aligned
```

A **fixed** model gives aligned quarterly/monthly results (like the never-trained hand-screen). So the
date sampling does **not** cause the divergence — the walk-forward sign-flip came entirely from
**retraining different models** (different rebalance dates → different training rows → different learned
rules). On a near-zero signal, that model variance dominates and lands on either side of zero.

## Diagnosis
**Model-variance issue on a weak signal — not a data bug.** The hand-screen's stability across all
samplings is the control that proves it: a fixed function cannot diverge; a refit model can. The
quarterly +0.0168 was a lucky retraining draw, not skill. (Feature importances were sane — momentum,
`rev_growth`, the built `earnings_yield` lead — but sane features can't rescue an absent signal.)

## Why this is the *expected* outcome, not a failure
Supervised forward-return prediction is what quant funds spend fortunes on and still find hard. With
~24 *independent* 3-month periods over ~500 **survivor** names and ~10y of history, there isn't enough
independent information to prove a small edge. Catching the illusory quarterly edge **before** trusting
it is the process working correctly.

## How to improve — in order of leverage (and what NOT to do)
The bottleneck is **data/signal, not model configuration**. No setting conjures signal that isn't there.

1. **More & cleaner data (highest leverage).** Fix **survivorship bias** (historical index
   constituents — delisted/bankrupt names are currently absent and flatter every result); extend price
   history; broaden the universe. This is roadmap **M4** (the point-in-time panel / feature store).
2. **Genuinely new predictive features (raises the ceiling).** Analyst **estimate-revisions**
   (a strong real factor), quality (ROE/accruals/leverage), **M3 regime state** (info the hand-screen
   lacks), volatility/size. A model is only as good as its inputs.
3. **Variance reduction (matches the diagnosis).** Ensemble across folds/seeds; keep the model simple
   (we already regularize hard); more training data. The model is *high-variance* — simplify and
   stabilize, don't add complexity.
4. **Better-matched objective (second-order).** Learning-to-rank (`lambdarank`) since we only care
   about order; or a longer/cleaner target.

**❌ Hyperparameter tuning is the LOWEST-value lever here — and risky.** It cannot create signal, and
searching many configs then picking the best invites overfitting/multiple-comparisons (manufacturing a
fake edge). Our params are already conservatively regularized — the correct choice for a weak signal;
loosening them would overfit *more*. The ML maxim applies: **more data and better features beat better
hyperparameters**, especially in weak-signal finance.

## Decision
Keep the hand-screen as the screen-rank. Shelve M5 as a serving model. Reopen only after M4
(survivorship + history) or new features (M3 / revisions) materially change the inputs — then re-run
`python -m app.ml.run` and require the OOS rank-IC to beat the hand-screen **and** clear t > 2, *and*
stay positive under both quarterly and monthly sampling.
