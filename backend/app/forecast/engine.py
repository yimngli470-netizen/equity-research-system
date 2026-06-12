"""Forecast engine (roadmap 4.2) — fingerprint check → drivers → LLM assumptions → compile → persist.

`ensure_forecast` is the single entry point, called as a pipeline step before the analytical agents
(the valuation agent reads its output). Smart-cached exactly like the agents: the LLM call only
fires when the inputs changed (new filing / transcript / estimates / prompt edit) — in practice
roughly once per quarter per ticker.
"""

import hashlib
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.forecast import assumptions as assumptions_mod
from app.forecast.drivers import build_driver_history
from app.forecast.model import HORIZON, ScenarioPath, aggregate, compile_scenario
from app.models.estimate import AnalystEstimate
from app.models.forecast import Forecast
from app.models.stock import Stock

logger = logging.getLogger(__name__)

SMART_MAX_AGE_DAYS = 100  # a forecast on unchanged inputs is still stale after ~a quarter


async def _fingerprint(db: AsyncSession, ticker: str) -> dict:
    from app.agents import fingerprints as fp
    return {
        "financials": await fp.financial_marker(db, ticker),
        "transcript": await fp.transcript_marker(db, ticker),
        "estimates": await fp.estimates_marker(db, ticker),
        "prompt": hashlib.sha256(assumptions_mod.SYSTEM_PROMPT.encode()).hexdigest()[:12],
    }


async def _latest_forecast(db: AsyncSession, ticker: str) -> Forecast | None:
    return (
        await db.execute(
            select(Forecast).where(Forecast.ticker == ticker)
            .order_by(Forecast.as_of.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def _street_eps_near(db: AsyncSession, ticker: str, target_end: date,
                           window_days: int = 60) -> float | None:
    """Consensus EPS for the period nearest OUR q1's end date (±window). Comparing our May
    quarter to the street's August quarter is not a delta, it's a category error — when no
    consensus period aligns, return None and report 'street n/a' honestly."""
    rows = (
        await db.execute(
            select(AnalystEstimate.period_end_date, AnalystEstimate.eps_consensus)
            .where(AnalystEstimate.ticker == ticker, AnalystEstimate.eps_consensus.is_not(None))
        )
    ).all()
    best: tuple[int, float] | None = None
    for end, eps in rows:
        delta = abs((end - target_end).days)
        if delta <= window_days and (best is None or delta < best[0]):
            best = (delta, float(eps))
    return best[1] if best else None


async def ensure_forecast(db: AsyncSession, ticker: str, mode: str = "smart") -> tuple[Forecast | None, bool]:
    """Build (or reuse) the ticker's forecast. Returns (forecast_row | None, cached).

    None ⇒ not forecastable (thin history) — callers degrade gracefully."""
    ticker = ticker.upper()

    fingerprint = await _fingerprint(db, ticker)
    if mode == "smart":
        latest = await _latest_forecast(db, ticker)
        if (latest is not None
                and latest.input_fingerprint == fingerprint
                and latest.as_of >= date.today() - timedelta(days=SMART_MAX_AGE_DAYS)):
            logger.info("[forecast] %s: inputs unchanged since %s — reusing (no LLM)",
                        ticker, latest.as_of)
            return latest, True

    drivers = await build_driver_history(db, ticker)
    if drivers is None:
        logger.info("[forecast] %s: history too thin to model — skipping", ticker)
        return None, False

    raw = await assumptions_mod.generate_assumptions(db, ticker, drivers)
    scenarios_raw = raw.get("scenarios") or {}

    latest_end = drivers.latest.end
    actual_rev_last4 = [q.revenue for q in drivers.last_n(4)]
    shares_0 = drivers.latest.shares or next(
        (q.shares for q in reversed(drivers.quarters) if q.shares), None)
    if len(actual_rev_last4) < 4 or any(r is None for r in actual_rev_last4) or not shares_0:
        logger.warning("[forecast] %s: missing revenue/share base — skipping", ticker)
        return None, False

    projections: dict = {}
    aggregates: dict = {}
    for name in ("base", "bull", "bear"):
        path = ScenarioPath.from_llm(scenarios_raw.get(name) or {}, drivers.medians)
        rows = compile_scenario(path, actual_rev_last4, latest_end, shares_0)
        projections[name] = {"quarters": rows, **aggregate(rows),
                             "rationale": path.rationale,
                             "net_factor": path.net_factor,
                             "share_change_qoq": path.share_change_qoq}
        aggregates[name] = projections[name]["ntm_eps"]

    base = projections["base"]
    next_q_eps = base["quarters"][0]["eps"] if base["quarters"] else None
    q1_end = date.fromisoformat(base["quarters"][0]["end_approx"]) if base["quarters"] else date.today()
    street = await _street_eps_near(db, ticker, q1_end)
    vs_street = (round((next_q_eps - street) / abs(street), 4)
                 if (next_q_eps is not None and street) else None)

    stock = await db.get(Stock, ticker)
    today = date.today()
    row = (
        await db.execute(
            select(Forecast).where(Forecast.ticker == ticker, Forecast.as_of == today)
        )
    ).scalar_one_or_none()
    values = dict(
        archetype=stock.archetype if stock else None,
        horizon_quarters=HORIZON,
        assumptions={k: raw.get(k) for k in ("scenarios", "assumption_bases", "key_swing_factors")},
        projections=projections,
        base_next_q_eps=next_q_eps,
        base_ntm_eps=base["ntm_eps"],
        base_ntm_revenue=base["ntm_revenue"],
        street_next_q_eps=street,
        eps_vs_street_next_q=vs_street,
        input_fingerprint=fingerprint,
    )
    if row:
        for k, v in values.items():
            setattr(row, k, v)
    else:
        row = Forecast(ticker=ticker, as_of=today, status="open", **values)
        db.add(row)
    await db.commit()

    logger.info("[forecast] %s: base NTM EPS %s (bull %s / bear %s), next-q vs street %s",
                ticker, base["ntm_eps"], aggregates.get("bull"), aggregates.get("bear"),
                f"{vs_street:+.1%}" if vs_street is not None else "n/a")
    return row, False


def summarize_forecast(f: Forecast) -> str:
    """Compact text block for downstream agent contexts (valuation/debate)."""
    p = f.projections or {}
    base, bull, bear = p.get("base") or {}, p.get("bull") or {}, p.get("bear") or {}
    lines = [f"OUR MODEL (driver-based forecast, as of {f.as_of}):",
             f"  next-quarter EPS: {f.base_next_q_eps} "
             + (f"vs street {f.street_next_q_eps} ({f.eps_vs_street_next_q:+.1%})"
                if f.eps_vs_street_next_q is not None else "(street n/a)"),
             f"  NTM EPS — base {base.get('ntm_eps')} | bull {bull.get('ntm_eps')} | bear {bear.get('ntm_eps')}",
             f"  NTM revenue (base): "
             + (f"${base['ntm_revenue']/1e9:.2f}B" if base.get("ntm_revenue") else "n/a"),
             f"  base rationale: {base.get('rationale') or 'n/a'}"]
    swing = (f.assumptions or {}).get("key_swing_factors") or []
    if swing:
        lines.append("  key swing factors: " + "; ".join(str(s) for s in swing[:4]))
    return "\n".join(lines)
