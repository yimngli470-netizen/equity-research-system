"""Forecast grading (roadmap 4.2) — score our EPS vs actual vs street as quarters resolve.

Runs on each pipeline run (pull model, no scheduler), fully deterministic — no LLM: a forecasted
quarter "resolves" when a filed actual lands near its approximate end date. Each resolved quarter
records our error, the street's error at forecast time, and who was closer — the densest label
stream the calibration loop (M4b) gets, far denser than thesis hit/miss."""

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Financial
from app.models.forecast import Forecast

logger = logging.getLogger(__name__)

_MATCH_WINDOW_DAYS = 45  # filed quarter-end within this of the approximate forecast end ⇒ same quarter


async def grade_due_forecasts(db: AsyncSession, ticker: str) -> int:
    """Grade any open forecast's resolved quarters for `ticker`. Returns forecasts touched."""
    ticker = ticker.upper()
    forecasts = (
        await db.execute(
            select(Forecast).where(Forecast.ticker == ticker, Forecast.status == "open")
        )
    ).scalars().all()
    if not forecasts:
        return 0

    actuals = (
        await db.execute(
            select(Financial.period_end_date, Financial.eps)
            .where(Financial.ticker == ticker, Financial.eps.is_not(None))
            .order_by(Financial.period_end_date.asc())
        )
    ).all()
    if not actuals:
        return 0

    def actual_near(d: date) -> tuple[date, float] | None:
        best = None
        for end, eps in actuals:
            delta = abs((end - d).days)
            if delta <= _MATCH_WINDOW_DAYS and (best is None or delta < best[0]):
                best = (delta, end, eps)
        return (best[1], best[2]) if best else None

    touched = 0
    today = date.today()
    for f in forecasts:
        base_qs = ((f.projections or {}).get("base") or {}).get("quarters") or []
        if not base_qs:
            continue
        outcome = dict(f.outcome or {})
        graded = dict(outcome.get("quarters") or {})  # keyed by str(q)
        changed = False

        for q in base_qs:
            key = str(q["q"])
            if key in graded or q.get("eps") is None:
                continue
            end_approx = date.fromisoformat(q["end_approx"])
            if end_approx > today:
                continue
            match = actual_near(end_approx)
            if match is None:
                continue  # actual not filed yet — try again next run
            actual_end, actual_eps = match
            ours = float(q["eps"])
            entry = {
                "forecast_eps": ours,
                "actual_eps": actual_eps,
                "actual_period_end": actual_end.isoformat(),
                "abs_pct_err": round(abs(ours - actual_eps) / abs(actual_eps), 4) if actual_eps else None,
            }
            # Street comparison only for q1 (the consensus we snapshotted at forecast time).
            if q["q"] == 1 and f.street_next_q_eps is not None and actual_eps:
                street_err = abs(f.street_next_q_eps - actual_eps) / abs(actual_eps)
                entry["street_eps_at_forecast"] = f.street_next_q_eps
                entry["street_abs_pct_err"] = round(street_err, 4)
                entry["beat_street"] = bool(entry["abs_pct_err"] is not None
                                            and entry["abs_pct_err"] < street_err)
            graded[key] = entry
            changed = True

        if not changed:
            continue
        outcome["quarters"] = graded
        errs = [g["abs_pct_err"] for g in graded.values() if g.get("abs_pct_err") is not None]
        if errs:
            outcome["mape"] = round(sum(errs) / len(errs), 4)
        f.outcome = outcome
        # Graded once the NTM (the headline window) has fully resolved.
        if all(str(q["q"]) in graded for q in base_qs[:4]):
            f.status = "graded"
            f.graded_at = today
        touched += 1
        logger.info("[forecast] graded %s forecast %s: %d/%d quarters, mape=%s status=%s",
                    ticker, f.as_of, len(graded), len(base_qs), outcome.get("mape"), f.status)

    await db.commit()
    return touched
