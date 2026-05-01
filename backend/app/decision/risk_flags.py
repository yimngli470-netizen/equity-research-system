"""Risk flag engine — rule-based flags that surface specific concerns.

Flag levels:
  - CRITICAL: serious red flag, should override/cap the signal
  - MAJOR: notable concern, may downgrade the signal by one level
  - WATCH: informational, doesn't change the signal but worth monitoring

Each rule function receives scores + features + agent reports and returns
a list of RiskFlag dicts if the condition triggers.
"""

from dataclasses import dataclass


@dataclass
class RiskFlag:
    level: str  # 'critical', 'major', 'watch'
    rule: str  # machine-readable rule ID
    category: str  # 'valuation', 'growth', 'profitability', 'momentum', 'sentiment', 'quality'
    message: str  # human-readable explanation

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "rule": self.rule,
            "category": self.category,
            "message": self.message,
        }


def check_valuation_flags(
    scores: dict[str, float],
    features: dict[str, float],
) -> list[RiskFlag]:
    """Check for valuation-related risks."""
    flags = []

    # Extremely high P/E
    fwd_pe = features.get("forward_pe")
    if fwd_pe is not None and fwd_pe < 0.05:  # normalized: very expensive
        flags.append(RiskFlag(
            level="major",
            rule="extreme_pe",
            category="valuation",
            message="Forward P/E is extremely elevated — stock is priced for perfection",
        ))

    # PEG ratio signals overvaluation
    peg = features.get("peg_ratio")
    if peg is not None and peg < 0.1:  # normalized: PEG > 2.7
        flags.append(RiskFlag(
            level="major",
            rule="high_peg",
            category="valuation",
            message="PEG ratio suggests growth doesn't justify the valuation premium",
        ))

    # Valuation category score very low
    if scores.get("valuation", 0.5) < 0.25:
        flags.append(RiskFlag(
            level="major",
            rule="low_valuation_score",
            category="valuation",
            message="Overall valuation score is weak — stock appears expensive on multiple metrics",
        ))

    # AI valuation agent says significantly overvalued
    verdict = features.get("valuation_verdict_score")
    if verdict is not None and verdict < 0.15:
        flags.append(RiskFlag(
            level="critical",
            rule="ai_overvalued",
            category="valuation",
            message="AI valuation analysis flags stock as significantly overvalued",
        ))

    return flags


def check_growth_flags(
    scores: dict[str, float],
    features: dict[str, float],
) -> list[RiskFlag]:
    """Check for growth-related risks."""
    flags = []

    # Revenue declining YoY
    rev_yoy = features.get("revenue_yoy")
    if rev_yoy is not None and rev_yoy < 0.2:  # normalized: ~-6% YoY
        flags.append(RiskFlag(
            level="major",
            rule="revenue_decline",
            category="growth",
            message="Revenue is declining year-over-year — growth thesis may be broken",
        ))

    # Growth decelerating sharply
    accel = features.get("revenue_acceleration")
    if accel is not None and accel < 0.15:  # normalized: acceleration < -7pp
        flags.append(RiskFlag(
            level="watch",
            rule="growth_deceleration",
            category="growth",
            message="Revenue growth is decelerating — monitor for further slowdown",
        ))

    # Inconsistent growth
    consistency = features.get("growth_consistency")
    if consistency is not None and consistency < 0.3:
        flags.append(RiskFlag(
            level="watch",
            rule="inconsistent_growth",
            category="growth",
            message="Revenue growth has been inconsistent across recent quarters",
        ))

    return flags


def check_profitability_flags(
    scores: dict[str, float],
    features: dict[str, float],
) -> list[RiskFlag]:
    """Check for profitability-related risks."""
    flags = []

    # Operating margin negative
    op_margin = features.get("operating_margin")
    if op_margin is not None and op_margin < 0.05:  # normalized: roughly break-even or loss
        flags.append(RiskFlag(
            level="major",
            rule="negative_operating_margin",
            category="profitability",
            message="Operating margin is near zero or negative — company is not profitable from operations",
        ))

    # Margins compressing YoY
    gm_yoy = features.get("gross_margin_change_yoy")
    om_yoy = features.get("operating_margin_change_yoy")
    if gm_yoy is not None and gm_yoy < 0.3 and om_yoy is not None and om_yoy < 0.3:
        flags.append(RiskFlag(
            level="major",
            rule="margin_compression",
            category="profitability",
            message="Both gross and operating margins are compressing year-over-year",
        ))
    elif om_yoy is not None and om_yoy < 0.2:
        flags.append(RiskFlag(
            level="watch",
            rule="op_margin_declining",
            category="profitability",
            message="Operating margin declining year-over-year",
        ))

    # Negative operating leverage
    leverage = features.get("operating_leverage")
    if leverage is not None and leverage < 0.2:  # normalized: < 0.8x
        flags.append(RiskFlag(
            level="watch",
            rule="negative_leverage",
            category="profitability",
            message="Negative operating leverage — costs growing faster than revenue",
        ))

    # Poor FCF conversion
    fcf_conv = features.get("fcf_conversion")
    if fcf_conv is not None and fcf_conv < 0.1:
        flags.append(RiskFlag(
            level="watch",
            rule="low_fcf_conversion",
            category="quality",
            message="Free cash flow conversion is poor — earnings quality concern",
        ))

    return flags


def check_momentum_flags(
    scores: dict[str, float],
    features: dict[str, float],
) -> list[RiskFlag]:
    """Check for momentum/price-related risks."""
    flags = []

    # Severe 3-month decline
    mom_3m = features.get("momentum_3m")
    if mom_3m is not None and mom_3m < 0.15:  # normalized: ~-14% over 3 months
        flags.append(RiskFlag(
            level="major",
            rule="sharp_decline_3m",
            category="momentum",
            message="Stock has declined sharply over the past 3 months — potential trend breakdown",
        ))

    # 12-month severe decline
    mom_12m = features.get("momentum_12m")
    if mom_12m is not None and mom_12m < 0.1:
        flags.append(RiskFlag(
            level="critical",
            rule="severe_decline_12m",
            category="momentum",
            message="Stock has suffered a severe 12-month decline — structural issue likely",
        ))

    # Divergence: short-term up but long-term down
    mom_1m = features.get("momentum_1m")
    if mom_1m is not None and mom_12m is not None and mom_1m > 0.7 and mom_12m < 0.3:
        flags.append(RiskFlag(
            level="watch",
            rule="dead_cat_bounce",
            category="momentum",
            message="Short-term bounce within a long-term downtrend — could be a dead cat bounce",
        ))

    return flags


def check_sentiment_flags(
    scores: dict[str, float],
    features: dict[str, float],
) -> list[RiskFlag]:
    """Check for sentiment/news-related risks."""
    flags = []

    # Very negative news sentiment
    sentiment = features.get("news_sentiment")
    if sentiment is not None and sentiment < 0.15:  # normalized: strongly negative
        flags.append(RiskFlag(
            level="watch",
            rule="negative_sentiment",
            category="sentiment",
            message="Recent news sentiment is strongly negative",
        ))

    # High industry risk
    ind_risk = features.get("industry_risk_avg")
    if ind_risk is not None and ind_risk < 0.2:  # inverted: high risk = low score
        flags.append(RiskFlag(
            level="watch",
            rule="high_industry_risk",
            category="sentiment",
            message="Industry-level risks are elevated (regulation, disruption, cyclicality)",
        ))

    # Weak moat
    moat = features.get("moat_strength")
    if moat is not None and moat < 0.3:
        flags.append(RiskFlag(
            level="watch",
            rule="weak_moat",
            category="sentiment",
            message="Competitive moat assessed as weak — vulnerable to competition",
        ))

    return flags


def check_quality_flags(
    scores: dict[str, float],
    features: dict[str, float],
) -> list[RiskFlag]:
    """Check for earnings quality risks."""
    flags = []

    # Low earnings quality from AI agent
    eq = features.get("earnings_quality")
    if eq is not None and eq < 0.3:
        flags.append(RiskFlag(
            level="major",
            rule="low_earnings_quality",
            category="quality",
            message="AI analysis flags low earnings quality — results may not be sustainable",
        ))

    # Forward outlook deteriorating
    fwd_rev = features.get("fwd_revenue_signal")
    fwd_margin = features.get("fwd_margin_signal")
    if fwd_rev is not None and fwd_rev < 0.2 and fwd_margin is not None and fwd_margin < 0.2:
        flags.append(RiskFlag(
            level="critical",
            rule="deteriorating_outlook",
            category="quality",
            message="Forward outlook is deteriorating on both revenue and margins",
        ))
    elif fwd_rev is not None and fwd_rev < 0.2:
        flags.append(RiskFlag(
            level="watch",
            rule="fwd_revenue_weak",
            category="quality",
            message="Forward revenue outlook is decelerating",
        ))

    return flags


def check_divergence_flags(
    scores: dict[str, float],
) -> list[RiskFlag]:
    """Check for divergences between scoring categories that may indicate risk."""
    flags = []

    growth = scores.get("growth", 0.5)
    valuation = scores.get("valuation", 0.5)
    profitability = scores.get("profitability", 0.5)

    # High growth but terrible valuation — priced for perfection
    if growth > 0.8 and valuation < 0.3:
        flags.append(RiskFlag(
            level="watch",
            rule="growth_valuation_gap",
            category="valuation",
            message="Strong growth is fully priced in — limited margin for error",
        ))

    # High valuation score (cheap) but bad profitability — value trap risk
    if valuation > 0.75 and profitability < 0.3:
        flags.append(RiskFlag(
            level="major",
            rule="value_trap",
            category="quality",
            message="Stock looks cheap but profitability is poor — potential value trap",
        ))

    # Everything is middling — low conviction
    all_scores = [scores.get(k, 0.5) for k in ["growth", "profitability", "valuation", "momentum", "sentiment", "event"]]
    if all(0.35 < s < 0.65 for s in all_scores):
        flags.append(RiskFlag(
            level="watch",
            rule="low_conviction",
            category="quality",
            message="All scoring categories are near-neutral — low conviction signal",
        ))

    return flags


def check_transcript_flags(
    scores: dict[str, float],
    features: dict[str, float],
) -> list[RiskFlag]:
    """Check for transcript/validation-related risks."""
    flags = []

    # Low agent reliability from validation agent
    reliability = features.get("agent_reliability")
    if reliability is not None and reliability < 0.4:
        flags.append(RiskFlag(
            level="watch",
            rule="low_agent_reliability",
            category="quality",
            message="Validation agent found significant contradictions in agent outputs — treat analysis with caution",
        ))

    # Management tone is evasive/defensive on earnings call
    tone = features.get("management_tone")
    if tone is not None and tone < 0.2:
        flags.append(RiskFlag(
            level="watch",
            rule="management_evasive",
            category="quality",
            message="Management tone on earnings call was evasive or defensive — potential red flag",
        ))

    # Consistent EPS misses
    beat_rate = features.get("eps_beat_rate")
    if beat_rate is not None and beat_rate < 0.25:
        flags.append(RiskFlag(
            level="major",
            rule="consistent_misses",
            category="quality",
            message="Company has missed EPS estimates in 3+ of the last 4 quarters",
        ))

    return flags


def evaluate_risk_flags(
    scores: dict[str, float],
    features: dict[str, float],
) -> list[RiskFlag]:
    """Run all risk flag checks and return combined list, sorted by severity."""
    flags: list[RiskFlag] = []

    flags.extend(check_valuation_flags(scores, features))
    flags.extend(check_growth_flags(scores, features))
    flags.extend(check_profitability_flags(scores, features))
    flags.extend(check_momentum_flags(scores, features))
    flags.extend(check_sentiment_flags(scores, features))
    flags.extend(check_quality_flags(scores, features))
    flags.extend(check_divergence_flags(scores))
    flags.extend(check_transcript_flags(scores, features))

    # Sort: critical first, then major, then watch
    level_order = {"critical": 0, "major": 1, "watch": 2}
    flags.sort(key=lambda f: level_order.get(f.level, 3))

    return flags
