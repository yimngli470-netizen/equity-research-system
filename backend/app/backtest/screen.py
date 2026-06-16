"""The deterministic screen, scored cross-sectionally AS-OF (roadmap 6.3d).

This reproduces the live screen's *hard-feature* signal — growth, profitability, valuation, momentum
— in a backtest-friendly form. Each raw feature is turned into a cross-sectional percentile within
the as-of universe (so it's peer-relative by construction, no absolute-bound calibration), valuation
metrics inverted (cheap ranks high). The composite is a weighted average of the available category
percentiles, matching the live screen's relative emphasis on the four hard categories.

The LLM/AI categories (sentiment, risk, event) do NOT exist historically and are deliberately absent
— per the honesty rule, the backtest validates the deterministic screen only.
"""

from __future__ import annotations

# Feature → category, and whether higher-raw is better (False ⇒ invert: cheap/low is better).
_FEATURES: dict[str, tuple[str, bool]] = {
    "rev_growth": ("growth", True),
    "eps_growth": ("growth", True),
    "gross_margin": ("profitability", True),
    "op_margin": ("profitability", True),
    "net_margin": ("profitability", True),
    "fcf_margin": ("profitability", True),
    "pe": ("valuation", False),          # low P/E ⇒ cheap ⇒ ranks high
    "ps": ("valuation", False),
    "fcf_yield": ("valuation", True),    # high FCF yield ⇒ cheap ⇒ ranks high
    "mom_3m": ("momentum", True),
    "mom_6m": ("momentum", True),
    "mom_12m": ("momentum", True),
}

# Hard-category weights = the live screen's category weights (growth 20 / valuation 20 /
# profitability 15 / momentum 10) renormalized over just the four hard categories.
_CATEGORY_WEIGHTS = {"growth": 0.308, "valuation": 0.308, "profitability": 0.231, "momentum": 0.154}


def _percentile_rank(values: dict[str, float], invert: bool) -> dict[str, float]:
    """Map a {ticker: value} cross-section to {ticker: percentile in [0,1]} (ties share the midrank)."""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        # midrank percentile for the tie block [i..j]
        pct = ((i + j) / 2) / (n - 1) if n > 1 else 0.5
        for k in range(i, j + 1):
            out[items[k][0]] = (1.0 - pct) if invert else pct
        i = j + 1
    return out


def score_cross_section(features: dict[str, dict[str, float]]) -> dict[str, float]:
    """Composite screen score per ticker from the as-of feature cross-section.

    `features`: {ticker: {feature_name: raw_value}}. Returns {ticker: composite in [0,1]}.
    """
    tickers = list(features.keys())
    # Cross-sectional percentile per feature (over names that HAVE the feature).
    norm: dict[str, dict[str, float]] = {t: {} for t in tickers}
    for feat, (_cat, higher_better) in _FEATURES.items():
        present = {t: features[t][feat] for t in tickers if feat in features[t]}
        if len(present) < 3:
            continue
        for t, p in _percentile_rank(present, invert=not higher_better).items():
            norm[t][feat] = p

    # Category scores = mean of that category's available normalized features.
    composite: dict[str, float] = {}
    for t in tickers:
        cat_vals: dict[str, list[float]] = {}
        for feat, p in norm[t].items():
            cat_vals.setdefault(_FEATURES[feat][0], []).append(p)
        cat_score = {c: sum(v) / len(v) for c, v in cat_vals.items()}
        if not cat_score:
            continue
        wsum = sum(_CATEGORY_WEIGHTS[c] for c in cat_score)
        composite[t] = sum(_CATEGORY_WEIGHTS[c] * s for c, s in cat_score.items()) / wsum
    return composite
