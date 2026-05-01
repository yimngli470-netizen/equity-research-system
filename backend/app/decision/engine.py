"""Decision engine — produces a final signal by combining scores with risk flags.

The decision engine:
1. Takes the raw composite score and signal from the scoring system
2. Runs all risk flag checks
3. Adjusts the signal based on risk flags:
   - CRITICAL flags cap the signal (no higher than HOLD)
   - MAJOR flags downgrade the signal by one level
4. Determines confidence based on data completeness and flag count
5. Generates human-readable reasoning
6. Saves the decision to stock_decisions table
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision.risk_flags import RiskFlag, evaluate_risk_flags
from app.models.decision import StockDecision
from app.models.score import QuantFeature, StockScore

logger = logging.getLogger(__name__)

SIGNAL_LEVELS = ["SELL", "REDUCE", "HOLD", "BUY", "STRONG_BUY"]


def _downgrade_signal(signal: str, steps: int = 1) -> str:
    """Downgrade a signal by N steps."""
    idx = SIGNAL_LEVELS.index(signal) if signal in SIGNAL_LEVELS else 2
    new_idx = max(0, idx - steps)
    return SIGNAL_LEVELS[new_idx]


def _cap_signal(signal: str, max_signal: str) -> str:
    """Cap a signal at a maximum level."""
    idx = SIGNAL_LEVELS.index(signal) if signal in SIGNAL_LEVELS else 2
    max_idx = SIGNAL_LEVELS.index(max_signal) if max_signal in SIGNAL_LEVELS else 2
    return SIGNAL_LEVELS[min(idx, max_idx)]


def _assess_confidence(
    feature_count: int,
    flags: list[RiskFlag],
    scores: dict[str, float],
    features: dict[str, float] | None = None,
) -> str:
    """Assess confidence in the signal based on data completeness and flags."""
    # Low confidence if few features (missing agent reports)
    if feature_count < 35:
        return "low"

    # Low confidence if many flags
    critical_count = sum(1 for f in flags if f.level == "critical")
    major_count = sum(1 for f in flags if f.level == "major")

    if critical_count >= 2:
        return "low"
    if critical_count >= 1 or major_count >= 3:
        return "moderate"

    # Validation-based confidence modifier: low reliability → downgrade
    if features:
        reliability = features.get("agent_reliability")
        if reliability is not None and reliability < 0.5:
            return "low"
        contradiction_rate = features.get("contradiction_rate")
        if contradiction_rate is not None and contradiction_rate > 0.3:
            return "moderate"

    # Check for extreme scores (very high conviction either way)
    composite_values = list(scores.values())
    if all(v > 0.7 for v in composite_values) or all(v < 0.3 for v in composite_values):
        return "high"

    # Decent data coverage, not too many flags
    if feature_count >= 45 and major_count <= 1:
        return "high"

    return "moderate"


def _build_reasoning(
    raw_signal: str,
    final_signal: str,
    scores: dict[str, float],
    flags: list[RiskFlag],
    confidence: str,
) -> str:
    """Generate human-readable reasoning for the decision."""
    parts = []

    # Lead with the final signal
    if final_signal == raw_signal:
        parts.append(f"Signal: {final_signal} (no adjustment from risk analysis).")
    else:
        parts.append(f"Signal adjusted from {raw_signal} to {final_signal} due to risk flags.")

    # Highlight strongest and weakest categories
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = sorted_scores[0]
    bottom = sorted_scores[-1]
    parts.append(f"Strongest: {top[0]} ({top[1]:.2f}). Weakest: {bottom[0]} ({bottom[1]:.2f}).")

    # Summarize flags
    critical_count = sum(1 for f in flags if f.level == "critical")
    major_count = sum(1 for f in flags if f.level == "major")
    watch_count = sum(1 for f in flags if f.level == "watch")

    if flags:
        flag_parts = []
        if critical_count:
            flag_parts.append(f"{critical_count} critical")
        if major_count:
            flag_parts.append(f"{major_count} major")
        if watch_count:
            flag_parts.append(f"{watch_count} watch")
        parts.append(f"Risk flags: {', '.join(flag_parts)}.")
    else:
        parts.append("No risk flags triggered.")

    parts.append(f"Confidence: {confidence}.")

    return " ".join(parts)


@dataclass
class DecisionResult:
    ticker: str
    date: date
    raw_signal: str
    raw_composite: float
    final_signal: str
    confidence: str
    risk_flags: list[dict]
    reasoning: str
    scores: dict[str, float]


async def run_decision(
    db: AsyncSession,
    ticker: str,
) -> DecisionResult:
    """Run the decision engine for a ticker.

    Requires scoring to have been run first (reads from stock_scores + quant_features).
    """
    today = date.today()

    # Fetch latest score
    score_result = await db.execute(
        select(StockScore)
        .where(StockScore.ticker == ticker)
        .order_by(StockScore.date.desc())
        .limit(1)
    )
    score = score_result.scalar_one_or_none()

    if not score:
        raise ValueError(f"No score found for {ticker}. Run scoring first.")

    scores = {
        "growth": score.growth_score,
        "profitability": score.profitability_score,
        "valuation": score.valuation_score,
        "momentum": score.momentum_score,
        "sentiment": score.sentiment_score,
        "risk": score.risk_score,
        "event": score.event_score,
    }
    raw_signal = score.signal
    raw_composite = score.composite_score

    # Fetch latest features as a flat dict
    feat_result = await db.execute(
        select(QuantFeature)
        .where(QuantFeature.ticker == ticker)
        .order_by(QuantFeature.date.desc())
        .limit(100)
    )
    all_features = feat_result.scalars().all()

    # Only use the latest date
    features: dict[str, float] = {}
    feature_count = 0
    if all_features:
        latest_date = all_features[0].date
        for f in all_features:
            if f.date == latest_date:
                features[f.feature_name] = f.feature_value
                feature_count += 1

    # Run risk flags
    flags = evaluate_risk_flags(scores, features)

    # Adjust signal based on flags
    final_signal = raw_signal

    critical_flags = [f for f in flags if f.level == "critical"]
    major_flags = [f for f in flags if f.level == "major"]

    # Critical flags: cap at HOLD (never recommend buying with critical risks)
    if critical_flags:
        final_signal = _cap_signal(final_signal, "HOLD")

    # Major flags: each one downgrades by one step (max 2 downgrades from major)
    major_downgrades = min(len(major_flags), 2)
    if major_downgrades > 0:
        final_signal = _downgrade_signal(final_signal, major_downgrades)

    # Assess confidence
    confidence = _assess_confidence(feature_count, flags, scores, features)

    # Build reasoning
    reasoning = _build_reasoning(raw_signal, final_signal, scores, flags, confidence)

    # Save to DB
    flag_dicts = [f.to_dict() for f in flags]

    existing = await db.execute(
        select(StockDecision).where(
            StockDecision.ticker == ticker,
            StockDecision.date == today,
        )
    )
    row = existing.scalar_one_or_none()

    if row:
        row.raw_signal = raw_signal
        row.raw_composite = raw_composite
        row.final_signal = final_signal
        row.confidence = confidence
        row.risk_flags = flag_dicts
        row.reasoning = reasoning
    else:
        db.add(StockDecision(
            ticker=ticker,
            date=today,
            raw_signal=raw_signal,
            raw_composite=raw_composite,
            final_signal=final_signal,
            confidence=confidence,
            risk_flags=flag_dicts,
            reasoning=reasoning,
        ))

    await db.commit()

    logger.info(
        "[decision] %s → raw=%s final=%s confidence=%s flags=%d",
        ticker, raw_signal, final_signal, confidence, len(flags),
    )

    return DecisionResult(
        ticker=ticker,
        date=today,
        raw_signal=raw_signal,
        raw_composite=raw_composite,
        final_signal=final_signal,
        confidence=confidence,
        risk_flags=flag_dicts,
        reasoning=reasoning,
        scores=scores,
    )
