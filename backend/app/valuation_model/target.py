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
from app.valuation_model.dcf import (DEFAULT_TERMINAL_G, NORMALIZED_TAX_RATE, TERMINAL_G,
                                     historical_fcf_conversion, operating_fcf_conversion,
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

# Growth-tilted multiple (Q2): higher expected growth earns a higher P/E (the PEG relationship), so
# the bull/bear multiple re-rates instead of holding flat. Tilt = 1 + β·(scenario growth − base
# growth), bounded — the peer-median P/E stays the anchor; the tilt only widens the spread by each
# scenario's forward EPS growth differential. Robust where pure PEG blows up (growth → 0).
GROWTH_PE_BETA = 1.5
MULT_TILT_BOUNDS = (0.70, 1.40)


def scenario_summary(scenarios: dict | None) -> dict:
    """Slim per-scenario legs for API/UI: the DCF value, the multiple value, and the blend —
    the spread between the legs is the expectations gap and belongs on screen, not buried in JSONB."""
    out: dict = {}
    for name, s in (scenarios or {}).items():
        if not isinstance(s, dict):
            continue
        out[name] = {
            "dcf": (s.get("dcf") or {}).get("fair_value_per_share"),
            "multiple": s.get("multiple_value"),
            "blended": s.get("blended"),
            # Operating (non-GAAP) legs — present when an operating DCF was computed.
            "dcf_operating": (s.get("dcf_operating") or {}).get("fair_value_per_share"),
            "multiple_operating": s.get("multiple_value_operating"),
            "blended_operating": s.get("blended_operating"),
        }
    return out


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
    # Operating (non-GAAP) basis: after-tax operating income, bypassing GAAP NI's below-the-line
    # noise (equity-stake revaluations). Two DCFs, two price targets, switchable in the UI.
    fcf_conv_op, fcf_conv_op_source = await operating_fcf_conversion(db, ticker)
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
        multiple_basis = f"scenario NTM EPS × growth-tilted peer P/E (base {pe:.1f})"
        normalized_eps = None

    def _blend(dcf_v: float | None, mult_v: float | None) -> float | None:
        if dcf_v is not None and mult_v is not None:
            return w_dcf * dcf_v + (1 - w_dcf) * mult_v
        return dcf_v if dcf_v is not None else mult_v

    # Each scenario's forward EPS growth (NTM → following year) → the growth-tilt for its multiple.
    def _fwd_growth(p: dict) -> float | None:
        ntm, nxt = p.get("ntm_eps"), p.get("next_year_eps")
        return max(-0.5, min(2.0, nxt / ntm - 1)) if (ntm and nxt and ntm > 0) else None

    growths = {n: _fwd_growth((forecast.projections or {}).get(n) or {})
               for n in ("base", "bull", "bear")}
    growth_base = growths.get("base")

    def _tilted_pe(name: str) -> float:
        g = growths.get(name)
        if g is None or growth_base is None:
            return pe
        tilt = max(MULT_TILT_BOUNDS[0], min(MULT_TILT_BOUNDS[1], 1 + GROWTH_PE_BETA * (g - growth_base)))
        lo, hi = PE_BOUNDS_CYCLICAL if use_normalized else PE_BOUNDS_GROWTH
        return max(lo, min(hi, pe * tilt))

    scenarios: dict[str, dict] = {}
    blended_gaap: dict[str, float] = {}      # GAAP net-income basis (current behavior)
    blended_op: dict[str, float] = {}        # operating (non-GAAP) basis
    coe_q = (1 + wacc.cost_of_equity) ** 0.25 - 1  # quarterly discount for the excess-cash credit
    for name in ("base", "bull", "bear"):
        proj = (forecast.projections or {}).get(name) or {}
        quarters = proj.get("quarters") or []
        q_ni = [q.get("net_income") for q in quarters]
        if len(q_ni) < 8 or any(v is None for v in q_ni):
            continue
        # Operating NI = after-tax operating income (NOPAT) — drops the noisy net_factor. Available
        # only when every projected quarter carries operating_income.
        q_oi = [q.get("operating_income") for q in quarters]
        q_ni_op = ([oi * (1 - NORMALIZED_TAX_RATE) for oi in q_oi]
                   if len(q_oi) >= 8 and not any(v is None for v in q_oi) else None)

        d_gaap = run_dcf(q_ni, fcf_conv, wacc.wacc, terminal_g, net_debt, shares)
        d_op = (run_dcf(q_ni_op, fcf_conv_op, wacc.wacc, terminal_g, net_debt, shares)
                if q_ni_op else None)

        excess_ps = None
        if use_normalized:
            # Through-cycle value = mid-cycle EPS × through-cycle P/E PLUS the PV of ALL the cash
            # the SCENARIO earns above mid-cycle run-rate before full reversion (8 modeled quarters +
            # DCF fade years 3-5). For cyclicals the normalized leg is already clean, so both modes
            # share this multiple — only the DCF leg differs.
            norm_q_ni = ne.normalized_net_income / 4.0
            excess = sum((ni - norm_q_ni) / (1 + coe_q) ** (i + 1) for i, ni in enumerate(q_ni))
            norm_annual = ne.normalized_net_income
            for yr_idx, ni_y in enumerate(d_gaap.ni_years[2:], start=3):  # fade years 3-5
                excess += (ni_y - norm_annual) / (1 + wacc.cost_of_equity) ** yr_idx
            excess_ps = excess / shares
            mult_gaap = normalized_eps * pe + excess_ps
            mult_op = mult_gaap
            mult_pe = pe   # cyclicals: through-cycle P/E, not growth-tilted (a stable multiple is the point)
        else:
            mult_pe = _tilted_pe(name)   # growth-re-rated P/E for this scenario
            ntm_eps = proj.get("ntm_eps")
            mult_gaap = (ntm_eps * mult_pe) if ntm_eps else None
            # Clean NTM EPS from operating NI — the operating-basis multiple leg.
            ntm_eps_op = (sum(q_ni_op[:4]) / shares) if q_ni_op else None
            mult_op = (ntm_eps_op * mult_pe) if ntm_eps_op else None

        b_gaap = _blend(d_gaap.fair_value_per_share, mult_gaap)
        if b_gaap is None:
            continue
        blended_gaap[name] = b_gaap
        scen = {"dcf": d_gaap.to_dict(),
                "multiple_value": round(mult_gaap, 2) if mult_gaap else None,
                "multiple_pe": round(mult_pe, 1),
                "fwd_growth": round(growths.get(name), 4) if growths.get(name) is not None else None,
                "excess_earnings_ps": round(excess_ps, 2) if excess_ps is not None else None,
                "blended": round(b_gaap, 2)}
        if d_op is not None:
            b_op = _blend(d_op.fair_value_per_share, mult_op)
            if b_op is not None:
                blended_op[name] = b_op
                scen["dcf_operating"] = d_op.to_dict()
                scen["multiple_value_operating"] = round(mult_op, 2) if mult_op else None
                scen["blended_operating"] = round(b_op, 2)
        scenarios[name] = scen

    if "base" not in blended_gaap:
        logger.warning("[pt] %s: base scenario incomputable — no price target", ticker)
        return None

    def _weighted(bv: dict[str, float]) -> float:
        return sum(probs[s] * bv.get(s, bv["base"]) for s in ("bull", "base", "bear"))

    fair_value_now = _weighted(blended_gaap)              # scalar = GAAP (backward compat)
    pt_12m = fair_value_now * (1 + wacc.cost_of_equity)
    modes = {"gaap": {"fair_value": round(fair_value_now, 2), "price_target": round(pt_12m, 2),
                      "upside": round(pt_12m / price_now - 1, 4) if price_now else None}}
    if "base" in blended_op:
        fv_op = _weighted(blended_op)
        pt_op = fv_op * (1 + wacc.cost_of_equity)
        modes["operating"] = {"fair_value": round(fv_op, 2), "price_target": round(pt_op, 2),
                              "upside": round(pt_op / price_now - 1, 4) if price_now else None}

    # Street-method cross-check for cyclicals (user request, 2026-06-12): what OUR earnings are
    # worth under the STREET's method (NTM EPS × the market's current forward multiple, no
    # reversion assumed). Not blended into the PT — a triangulation anchor, so the reversion-
    # anchored number is never read in isolation. Redundant for stable names (their multiple leg
    # already IS forward-P/E-based).
    forward_check: dict | None = None
    if use_normalized:
        base_ntm_eps = (forecast.projections.get("base") or {}).get("ntm_eps")
        fwd_pe = (val.forward_pe if val and val.forward_pe and 0 < val.forward_pe < 200 else None) \
            or await _peer_forward_pe(db, ticker)
        if base_ntm_eps and fwd_pe:
            fwd_pe = max(6.0, min(25.0, float(fwd_pe)))  # peak-cycle forward multiples compress
            forward_check = {
                "value": round(base_ntm_eps * fwd_pe, 2),
                "ntm_eps": base_ntm_eps,
                "fwd_pe": round(fwd_pe, 1),
                "note": "our NTM EPS × market fwd P/E — the street's method applied to OUR earnings (no reversion)",
            }

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
        modes=modes,
        method={"w_dcf": w_dcf, "multiple_basis": multiple_basis,
                "fcf_conversion": round(fcf_conv, 3), "fcf_conversion_source": fcf_conv_source,
                "fcf_conversion_operating": round(fcf_conv_op, 3),
                "operating_tax_rate": NORMALIZED_TAX_RATE,
                "operating_basis": "after-tax operating income (NOPAT) — strips below-the-line "
                                   "non-operating items (e.g. equity-stake revaluations)",
                "terminal_growth": terminal_g, "earnings_basis": ne.basis if ne else "unknown",
                "forward_multiple_check": forward_check},
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
