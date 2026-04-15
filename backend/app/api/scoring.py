"""Scoring API — trigger score calculation and view weights."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.scoring.calculator import calculate_score
from app.scoring.weights import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS

router = APIRouter(prefix="/api/scoring", tags=["scoring"])


class ScoreRequest(BaseModel):
    ticker: str
    weights: dict[str, float] | None = None  # override default weights


class ScoreResponse(BaseModel):
    ticker: str
    date: str
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


@router.post("/run", response_model=ScoreResponse)
async def run_scoring(request: ScoreRequest, db: AsyncSession = Depends(get_db)):
    """Calculate composite score for a ticker.

    Extracts hard quant + AI-derived features, normalizes, and computes
    weighted composite score. Saves to quant_features and stock_scores tables.
    """
    from app.scoring.weights import ScoringWeights

    weights = DEFAULT_WEIGHTS
    if request.weights:
        weights = ScoringWeights(**request.weights)
        if not weights.validate():
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"Weights must sum to 1.0, got {sum(weights.as_dict().values()):.3f}",
            )

    result = await calculate_score(
        db=db,
        ticker=request.ticker.upper(),
        weights=weights,
    )

    return ScoreResponse(
        ticker=result.ticker,
        date=str(result.date),
        growth_score=result.growth_score,
        profitability_score=result.profitability_score,
        valuation_score=result.valuation_score,
        momentum_score=result.momentum_score,
        sentiment_score=result.sentiment_score,
        risk_score=result.risk_score,
        event_score=result.event_score,
        composite_score=result.composite_score,
        signal=result.signal,
        feature_count=result.feature_count,
    )


@router.get("/weights")
async def get_weights():
    """Return current default scoring weights and signal thresholds."""
    return {
        "weights": DEFAULT_WEIGHTS.as_dict(),
        "thresholds": {
            "strong_buy": DEFAULT_THRESHOLDS.strong_buy,
            "buy": DEFAULT_THRESHOLDS.buy,
            "hold": DEFAULT_THRESHOLDS.hold_upper,
            "reduce": DEFAULT_THRESHOLDS.reduce,
        },
    }


class FeatureResponse(BaseModel):
    feature_name: str
    feature_value: float
    category: str


@router.get("/features/{ticker}", response_model=list[FeatureResponse])
async def get_features(ticker: str, db: AsyncSession = Depends(get_db)):
    """Return the latest normalized features for a ticker."""
    from sqlalchemy import select

    from app.models.score import QuantFeature

    result = await db.execute(
        select(QuantFeature)
        .where(QuantFeature.ticker == ticker.upper())
        .order_by(QuantFeature.date.desc(), QuantFeature.category, QuantFeature.feature_name)
        .limit(100)
    )
    features = result.scalars().all()

    # Only return the latest date's features
    if not features:
        return []

    latest_date = features[0].date
    return [
        FeatureResponse(
            feature_name=f.feature_name,
            feature_value=f.feature_value,
            category=f.category,
        )
        for f in features
        if f.date == latest_date
    ]
