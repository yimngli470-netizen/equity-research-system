"""Feature normalization — map raw feature values to 0-1 scores.

Each feature has its own normalization logic because the "good" range
varies by metric type. For example:
- Revenue YoY growth of 30% is great → high score
- Forward P/E of 30 is expensive → lower score (inverse)
- Gross margin of 70% is excellent → high score

We use piecewise linear mapping: define (low, high) bounds where
low → 0.0 and high → 1.0, clamped to [0, 1].
"""


def _linear_normalize(
    value: float | None,
    low: float,
    high: float,
    invert: bool = False,
) -> float | None:
    """Linearly map value from [low, high] to [0, 1]. Clamps to bounds.

    If invert=True, high values map to low scores (e.g., P/E ratio).
    """
    if value is None:
        return None
    if high == low:
        return 0.5

    score = (value - low) / (high - low)
    score = max(0.0, min(1.0, score))

    if invert:
        score = 1.0 - score

    return round(score, 4)


# ── Normalization configs ──
# (low_bound, high_bound, invert)
# low_bound = value that maps to 0.0 (or 1.0 if inverted)
# high_bound = value that maps to 1.0 (or 0.0 if inverted)

GROWTH_NORMS: dict[str, tuple[float, float, bool]] = {
    "revenue_yoy":              (-0.20, 0.50, False),  # -20% → 0, +50% → 1
    "net_income_yoy":           (-0.30, 0.60, False),
    "eps_yoy":                  (-0.30, 0.60, False),
    "operating_income_yoy":     (-0.30, 0.60, False),
    "gross_profit_yoy":         (-0.20, 0.50, False),
    "revenue_qoq":              (-0.10, 0.20, False),
    "eps_qoq":                  (-0.15, 0.25, False),
    "growth_consistency":       (0.0, 1.0, False),     # already 0-1
    "revenue_acceleration":     (-0.10, 0.10, False),  # -10pp → 0, +10pp → 1
}

PROFITABILITY_NORMS: dict[str, tuple[float, float, bool]] = {
    "gross_margin":                 (0.20, 0.80, False),
    "operating_margin":             (-0.05, 0.40, False),
    "profit_margin":                (-0.05, 0.35, False),
    "fcf_margin":                   (-0.05, 0.35, False),
    "gross_margin_change_qoq":      (-0.03, 0.03, False),
    "operating_margin_change_qoq":  (-0.03, 0.03, False),
    "gross_margin_change_yoy":      (-0.05, 0.05, False),
    "operating_margin_change_yoy":  (-0.05, 0.05, False),
    "operating_leverage":           (0.5, 2.0, False),
    "fcf_conversion":               (0.5, 1.5, False),
}

VALUATION_NORMS: dict[str, tuple[float, float, bool]] = {
    "forward_pe":       (10.0, 60.0, True),   # lower P/E → better value → higher score
    "trailing_pe":      (10.0, 80.0, True),
    "peg_ratio":        (0.5, 3.0, True),     # lower PEG → better → higher score
    "price_to_sales":   (1.0, 30.0, True),
    "price_to_book":    (1.0, 20.0, True),
    "ev_to_revenue":    (1.0, 30.0, True),
    "ev_to_ebitda":     (5.0, 50.0, True),
    "earnings_growth":  (-0.10, 0.50, False),
    "revenue_growth_fwd": (-0.05, 0.40, False),
}

MOMENTUM_NORMS: dict[str, tuple[float, float, bool]] = {
    "momentum_1m":  (-0.10, 0.10, False),
    "momentum_3m":  (-0.20, 0.20, False),
    "momentum_12m": (-0.30, 0.50, False),
}

# AI-derived features — many are already 0-1 from agents
SENTIMENT_NORMS: dict[str, tuple[float, float, bool]] = {
    "news_sentiment":       (-1.0, 1.0, False),  # agent outputs -1 to 1
    "news_avg_impact":      (0.0, 1.0, False),
    "news_positive_ratio":  (0.0, 1.0, False),
    "indicator_signal_avg": (0.0, 1.0, False),
    "cycle_position_score": (0.0, 1.0, False),
}

EVENT_NORMS: dict[str, tuple[float, float, bool]] = {
    "earnings_quality":       (0.0, 1.0, False),
    "revenue_trend_signal":   (0.0, 1.0, False),
    "margin_trend_signal":    (0.0, 1.0, False),
    "fwd_revenue_signal":     (0.0, 1.0, False),
    "fwd_margin_signal":      (0.0, 1.0, False),
    "fwd_confidence":         (0.0, 1.0, False),
    "management_tone":        (0.0, 1.0, False),   # already mapped 0-1
    "eps_beat_rate":           (0.0, 1.0, False),   # 0/4 to 4/4
    "avg_surprise_pct":       (-0.10, 0.10, False), # -10% to +10%
    "beat_trend":              (0.0, 1.0, False),   # already mapped 0-1
}

RISK_NORMS: dict[str, tuple[float, float, bool]] = {
    "earnings_risk_avg":  (0.0, 1.0, True),   # higher risk → lower score
    "industry_risk_avg":  (0.0, 1.0, True),
    "moat_strength":      (0.0, 1.0, False),   # strong moat → good → high score
    "market_share_trend": (0.0, 1.0, False),
    "avg_theme_exposure": (0.0, 1.0, False),
}

AI_VALUATION_NORMS: dict[str, tuple[float, float, bool]] = {
    "ai_valuation_score":       (0.0, 1.0, False),
    "margin_of_safety":         (-0.30, 0.50, False),
    "vs_historical":            (0.0, 1.0, False),
    "vs_peers":                 (0.0, 1.0, False),
    "valuation_verdict_score":  (0.0, 1.0, False),
    "target_upside":            (-0.30, 0.50, False),
    "eps_vs_consensus":         (0.0, 1.0, False),   # already mapped 0-1
    "revenue_vs_consensus":     (0.0, 1.0, False),
    "guidance_tone":            (0.0, 1.0, False),
    "guidance_vs_consensus":    (0.0, 1.0, False),
}

VALIDATION_NORMS: dict[str, tuple[float, float, bool]] = {
    "agent_reliability":  (0.0, 1.0, False),
    "contradiction_rate": (0.0, 0.50, True),  # fewer contradictions → higher score
}


ALL_NORMS: dict[str, dict[str, tuple[float, float, bool]]] = {
    "growth": GROWTH_NORMS,
    "profitability": PROFITABILITY_NORMS,
    "valuation": VALUATION_NORMS,
    "momentum": MOMENTUM_NORMS,
    "sentiment": SENTIMENT_NORMS,
    "event": EVENT_NORMS,
    "risk": RISK_NORMS,
    "ai_valuation": AI_VALUATION_NORMS,
    "validation": VALIDATION_NORMS,
}


def normalize_features(
    category: str,
    raw_features: dict[str, float | None],
) -> dict[str, float | None]:
    """Normalize a dict of raw features for a given category.

    Returns dict of {feature_name: normalized_score (0-1)}.
    Features not in the normalization config are passed through if already 0-1.
    """
    norms = ALL_NORMS.get(category, {})
    result: dict[str, float | None] = {}

    for name, value in raw_features.items():
        if name in norms:
            low, high, invert = norms[name]
            result[name] = _linear_normalize(value, low, high, invert)
        else:
            # Unknown feature — pass through if it looks like a 0-1 score
            result[name] = value

    return result
