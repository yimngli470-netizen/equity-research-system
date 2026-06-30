"""Stage 4 — train a LightGBM ranker inside the purged walk-forward folds.

The signal is weak and the data is modest, so the entire hyperparameter philosophy is REGULARIZE
HARD — a model that can memorize 14k noisy rows will, and then fail out-of-sample. Each knob below is
set to keep the trees shallow, slow, and forced to rely on patterns common to many names:

  • objective="regression"  — predict the (winsorized) forward excess return; we score by rank-IC.
  • n_estimators=300         — many small trees (boosting), each nudging the prediction a little.
  • learning_rate=0.03       — small steps; slower learning generalizes better than big greedy jumps.
  • num_leaves=15, max_depth=4 — SHALLOW trees: shallow ⇒ can only model coarse interactions, not
                                 memorize individual rows. The #1 overfit guard for tabular finance.
  • min_child_samples=100    — a leaf must cover ≥100 (ticker, quarter) rows; no rules fit to a
                                 handful of lucky names.
  • subsample / colsample=0.8 — each tree sees a random 80% of rows and features (bagging-style noise
                                 injection) ⇒ less variance, less overfit.
  • reg_alpha / reg_lambda    — L1/L2 penalties on leaf weights ⇒ shrink toward zero, ignore weak splits.

These are intentionally conservative, not tuned. Tuning (with a nested time-split) comes later — first
we want an honest read of whether there's *any* OOS signal at sane defaults.
"""

from __future__ import annotations

import numpy as np
import lightgbm as lgb

DEFAULT_PARAMS = dict(
    objective="regression",
    n_estimators=300,
    learning_rate=0.03,
    num_leaves=15,
    max_depth=4,
    min_child_samples=100,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_alpha=0.1,
    reg_lambda=0.5,
    verbose=-1,
    n_jobs=-1,
)


def train_fold(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray, params: dict | None = None):
    """Fit LightGBM on one fold's train split and predict its test split.

    Returns (fitted_model, test_predictions). NaNs in X are fine — LightGBM learns a default branch
    direction for missing values, so we do not impute.
    """
    model = lgb.LGBMRegressor(**(params or DEFAULT_PARAMS))
    model.fit(X_train, y_train)
    return model, model.predict(X_test)
