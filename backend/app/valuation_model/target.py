"""Price target assembly (roadmap 4.3) — scenario-weighted, method-blended, fully auditable.

    PT(12m) = [ Σ_s P(s) × ( w_dcf × DCF_s + (1−w_dcf) × Multiple_s ) ] × (1 + cost_of_equity)

- P(s): the judge's rubric-anchored scenario_probabilities (the ONE judgment input — everything
  else here is measured or declared). Fallback mapping from leaning/conviction for older reports.
- w_dcf per archetype: cyclicals anchor on the normalized-earnings MULTIPLE (a DCF off peak
  earnings is a trap); secular growers anchor on the DCF.
- Multiple leg: cyclical basis → normalized mid-cycle EPS × own through-cycle median P/E;
  otherwise scenario NTM EPS × peer-median forward P/E (own as fallback).
Every component lands in the persisted row — the PT is reproducible arithmetic, not a vibe.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.measurement.normalized_earnings import compute_normalized_earnings
from app.models.analysis import AnalysisReport
from app.models.financial import Financial
from app.models.forecast import Forecast
from app.models.peer import PeerWeight
from app.models.price import DailyPrice
from app.models.price_target import PriceTarget
from app.models.stock import Stock
from app.models.valuation import Valuation
from app.valuation_model.dcf import (DEFAULT_TERMINAL_G, TERMINAL_G, historical_fcf_conversion,
                                     run_dcf, sensitivity_grid)
from app.valuation_model.wacc import build_wacc

logger = logging.getLogger(__name__)

# DCF weight in the method blend, per archetype (the rest goes to the multiple leg).
W_DCF = {
    "cyclical-commodity": 0.30,
    "deep-value-turnaround": 0.40,
    "financial": 0.30,
    "mature-compounder": 0.50,
    "secular-grower": 0.60,
    "platform": 0.60,
}
DEFAULT_W_DCF = 0.50
PE_BOUNDS_CYCLICAL = (8.0, 30.0)
PE_BOUNDS_GROWTH = (8.0, 45.0)
HORIZON_MONTHS = 12


def scenario_probabilities(judge_report: dict | None) -> tuple[dict[str, float], str]:
    """The judge's rubric-anchored probabilities; normalized to sum 1. Fallback: a deterministic
    mapping from leaning + conviction (for cached judge reports predating the schema)."""
    if judge_report:
        raw = judge_report.get("scenario_probabilities")
        if isinstance(raw, dict):
            vals = {k: float(raw.get(k, 0) or 0) for k in ("bull", "base", "bear")}
            total = sum(vals.values())
            if total > 0:
                return {k: round(v / total, 3) for k, v in vals.items()}, "judge"
    # Fallback: tilt 25/50/25 by leaning, scaled by conviction.
    leaning = str((judge_report or {}).get("leaning") or "neutral").lower()
    conviction = (judge_report or {}).get("conviction")
    conviction = float(conviction) if isinstance(conviction, (int, float)) else 0.5
    sign = {"strong_bull": 1.0, "bull": 0.6, "neutral": 0.0,
            "bear": -0.6, "strong_bear": -1.0}.get(leaning, 0.0)
    tilt = 0.20 * sign * max(0.0, min(1.0, conviction))
    p = {"bull": 0.25 + tilt, "base": 0.50, "bear": 0.25 - tilt}
    total = sum(p.values())
    return {k: round(v / total, 3) for k, v in p.items()}, "fallback(leaning/conviction)"


async def _through_cycle_pe(db: AsyncSession, ticker: str) -> float | None:
    """Median (quarter-end price / trailing-4q EPS) over filed history — our own measured
    through-cycle multiple, for valuing a cyclical's normalized earnings."""
    fins = (
        await db.execute(
            select(Financial.period_end_date, Financial.eps)
            .where(Financial.ticker == ticker, Financial.eps.is_not(None))
            .order_by(Financial.period_end_date.asc())
        )
    ).all()
    if len(fins) < 8:
        return None
    pes: list[float] = []
    for i in range(3, len(fins)):
        ttm_eps = sum(e for _, e in fins[i - 3:i + 1])
        if ttm_eps <= 0:
            continue
        end = fins[i][0]
        px = (
            await db.execute(
                select(DailyPrice.close)
                .where(DailyPrice.ticker == ticker, DailyPrice.date <= end)
                .order_by(DailyPrice.date.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if px:
            pes.append(px / ttm_eps)
    if len(pes) < 4:
        return None
    pes.sort()
    return pes[len(pes) // 2]


async def _peer_forward_pe(db: AsyncSession, ticker: str) -> float | None:
    """Median forward P/E across the ticker's peer set (own forward P/E as fallback)."""
    peers = (
        await db.execute(select(PeerWeight.peer).where(PeerWeight.ticker == ticker))
    ).scalars().all()
    pes: list[float] = []
    for p in list(peers) + [ticker]:
        v = (
            await db.execute(
                select(Valuation.forward_pe).where(Valuation.ticker == p)
                .order_by(Valuation.date.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if v and 0 < v < 200:
            pes.append(float(v))
    if not pes:
        return None
    pes.sort()
    return pes[len(pes) // 2]


async def compute_price_target(db: AsyncSession, ticker: str,
                               judge_report: dict | None) -> PriceTarget | None:
    """Build + persist today's price target. None when the forecast (4.2) is missing —
    no model, no target; we don't conjure numbers."""
    ticker = ticker.upper()
    forecast = (
        await db.execute(
            select(Forecast).where(Forecast.ticker == ticker)
            .order_by(Forecast.as_of.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if forecast is None or not forecast.projections:
        logger.info("[pt] %s: no forecast — no price target", ticker)
        return None

    stock = await db.get(Stock, ticker)
    archetype = stock.archetype if stock else None

    async def latest_nonnull(col):
        """Newest filed value for a balance-sheet column — individual rows can have gaps
        (e.g. derived Q4s lack EPS-derived shares), so don't insist on the very last row."""
        return (
            await db.execute(
                select(col).where(Financial.ticker == ticker, col.is_not(None))
                .order_by(Financial.period_end_date.desc()).limit(1)
            )
        ).scalar_one_or_none()

    val = (
        await db.execute(
            select(Valuation).where(Valuation.ticker == ticker)
            .order_by(Valuation.date.desc()).limit(1)
        )
    ).scalar_one_or_none()
    price_now = (
        await db.execute(
            select(DailyPrice.close).where(DailyPrice.ticker == ticker)
            .order_by(DailyPrice.date.desc()).limit(1)
        )
    ).scalar_one_or_none()

    shares = await latest_nonnull(Financial.shares_outstanding) or (
        val.shares_outstanding if val else None)
    if not shares:
        logger.warning("[pt] %s: no share count — no price target", ticker)
        return None
    total_debt = await latest_nonnull(Financial.total_debt) or 0.0
    cash = await latest_nonnull(Financial.cash_and_equivalents) or 0.0
    net_debt = total_debt - cash
    market_cap = (val.market_cap if val else None) or (price_now * shares if price_now else None)

    wacc = await build_wacc(db, ticker, market_cap, total_debt)
    fcf_conv, fcf_conv_source = await historical_fcf_conversion(db, ticker)
    terminal_g = TERMINAL_G.get(archetype or "", DEFAULT_TERMINAL_G)
    probs, probs_source = scenario_probabilities(judge_report)
    w_dcf = W_DCF.get(archetype or "", DEFAULT_W_DCF)

    # Multiple leg setup — basis decides the ruler (the MU lesson, mechanized).
    ne = await compute_normalized_earnings(db, ticker, archetype=archetype)
    use_normalized = ne is not None and ne.basis == "cyclical" and ne.normalized_net_income
    if use_normalized:
        pe = await _through_cycle_pe(db, ticker)
        pe = max(PE_BOUNDS_CYCLICAL[0], min(PE_BOUNDS_CYCLICAL[1], pe)) if pe else 14.0
        multiple_basis = f"normalized mid-cycle EPS × through-cycle P/E {pe:.1f}"
        normalized_eps = ne.normalized_net_income / shares
    else:
        pe = await _peer_forward_pe(db, ticker)
        pe = max(PE_BOUNDS_GROWTH[0], min(PE_BOUNDS_GROWTH[1], pe)) if pe else 18.0
        multiple_basis = f"scenario NTM EPS × peer-median fwd P/E {pe:.1f}"
        normalized_eps = None

    scenarios: dict[str, dict] = {}
    blended_values: dict[str, float] = {}
    coe_q = (1 + wacc.cost_of_equity) ** 0.25 - 1  # quarterly discount for the excess-cash credit
    for name in ("base", "bull", "bear"):
        proj = (forecast.projections or {}).get(name) or {}
        q_ni = [q.get("net_income") for q in (proj.get("quarters") or [])]
        if len(q_ni) < 8 or any(v is None for v in q_ni):
            continue
        d = run_dcf(q_ni, fcf_conv, wacc.wacc, terminal_g, net_debt, shares)
        excess_ps = None
        if use_normalized:
            # Through-cycle value = mid-cycle EPS × through-cycle P/E PLUS the PV of ALL the cash
            # the SCENARIO earns above mid-cycle run-rate before full reversion: the 8 modeled
            # quarters AND the DCF's fade years 3-5 (which are still above mid-cycle on the way
            # down). Truncating the credit at year 2 ignored real boom money — user-spotted.
            norm_q_ni = ne.normalized_net_income / 4.0
            excess = sum((ni - norm_q_ni) / (1 + coe_q) ** (i + 1) for i, ni in enumerate(q_ni))
            norm_annual = ne.normalized_net_income
            for yr_idx, ni_y in enumerate(d.ni_years[2:], start=3):  # fade years 3-5
                excess += (ni_y - norm_annual) / (1 + wacc.cost_of_equity) ** yr_idx
            excess_ps = excess / shares
            mult_value = normalized_eps * pe + excess_ps
        else:
            ntm_eps = proj.get("ntm_eps")
            mult_value = (ntm_eps * pe) if ntm_eps else None
        dcf_v = d.fair_value_per_share
        if dcf_v is None and mult_value is None:
            continue
        blended = (w_dcf * dcf_v + (1 - w_dcf) * mult_value
                   if (dcf_v is not None and mult_value is not None)
                   else (dcf_v if dcf_v is not None else mult_value))
        blended_values[name] = blended
        scenarios[name] = {"dcf": d.to_dict(),
                           "multiple_value": round(mult_value, 2) if mult_value else None,
                           "excess_earnings_ps": round(excess_ps, 2) if excess_ps is not None else None,
                           "blended": round(blended, 2)}

    if "base" not in blended_values:
        logger.warning("[pt] %s: base scenario incomputable — no price target", ticker)
        return None

    fair_value_now = sum(probs[s] * blended_values.get(s, blended_values["base"])
                         for s in ("bull", "base", "bear"))
    pt_12m = fair_value_now * (1 + wacc.cost_of_equity)

    base_qni = [q["net_income"] for q in forecast.projections["base"]["quarters"]]
    grid = sensitivity_grid(base_qni, fcf_conv, wacc.wacc, terminal_g, net_debt, shares)

    today = date.today()
    row = (
        await db.execute(
            select(PriceTarget).where(PriceTarget.ticker == ticker, PriceTarget.as_of == today)
        )
    ).scalar_one_or_none()
    values = dict(
        archetype=archetype,
        horizon_months=HORIZON_MONTHS,
        fair_value=round(fair_value_now, 2),
        price_target=round(pt_12m, 2),
        price_at=float(price_now) if price_now else None,
        upside=round(pt_12m / price_now - 1, 4) if price_now else None,
        probabilities={**probs, "source": probs_source},
        scenarios=scenarios,
        method={"w_dcf": w_dcf, "multiple_basis": multiple_basis,
                "fcf_conversion": round(fcf_conv, 3), "fcf_conversion_source": fcf_conv_source,
                "terminal_growth": terminal_g, "earnings_basis": ne.basis if ne else "unknown"},
        wacc=wacc.to_dict(),
        sensitivity=grid,
        forecast_as_of=forecast.as_of,
        street_target_mean=val.target_mean_price if val else None,
    )
    if row:
        for k, v in values.items():
            setattr(row, k, v)
    else:
        row = PriceTarget(ticker=ticker, as_of=today, **values)
        db.add(row)
    await db.commit()
    logger.info("[pt] %s: PT(12m) $%.2f (fv $%.2f, P=%s, w_dcf=%.2f, %s) vs price %s",
                ticker, pt_12m, fair_value_now, probs, w_dcf, multiple_basis,
                f"${price_now:.2f}" if price_now else "n/a")
    return row
