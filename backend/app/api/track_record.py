"""Track-record API (roadmap 5.2) — makes the accountability loop visible.

Read-only registered event scores, frozen legacy grades and separate dated market marks.
Only explicitly registered events accrue new fundamental grades under accountability-v2.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.forecast import Forecast
from app.models.thesis import StockThesis
from app.thesis.calibration import compute_calibration
from app.thesis.market_marks import latest_market_marks, LEGACY_GRADING_NOTICE, MARK_NOTE

router = APIRouter(prefix="/api/track-record", tags=["track-record"])


def _thesis_row(t: StockThesis, mark: dict | None = None) -> dict:
    o = t.outcome or {}
    returns = mark or o
    return {
        "id": t.id,
        "revision_of": t.revision_of,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "writer_version": t.writer_version,
        "evidence_id": t.evidence_id,
        "grading_note": LEGACY_GRADING_NOTICE,
        "market_mark": mark,
        "return_source": "separate_market_mark" if mark else "frozen_legacy_outcome",
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
        "realized_return": returns.get("realized_return"),
        "excess_return": returns.get("excess_return"),
        "n_kill_criteria": len(t.kill_criteria or []),
        "n_graded_predictions": len((o.get("predictions") or {})),
    }


def _forecast_row(f: Forecast) -> dict:
    o = f.outcome or {}
    qs = (o.get("quarters") or {})
    beats = [v.get("beat_street") for v in qs.values() if "beat_street" in v]
    return {
        "id": f.id,
        "revision_of": f.revision_of,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "writer_version": f.writer_version,
        "evidence_id": f.evidence_id,
        "grading_note": LEGACY_GRADING_NOTICE,
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
    marks = await latest_market_marks(db)
    return [_thesis_row(t, marks.get(t.id)) for t in rows]


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
    marks = await latest_market_marks(db)
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
        "mean_marked_excess_return": avg([m["excess_return"] for m in marks.values()]),
        "theses_with_market_marks": len(marks),
        "market_mark_note": MARK_NOTE,
        "mean_hit_rate": avg(hit_rates),
        "forecasts_total": len(forecasts),
        "forecasts_graded": len(fc_graded),
        "forecast_mape": avg(mapes),
        "note": LEGACY_GRADING_NOTICE,
    }


@router.get("/calibration")
async def calibration(db: AsyncSession = Depends(get_db)):
    """Conviction calibration (3.3) — re-exposed here so the track-record page is one stop."""
    return await compute_calibration(db)


@router.get("/events")
async def event_scores(db: AsyncSession = Depends(get_db)):
    """Registered primary probabilities, coverage and resolving evidence lineage."""
    from app.accountability.store import probability_report
    return await probability_report(db)
