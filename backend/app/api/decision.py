"""Decision API — run decision engine and view results."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.decision.engine import run_decision
from app.models.decision import StockDecision
from app.thesis.calibration import compute_calibration

router = APIRouter(prefix="/api/decision", tags=["decision"])


class DecisionRequest(BaseModel):
    ticker: str


class RiskFlagResponse(BaseModel):
    level: str
    rule: str
    category: str
    message: str


class DecisionResponse(BaseModel):
    ticker: str
    date: str
    raw_signal: str
    raw_composite: float
    final_signal: str
    confidence: str
    risk_flags: list[RiskFlagResponse]
    reasoning: str
    scores: dict[str, float]
    judge_leaning: str | None = None
    judge_conviction: float | None = None
    position_sizing: dict | None = None
    price_target: dict | None = None


@router.post("/run", response_model=DecisionResponse)
async def run_decision_endpoint(
    request: DecisionRequest, db: AsyncSession = Depends(get_db)
):
    """Run the decision engine for a ticker.

    Requires scoring to have been run first. Takes the composite score,
    evaluates risk flags, adjusts the signal, and returns the final decision.
    """
    try:
        result = await run_decision(db, request.ticker.upper())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DecisionResponse(
        ticker=result.ticker,
        date=str(result.date),
        raw_signal=result.raw_signal,
        raw_composite=result.raw_composite,
        final_signal=result.final_signal,
        confidence=result.confidence,
        risk_flags=[
            RiskFlagResponse(**f) for f in result.risk_flags
        ],
        reasoning=result.reasoning,
        scores=result.scores,
        judge_leaning=result.judge_leaning,
        judge_conviction=result.judge_conviction,
        position_sizing=result.position_sizing,
        price_target=result.price_target,
    )


@router.get("/calibration")
async def get_calibration(db: AsyncSession = Depends(get_db)):
    """Calibration over the graded thesis history (roadmap 3.3): a Brier-style score + reliability
    curve, overall and per archetype. The answer to 'when it says 70%, how often is it right?'"""
    return await compute_calibration(db)


@router.get("/{ticker}/latest", response_model=DecisionResponse | None)
async def get_latest_decision(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get the most recent decision for a ticker."""
    result = await db.execute(
        select(StockDecision)
        .where(StockDecision.ticker == ticker.upper())
        .order_by(StockDecision.date.desc())
        .limit(1)
    )
    decision = result.scalar_one_or_none()
    if not decision:
        return None

    # We need to reconstruct scores from stock_scores for the response
    from app.models.score import StockScore

    score_result = await db.execute(
        select(StockScore)
        .where(StockScore.ticker == ticker.upper())
        .order_by(StockScore.date.desc())
        .limit(1)
    )
    score = score_result.scalar_one_or_none()
    scores = {}
    if score:
        scores = {
            "growth": score.growth_score,
            "profitability": score.profitability_score,
            "valuation": score.valuation_score,
            "momentum": score.momentum_score,
            "sentiment": score.sentiment_score,
            "risk": score.risk_score,
            "event": score.event_score,
        }

    return DecisionResponse(
        ticker=decision.ticker,
        date=str(decision.date),
        raw_signal=decision.raw_signal,
        raw_composite=decision.raw_composite,
        final_signal=decision.final_signal,
        confidence=decision.confidence,
        risk_flags=[RiskFlagResponse(**f) for f in decision.risk_flags],
        reasoning=decision.reasoning,
        scores=scores,
        judge_leaning=decision.judge_leaning,
        judge_conviction=decision.judge_conviction,
        position_sizing=decision.position_sizing,
        price_target=await _latest_price_target(db, decision.ticker),
    )


async def _latest_price_target(db: AsyncSession, ticker: str) -> dict | None:
    from app.models.price_target import PriceTarget

    pt = (
        await db.execute(
            select(PriceTarget).where(PriceTarget.ticker == ticker)
            .order_by(PriceTarget.as_of.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if pt is None:
        return None
    return {
        "fair_value": pt.fair_value,
        "price_target": pt.price_target,
        "horizon_months": pt.horizon_months,
        "upside": pt.upside,
        "probabilities": pt.probabilities,
        "method": pt.method,
        "wacc": pt.wacc,
        "street_target_mean": pt.street_target_mean,
    }
