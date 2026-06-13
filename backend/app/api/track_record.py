"""Track-record API (roadmap 5.2) — makes the accountability loop visible.

Read-only views over the journal + forecast grading + calibration: the thesis ledger (with
benchmark-relative outcomes), forecast accuracy (ours vs street vs actual), and the calibration
curve. Much of it reads "pending" early — that is the point: the loop is wired and accruing, and
this is where it surfaces as graded history lands.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.forecast import Forecast
from app.models.thesis import StockThesis
from app.thesis.calibration import compute_calibration

router = APIRouter(prefix="/api/track-record", tags=["track-record"])


def _thesis_row(t: StockThesis) -> dict:
    o = t.outcome or {}
    return {
        "ticker": t.ticker,
        "as_of": str(t.as_of),
        "archetype": t.archetype,
        "leaning": t.leaning,
        "conviction": t.conviction,
        "decision_signal": t.decision_signal,
        "price_at": t.price_at,
        "status": t.status,
        "graded_at": str(t.graded_at) if t.graded_at else None,
        "hit_rate": o.get("hit_rate"),
        "realized_return": o.get("realized_return"),
        "excess_return": o.get("excess_return"),
        "n_kill_criteria": len(t.kill_criteria or []),
        "n_graded_predictions": len((o.get("predictions") or {})),
    }


def _forecast_row(f: Forecast) -> dict:
    o = f.outcome or {}
    qs = (o.get("quarters") or {})
    beats = [v.get("beat_street") for v in qs.values() if "beat_street" in v]
    return {
        "ticker": f.ticker,
        "as_of": str(f.as_of),
        "archetype": f.archetype,
        "base_ntm_eps": f.base_ntm_eps,
        "base_next_q_eps": f.base_next_q_eps,
        "street_next_q_eps": f.street_next_q_eps,
        "eps_vs_street_next_q": f.eps_vs_street_next_q,
        "status": f.status,
        "mape": o.get("mape"),
        "n_quarters_resolved": len(qs),
        "beat_street": (sum(1 for b in beats if b) / len(beats)) if beats else None,
    }


@router.get("/theses")
async def list_theses(db: AsyncSession = Depends(get_db)):
    """The thesis ledger, newest first — the dated calls and how they're scoring."""
    rows = (
        await db.execute(select(StockThesis).order_by(StockThesis.as_of.desc(), StockThesis.id.desc()))
    ).scalars().all()
    return [_thesis_row(t) for t in rows]


@router.get("/forecasts")
async def list_forecasts(db: AsyncSession = Depends(get_db)):
    """Forecast ledger — our EPS calls vs street, and accuracy as quarters resolve."""
    rows = (
        await db.execute(select(Forecast).order_by(Forecast.as_of.desc(), Forecast.id.desc()))
    ).scalars().all()
    return [_forecast_row(f) for f in rows]


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)):
    """Headline accountability numbers — the aggregates the track-record page leads with."""
    theses = (await db.execute(select(StockThesis))).scalars().all()
    forecasts = (await db.execute(select(Forecast))).scalars().all()

    graded = [t for t in theses if t.status == "graded"]
    excess = [t.outcome["excess_return"] for t in graded
              if t.outcome and t.outcome.get("excess_return") is not None]
    hit_rates = [t.outcome["hit_rate"] for t in graded
                 if t.outcome and t.outcome.get("hit_rate") is not None]
    fc_graded = [f for f in forecasts if f.status == "graded"]
    mapes = [f.outcome["mape"] for f in fc_graded if f.outcome and f.outcome.get("mape") is not None]

    def avg(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    return {
        "theses_total": len(theses),
        "theses_open": sum(1 for t in theses if t.status == "open"),
        "theses_graded": len(graded),
        "mean_excess_return": avg(excess),
        "mean_hit_rate": avg(hit_rates),
        "forecasts_total": len(forecasts),
        "forecasts_graded": len(fc_graded),
        "forecast_mape": avg(mapes),
        "note": ("The loop is wired and accruing; graded counts grow as kill-criteria dates pass "
                 "and forecast quarters file. Early reads are mostly 'open' by design."),
    }


@router.get("/calibration")
async def calibration(db: AsyncSession = Depends(get_db)):
    """Conviction calibration (3.3) — re-exposed here so the track-record page is one stop."""
    return await compute_calibration(db)
