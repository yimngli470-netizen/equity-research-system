"""Stage 3 — purged walk-forward cross-validation for the M5 panel.

Time-series ML must NEVER use a random train/test split. Shuffling rows lets the model train on the
future and test on the past — it leaks, and inflates every metric. Instead we WALK FORWARD: always
train on the PAST, test on a strictly-LATER block, then slide forward. This mirrors reality — you can
only ever fit on history and trade the future.

The PURGE / EMBARGO. A training row dated T carries a label = its forward return over [T, T+horizon].
If T sits within `horizon` of the first test date, that label's measurement window overlaps the test
era — the model has effectively peeked at test-period prices. So before each test block we DROP the
last `embargo_periods` of training rows, leaving a clean time gap.

    embargo_periods = ceil(horizon_days / rebalance_days)

(With our quarterly rebalance = 63d and horizon = 63d, that's 1 period: the training date immediately
before the test block has a forward window that reaches exactly into it, so we drop it.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Fold:
    k: int
    train_dates: list[str]
    test_dates: list[str]
    embargo_dates: list[str]   # the periods dropped between train and test


def embargo_periods(horizon_days: int, rebalance_days: int) -> int:
    return max(1, math.ceil(horizon_days / rebalance_days))


def walk_forward_folds(
    dates: list[str], *, min_train: int, n_test: int, horizon_days: int, rebalance_days: int
) -> list[Fold]:
    """Expanding-window walk-forward folds with an embargo gap. `dates` = the sorted unique rebalance
    dates. Each fold trains on all history up to a cutoff (minus the embargo) and tests on the next
    `n_test` periods."""
    dates = sorted(dates)
    emb = embargo_periods(horizon_days, rebalance_days)
    folds: list[Fold] = []
    i, k = min_train, 1
    while i + n_test <= len(dates):
        folds.append(Fold(
            k=k,
            train_dates=dates[: i - emb],
            embargo_dates=dates[i - emb : i],
            test_dates=dates[i : i + n_test],
        ))
        i += n_test
        k += 1
    return folds
