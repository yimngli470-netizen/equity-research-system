"""Composite score calculator.

Pulls hard + AI features, normalizes them, computes category scores,
then combines with configurable weights into a single composite score.
Saves results to quant_features and stock_scores tables.
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.score import QuantFeature, StockScore
from app.quant.ai_features import extract_all_ai_features
from app.quant.hard_features import extract_all_hard_features
from app.quant.normalizer import normalize_features
from app.scoring.weights import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    ScoringWeights,
    SignalThresholds,
    score_to_signal,
)

logger = logging.getLogger(__name__)


# How hard-quant categories map to scoring categories:
# growth → growth_score
# profitability → profitability_score
# valuation (hard) + ai_valuation → valuation_score (blended)
# momentum → momentum_score
# sentiment → sentiment_score
# risk → risk_score
# event → event_score


def _category_score(normalized: dict[str, float | None]) -> float | None:
    """Average of all non-None normalized features in a category."""
    values = [v for v in normalized.values() if v is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


@dataclass
class ScoringResult:
    ticker: str
    date: date
    growth_score: float
    profitability_score: float
    valuation_score: float
    momentum_score: float
    sentiment_score: float
    risk_score: float
    event_score: float
    composite_score: float
    signal: str
    feature_count: int


async def calculate_score(
    db: AsyncSession,
    ticker: str,
    weights: ScoringWeights | None = None,
    thresholds: SignalThresholds | None = None,
) -> ScoringResult:
    """Calculate the composite score for a ticker.

    1. Extract hard + AI features
    2. Normalize all features to 0-1
    3. Compute category scores (average of features per category)
    4. Blend valuation: 50% hard multiples + 50% AI valuation assessment
    5. Weighted sum → composite score
    6. Map to signal
    7. Save features + score to DB
    """
    w = weights or DEFAULT_WEIGHTS
    t = thresholds or DEFAULT_THRESHOLDS
    today = date.today()

    # Step 1: Extract features
    hard = await extract_all_hard_features(db, ticker)
    ai = await extract_all_ai_features(db, ticker)

    # Step 2: Normalize
    norm_growth = normalize_features("growth", hard.get("growth", {}))
    norm_profit = normalize_features("profitability", hard.get("profitability", {}))
    norm_valuation_hard = normalize_features("valuation", hard.get("valuation", {}))
    norm_momentum = normalize_features("momentum", hard.get("momentum", {}))
    norm_sentiment = normalize_features("sentiment", ai.get("sentiment", {}))
    norm_event = normalize_features("event", ai.get("event", {}))
    norm_risk = normalize_features("risk", ai.get("risk", {}))
    norm_valuation_ai = normalize_features("ai_valuation", ai.get("ai_valuation", {}))

    # Step 3: Category scores
    growth_score = _category_score(norm_growth)
    profitability_score = _category_score(norm_profit)
    valuation_hard_score = _category_score(norm_valuation_hard)
    valuation_ai_score = _category_score(norm_valuation_ai)
    momentum_score = _category_score(norm_momentum)
    sentiment_score = _category_score(norm_sentiment)
    risk_score = _category_score(norm_risk)
    event_score = _category_score(norm_event)

    # Step 4: Blend valuation (50/50 hard multiples and AI assessment)
    if valuation_hard_score is not None and valuation_ai_score is not None:
        valuation_score = round(0.5 * valuation_hard_score + 0.5 * valuation_ai_score, 4)
    elif valuation_hard_score is not None:
        valuation_score = valuation_hard_score
    elif valuation_ai_score is not None:
        valuation_ai_score
        valuation_score = valuation_ai_score
    else:
        valuation_score = None

    # Use 0.5 (neutral) for any missing category
    scores = {
        "growth": growth_score if growth_score is not None else 0.5,
        "profitability": profitability_score if profitability_score is not None else 0.5,
        "valuation": valuation_score if valuation_score is not None else 0.5,
        "momentum": momentum_score if momentum_score is not None else 0.5,
        "sentiment": sentiment_score if sentiment_score is not None else 0.5,
        "risk": risk_score if risk_score is not None else 0.5,
        "event": event_score if event_score is not None else 0.5,
    }

    # Step 5: Weighted composite
    weight_dict = w.as_dict()
    composite = sum(scores[cat] * weight_dict[cat] for cat in scores)
    composite = round(composite, 4)

    # Step 6: Signal
    signal = score_to_signal(composite, t)

    # Step 7: Save features to quant_features table
    all_features: list[tuple[str, str, float | None]] = []
    for name, val in norm_growth.items():
        all_features.append(("growth", name, val))
    for name, val in norm_profit.items():
        all_features.append(("profitability", name, val))
    for name, val in norm_valuation_hard.items():
        all_features.append(("valuation", name, val))
    for name, val in norm_momentum.items():
        all_features.append(("momentum", name, val))
    for name, val in norm_sentiment.items():
        all_features.append(("sentiment", name, val))
    for name, val in norm_event.items():
        all_features.append(("event", name, val))
    for name, val in norm_risk.items():
        all_features.append(("risk", name, val))
    for name, val in norm_valuation_ai.items():
        all_features.append(("ai_valuation", name, val))

    feature_count = 0
    for category, feature_name, value in all_features:
        if value is None:
            continue
        feature_count += 1
        stmt = (
            insert(QuantFeature)
            .values(
                ticker=ticker,
                date=today,
                feature_name=feature_name,
                feature_value=value,
                category=category,
            )
            .on_conflict_do_update(
                constraint="uq_qf_ticker_date_feature",
                set_={"feature_value": value, "category": category},
            )
        )
        await db.execute(stmt)

    # Save composite score to stock_scores table
    existing = await db.execute(
        select(StockScore).where(
            StockScore.ticker == ticker,
            StockScore.date == today,
        )
    )
    row = existing.scalar_one_or_none()

    if row:
        row.growth_score = scores["growth"]
        row.profitability_score = scores["profitability"]
        row.valuation_score = scores["valuation"]
        row.momentum_score = scores["momentum"]
        row.sentiment_score = scores["sentiment"]
        row.risk_score = scores["risk"]
        row.event_score = scores["event"]
        row.composite_score = composite
        row.signal = signal
    else:
        db.add(
            StockScore(
                ticker=ticker,
                date=today,
                growth_score=scores["growth"],
                profitability_score=scores["profitability"],
                valuation_score=scores["valuation"],
                momentum_score=scores["momentum"],
                sentiment_score=scores["sentiment"],
                risk_score=scores["risk"],
                event_score=scores["event"],
                composite_score=composite,
                signal=signal,
            )
        )

    await db.commit()

    logger.info(
        "[scoring] %s → composite=%.3f signal=%s (%d features)",
        ticker, composite, signal, feature_count,
    )

    return ScoringResult(
        ticker=ticker,
        date=today,
        growth_score=scores["growth"],
        profitability_score=scores["profitability"],
        valuation_score=scores["valuation"],
        momentum_score=scores["momentum"],
        sentiment_score=scores["sentiment"],
        risk_score=scores["risk"],
        event_score=scores["event"],
        composite_score=composite,
        signal=signal,
        feature_count=feature_count,
    )
