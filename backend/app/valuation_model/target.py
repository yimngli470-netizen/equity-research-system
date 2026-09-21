"""Dated, company-conditioned scenario valuation. All prices come from deterministic math.

Present DCF value and a future share-price target are separate quantities. The multiple leg
uses earnings for the twelve months AFTER the target date, never an unspecified provider EPS.
"""
from dataclasses import replace
from datetime import date, timedelta
import logging
import statistics

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.forecast.model import COMPILER_VERSION, _add_months
from app.measurement.normalized_earnings import compute_normalized_earnings
from app.models.financial import Financial
from app.models.forecast import Forecast
from app.models.peer import PeerWeight
from app.models.price import DailyPrice
from app.models.price_target import PriceTarget
from app.models.stock import Stock
from app.models.valuation import Valuation
from app.valuation_model.economics import (MODEL_VERSION, adjusted_multiple, comparable_weight,
    forecast_economics, number, select_policy, weighted_median, window_total)
from app.valuation_model.equity import equity_dcf
from app.valuation_model.funding import funded_share_path
from app.valuation_model.wacc import build_wacc

logger = logging.getLogger(__name__)
HORIZON_MONTHS = 12
NORMALIZED_TAX_RATE = .21


def scenario_summary(scenarios: dict | None) -> dict:
    return {name: {
        "dcf": (s.get("dcf") or {}).get("price_at_horizon"),
        "dcf_today": (s.get("dcf") or {}).get("fair_value_per_share"),
        "multiple": s.get("multiple_value"), "blended": s.get("blended"),
        "dcf_operating": (s.get("dcf_operating") or {}).get("price_at_horizon"),
        "multiple_operating": None, "blended_operating": s.get("blended_operating"),
        "eps_at_horizon": s.get("eps_at_horizon"), "multiple_pe": s.get("multiple_pe"),
        "w_dcf": s.get("w_dcf"), "revenue_growth": s.get("revenue_growth"),
        "operating_margin": s.get("operating_margin"),
    } for name, s in (scenarios or {}).items() if isinstance(s, dict)}


def scenario_probabilities(judge_report: dict | None) -> tuple[dict[str, float], str]:
    raw = (judge_report or {}).get("scenario_probabilities")
    if isinstance(raw, dict):
        vals = {k: number(raw.get(k)) for k in ("bull", "base", "bear")}
        if all(v is not None and v >= 0 for v in vals.values()) and sum(vals.values()) > 0:
            total = sum(vals.values())
            return {k: v / total for k, v in vals.items()}, "judge"
    if judge_report is None:
        return {"bull": .25, "base": .5, "bear": .25}, "declared neutral prior (no current judge)"
    leaning = str((judge_report or {}).get("leaning") or "neutral").lower()
    conviction = number((judge_report or {}).get("conviction"))
    sign = {"strong_bull": 1., "bull": .6, "neutral": 0., "bear": -.6, "strong_bear": -1.}.get(leaning, 0.)
    tilt = .20 * sign * max(0., min(1., conviction if conviction is not None else .5))
    return {"bull": .25 + tilt, "base": .5, "bear": .25 - tilt}, "fallback(leaning/conviction)"


def forecast_issue(forecast: Forecast, latest_end: date | None, at: date) -> str | None:
    if (forecast.input_fingerprint or {}).get("compiler") != COMPILER_VERSION:
        return "Forecast uses the previous compiler; refresh analysis to rebuild the scenario paths."
    if not 0 <= (at - forecast.as_of).days <= 100:
        return "Forecast is more than 100 days old or future-dated."
    qs = ((forecast.projections or {}).get("base") or {}).get("quarters") or []
    if not qs:
        return "Forecast has no quarterly earnings path."
    modeled_actual = _add_months(date.fromisoformat(qs[0]["end_approx"]), -3)
    if latest_end and latest_end > modeled_actual + timedelta(days=7):
        return "A newer financial quarter is available; refresh the forecast before using a target."
    return None


def cash_conversion(financials: list[Financial], operating=False) -> tuple[float | None, dict]:
    # Aggregate a consecutive block, including negative quarters; never cherry-pick positive NI.
    rows = financials[:8]
    key = "operating_income" if operating else "net_income"
    meta = {"basis": "FCF / after-tax operating income" if operating else "FCF / GAAP net income",
            "quarters": len(rows), "source": "filed OCF less capex; aggregate latest eight quarters"}
    if len(rows) < 4 or any(number(r.free_cash_flow) is None or number(getattr(r, key)) is None for r in rows):
        return None, {**meta, "reason": "At least four consecutive quarters of earnings and FCF required"}
    if any(not 75 <= (a.period_end_date - b.period_end_date).days <= 100 for a, b in zip(rows, rows[1:])):
        return None, {**meta, "reason": "Cash-flow history has missing quarters"}
    income = sum(getattr(r, key) for r in rows) * (1 - NORMALIZED_TAX_RATE if operating else 1)
    fcf = sum(r.free_cash_flow for r in rows)
    value = fcf / income if income > 0 else None
    meta.update(start=rows[-1].period_end_date.isoformat(), end=rows[0].period_end_date.isoformat(),
                income=income, free_cash_flow=fcf, observed_conversion=value)
    if value is None or not 0 < value <= 3:
        return None, {**meta, "reason": "Unstable earnings-to-cash bridge; requires an explicit reinvestment model"}
    return value, meta


def _gaap_peer_baseline(rows: list[Financial]) -> dict | None:
    """A forecast P/E needs a reported GAAP bridge, not only a guessed net factor.

    Require a complete profitable trailing year. Individual loss quarters are retained;
    an unprofitable trailing year is a transition case, not an earnings-multiple anchor.
    """
    recent = sorted(rows, key=lambda r: r.period_end_date, reverse=True)[:4]
    if len(recent) < 4 or any(
        number(r.net_income) is None or number(r.operating_income) is None
        or number(r.revenue) is None or r.revenue <= 0
        or number(r.shares_outstanding) is None or r.shares_outstanding <= 0
        for r in recent
    ):
        return None
    if any(not 75 <= (a.period_end_date - b.period_end_date).days <= 100
           for a, b in zip(recent, recent[1:])):
        return None
    ni, oi = sum(r.net_income for r in recent), sum(r.operating_income for r in recent)
    if ni <= 0 or oi <= 0:
        return None
    return {"quarters": 4, "net_income": ni, "operating_income": oi,
            "net_factor": ni / oi, "start": _add_months(recent[-1].period_end_date, -3).isoformat(),
            "end": recent[0].period_end_date.isoformat(),
            "source": "reported GAAP income and diluted shares; complete latest four quarters"}


def _stock_comp_ratio(rows: list[Financial]) -> float:
    rows = rows[:8]
    if len(rows) < 4 or any(number(r.stock_based_comp) is None or number(r.revenue) is None
                            or r.revenue <= 0 or r.stock_based_comp < 0 for r in rows):
        raise ValueError("At least four quarters of stock-compensation and revenue data are required to model dilution and repurchase funding.")
    return sum(r.stock_based_comp for r in rows) / sum(r.revenue for r in rows)


async def _comparable_anchor(db, subject, at):
    """Bulk reads, followed by economic eligibility, freshness, and matching GAAP EPS windows."""
    if (subject.industry or "").strip().casefold() in {"software - application", "software - infrastructure"}:
        return None, {"constituents": [], "minimum_peers": 2,
            "excluded_industry": subject.industry,
            "earnings_basis": "our GAAP forecast", "earnings_start": at.isoformat(),
            "earnings_end": _add_months(at, 12).isoformat(),
            "source": "provider industry classification is insufficient for a business-model match",
            "reason": "DCF only: the provider software bucket does not establish comparable business models; "
                      "narrower business-model coverage is required. Return and financial similarity alone are insufficient."}
    weights = {r.peer: r.weight for r in (await db.execute(select(PeerWeight).where(PeerWeight.ticker == subject.ticker))).scalars()}
    stocks = list((await db.execute(select(Stock).where(Stock.ticker.in_(list(weights))))).scalars()) if weights else []
    # Other researched companies may be comparable even before the similarity job has run.
    if not stocks:
        stocks = list((await db.execute(select(Stock).where(Stock.sector == subject.sector))).scalars())
    tickers = [s.ticker for s in stocks if s.ticker != subject.ticker]
    def latest_query(model, date_col):
        return select(model).where(model.ticker.in_(tickers), date_col <= at).distinct(model.ticker).order_by(model.ticker, date_col.desc())
    forecasts = {r.ticker: r for r in (await db.execute(latest_query(Forecast, Forecast.as_of))).scalars()}
    prices = {r.ticker: r for r in (await db.execute(latest_query(DailyPrice, DailyPrice.date))).scalars()}
    vals = {r.ticker: r for r in (await db.execute(latest_query(Valuation, Valuation.date))).scalars()}
    # Only forecast-covered peers can qualify. Load their actual history in one query so a
    # numeric forecast cannot bypass a missing GAAP earnings baseline (e.g. a default NI/OI).
    histories = {t: [] for t in forecasts}
    financial_rows = (await db.execute(select(Financial).where(
        Financial.ticker.in_(list(forecasts)), Financial.period_end_date <= at
    ).order_by(Financial.ticker, Financial.period_end_date.desc()))).scalars()
    for row in financial_rows:
        if len(histories[row.ticker]) < 8:
            histories[row.ticker].append(row)
    fins = {t: rows[0] for t, rows in histories.items() if rows}
    constituents = []
    exclusions = {"missing_or_stale_inputs": 0, "economically_unrelated": 0,
                  "invalid_earnings": 0, "unsupported_gaap_history": 0}
    excluded_gaap_peers, excluded_funding_peers = [], []
    for stock in stocks:
        if stock.ticker == subject.ticker:
            continue
        f, px, val, fin = forecasts.get(stock.ticker), prices.get(stock.ticker), vals.get(stock.ticker), fins.get(stock.ticker)
        if not f or not px or (at - px.date).days > 7 or forecast_issue(f, fin.period_end_date if fin else None, at):
            exclusions["missing_or_stale_inputs"] += 1
            continue
        baseline = _gaap_peer_baseline(histories.get(stock.ticker, []))
        if baseline is None:
            exclusions["unsupported_gaap_history"] += 1
            excluded_gaap_peers.append(stock.ticker)
            continue
        cap = val.market_cap if val and (at - val.date).days <= 30 else None
        econ = forecast_economics(stock, f.projections.get("base") or {}, at, cap, fin.total_debt or 0 if fin else 0)
        try:
            conversion, conversion_meta = cash_conversion(histories[stock.ticker])
            if conversion is None:
                raise ValueError(conversion_meta["reason"])
            funded, funding_adjustments = funded_share_path(
                (f.projections.get("base") or {}).get("quarters") or [], fin.shares_outstanding,
                conversion=conversion, reference_price=px.close,
                stock_comp_ratio=_stock_comp_ratio(histories[stock.ticker]))
        except (ValueError, KeyError, TypeError):
            excluded_funding_peers.append(stock.ticker)
            continue
        eps = window_total(funded, at, _add_months(at, 12), "eps")
        if econ is None or eps is None or eps <= 0 or not px.close or px.close <= 0:
            exclusions["invalid_earnings"] += 1
            continue
        weight = comparable_weight(subject, econ, weights.get(stock.ticker, 0))
        if weight <= 0:
            exclusions["economically_unrelated"] += 1
            continue
        constituents.append({"ticker": stock.ticker, "pe": px.close / eps, "weight": weight,
            "revenue_growth": econ.revenue_growth, "operating_margin": econ.operating_margin,
            "market_cap": cap, "price": px.close, "price_date": px.date.isoformat(),
            "forecast_as_of": f.as_of.isoformat(), "eps": eps, "gaap_history": baseline,
            "funding_adjustments": funding_adjustments})
    meta = {"constituents": constituents, "exclusions": exclusions, "minimum_peers": 2,
        "excluded_gaap_peers": excluded_gaap_peers,
        "excluded_funding_peers": excluded_funding_peers,
        "gaap_history_requirement": "Complete latest four quarters of reported NI/OI/revenue/shares with positive aggregate NI and OI",
        "earnings_basis": "our GAAP forecast", "earnings_start": at.isoformat(),
        "earnings_end": _add_months(at, 12).isoformat(),
        "source": "peer market price / same-period modeled GAAP EPS; economic-distance weighted median"}
    if len(constituents) < 2:
        return None, {**meta, "reason": "Fewer than two fresh, economically eligible GAAP forecast peers; DCF only"}
    for key in ("pe", "revenue_growth", "operating_margin"):
        meta[key] = weighted_median([(c[key], c["weight"]) for c in constituents])
    return meta["pe"], meta


async def _through_cycle_pe(db, ticker, at):
    # Market-cap / reported NI avoids historical price-versus-split-adjusted EPS mismatches.
    vals = list((await db.execute(select(Valuation).where(Valuation.ticker == ticker, Valuation.date <= at,
        Valuation.market_cap > 0).order_by(Valuation.date))).scalars())
    fins = list((await db.execute(select(Financial).where(Financial.ticker == ticker,
        Financial.filed_date.is_not(None)).order_by(Financial.period_end_date))).scalars())
    samples = {}
    for val in vals:
        known = [f for f in fins if f.filed_date <= val.date and f.period_end_date <= val.date][-4:]
        if len(known) < 4 or any(f.net_income is None for f in known):
            continue
        if any(not 75 <= (b.period_end_date - a.period_end_date).days <= 100 for a, b in zip(known, known[1:])):
            continue
        if (val.date - known[-1].period_end_date).days > 150:
            continue
        ni = sum(f.net_income for f in known)
        if ni > 0:
            samples[(val.date.year, (val.date.month - 1) // 3)] = (val.date, val.market_cap / ni)
    observations = list(samples.values())
    if len(observations) < 8 or (max(d for d, _ in observations) - min(d for d, _ in observations)).days < 700:
        return None
    return statistics.median(p for _, p in observations)


async def compute_price_target(db: AsyncSession, ticker: str, judge_report: dict | None,
                               *, persist=True, as_of: date | None = None, horizon_months=12) -> PriceTarget:
    if horizon_months not in (12, 18):
        raise ValueError("Supported target horizons are 12 and 18 months")
    if as_of is not None and as_of != date.today():
        raise ValueError("This live calculator does not support historical dates; use stored dated artifacts for historical review")
    at, ticker = as_of or date.today(), ticker.upper()
    target_date = _add_months(at, horizon_months)
    end = _add_months(target_date, 12)
    stock = await db.get(Stock, ticker)
    f = (await db.execute(select(Forecast).where(Forecast.ticker == ticker, Forecast.as_of <= at)
                         .order_by(Forecast.as_of.desc()).limit(1))).scalar_one_or_none()
    px = (await db.execute(select(DailyPrice).where(DailyPrice.ticker == ticker, DailyPrice.date <= at)
                          .order_by(DailyPrice.date.desc()).limit(1))).scalar_one_or_none()
    val = (await db.execute(select(Valuation).where(Valuation.ticker == ticker, Valuation.date <= at)
                           .order_by(Valuation.date.desc()).limit(1))).scalar_one_or_none()
    fins = list((await db.execute(select(Financial).where(Financial.ticker == ticker, Financial.period_end_date <= at)
                                 .order_by(Financial.period_end_date.desc()).limit(24))).scalars())
    probs, prob_source = scenario_probabilities(judge_report)
    method = {"version": MODEL_VERSION, "status": "unavailable", "issues": [], "warnings": [],
        "target_date": target_date.isoformat(), "earnings_start": target_date.isoformat(), "earnings_end": end.isoformat(),
        "earnings_basis": "GAAP", "price_date": px.date.isoformat() if px else None,
        "street_as_of": val.date.isoformat() if val else None,
        "financial_end": fins[0].period_end_date.isoformat() if fins else None,
        "period_note": "Modeled quarter ends and partial-quarter accrual are approximate; earnings windows are calendar aligned.",
        "fair_value_basis": "probability-weighted present equity DCF", "target_basis": "future equity DCF and forward earnings at the target date",
        "operating_basis": "Operating cash-conversion sensitivity, fixed 21% normalization tax; not company-reconciled non-GAAP EPS",
        "policy_source": "Declared model priors; not empirically calibrated. A low price alone does not validate a buy thesis."}
    values = dict(archetype=stock.archetype if stock else None, horizon_months=horizon_months,
        fair_value=None, price_target=None, price_at=px.close if px else None, upside=None,
        probabilities={**probs, "source": prob_source}, scenarios={}, modes={}, method=method,
        wacc={}, sensitivity={}, forecast_as_of=f.as_of if f else None,
        street_target_mean=val.target_mean_price if val else None)
    try:
        if not stock or not f:
            raise ValueError("No company forecast available; run analysis to generate scenarios.")
        if stock.archetype not in {"financial", "cyclical-commodity", "deep-value-turnaround", "platform", "secular-grower", "mature-compounder"}:
            raise ValueError("Business-model classification is missing; classify the company before selecting a valuation method.")
        issue = forecast_issue(f, fins[0].period_end_date if fins else None, at)
        if issue:
            raise ValueError(issue)
        if not px or not px.close or px.close <= 0 or (at - px.date).days > 7:
            raise ValueError("A market price from the last seven days is required.")
        shares = next((r.shares_outstanding for r in fins if r.shares_outstanding and r.shares_outstanding > 0), None)
        shares = shares or (val.shares_outstanding if val else None)
        if not shares or not fins:
            raise ValueError("Missing filed share count or financial history.")
        debt = next((r.total_debt for r in fins if r.total_debt is not None), 0)
        cap = px.close * shares
        conv, conv_meta = cash_conversion(fins)
        opconv, op_meta = cash_conversion(fins, operating=True)
        method.update(fcf_conversion=conv, cash_conversion=conv_meta, operating_cash_conversion=op_meta)
        if conv is None:
            raise ValueError(conv_meta["reason"])
        compensation_rows = fins[:8]
        sbc_ratio = _stock_comp_ratio(compensation_rows)
        method["share_funding"] = {"stock_comp_ratio": sbc_ratio, "reference_price": px.close,
            "source": "aggregate filed stock compensation / revenue, latest eight quarters",
            "start": compensation_rows[-1].period_end_date.isoformat(), "end": compensation_rows[0].period_end_date.isoformat(),
            "assumption": "Repurchases are capped at modeled quarterly FCF, with unmet share retirements carried as additional dilution in EPS and DCF. Funding uses a constant reference price; no cash reserves or financing proceeds are assumed.",
            "adjustments_by_scenario": {}}
        e = forecast_economics(stock, f.projections.get("base") or {}, at, cap, debt)
        if e is None:
            raise ValueError("Forecast must cover the next 24 months with complete revenue and earnings data.")
        policy = select_policy(e)
        method.update(policy=policy.to_dict(), terminal_growth=policy.terminal_growth,
                      w_dcf=policy.dcf_weight, growth=e.revenue_growth, operating_margin=e.operating_margin)
        ne = await compute_normalized_earnings(db, ticker, archetype=stock.archetype)
        cyclical = stock.archetype == "cyclical-commodity"
        normalized_income = ne.normalized_net_income if cyclical and ne else None
        if cyclical and (not normalized_income or normalized_income <= 0):
            raise ValueError("Cyclical valuation requires positive normalized earning power.")
        if cyclical:
            pe = await _through_cycle_pe(db, ticker, at)
            anchor = {"pe": pe, "source": "own market-cap / filed TTM NI, quarter-sampled over at least two years"}
            method["earnings_basis"] = "normalized mid-cycle"
            method["normalized_net_income"] = normalized_income
            method["multiple_basis"] = "normalized mid-cycle EPS × own through-cycle P/E"
        else:
            pe, anchor = await _comparable_anchor(db, e, at)
            method["multiple_basis"] = "GAAP EPS for 12 months after target date × economically matched peer P/E"
        method["comparable_anchor"] = anchor
        if pe is None:
            method["warnings"].append(anchor.get("reason", "Insufficient through-cycle multiple history; DCF only"))
        if val and (at - val.date).days > 30:
            method["warnings"].append("Street target snapshot is more than 30 days old; compare its date before drawing conclusions.")
        discount = await build_wacc(db, ticker, cap, debt)
        values["wacc"] = {**discount.to_dict(), "applied_discount_rate": "cost_of_equity"}
        scenarios, funded_projections, funding_notes = {}, {}, []
        for name in ("base", "bull", "bear"):
            proj = f.projections.get(name) or {}
            qs, funding_adjustments = funded_share_path(proj.get("quarters") or [], shares,
                conversion=conv, reference_price=px.close, stock_comp_ratio=sbc_ratio)
            funded_projections[name] = qs
            method["share_funding"]["adjustments_by_scenario"][name] = funding_adjustments
            if funding_adjustments:
                extra = qs[-1]["shares"] / proj["quarters"][-1]["shares"] - 1
                funding_notes.append(f"{name} +{extra:.1%}")
            eps = window_total(qs, target_date, end, "eps")
            economics = forecast_economics(stock, proj, at, cap, debt)
            if eps is None or economics is None:
                raise ValueError(f"{name} forecast does not cover the target-date earnings window through {end}.")
            sp = select_policy(economics)
            dcf = equity_dcf(qs, conv, discount.cost_of_equity, sp, at, target_date, shares,
                             normalized_income=normalized_income, reference_price=px.close, stock_comp_ratio=sbc_ratio)
            mult_pe, factor = None, None
            if pe is not None and eps > 0 and sp.dcf_weight < 1:
                mult_pe, factor = (pe, 1.) if cyclical else adjusted_multiple(pe, economics, anchor["revenue_growth"], anchor["operating_margin"])
            mult_eps = normalized_income * (1 + sp.terminal_growth) ** (horizon_months / 12) / dcf["target_shares"] if cyclical else eps
            multiple = mult_eps * mult_pe if mult_pe is not None else None
            weight = sp.dcf_weight if multiple is not None else 1.
            blended = weight * dcf["price_at_horizon"] + (1 - weight) * multiple if multiple is not None else dcf["price_at_horizon"]
            op = None
            if opconv is not None:
                try:
                    op = equity_dcf(qs, opconv, discount.cost_of_equity, sp, at, target_date, shares,
                                    operating=True, normalized_income=normalized_income,
                                    reference_price=px.close, stock_comp_ratio=sbc_ratio)
                except ValueError as exc:
                    method["warnings"].append(f"{name.capitalize()} operating sensitivity unavailable: {exc}")
            scenarios[name] = {"dcf": dcf, "dcf_operating": op,
                "multiple_value": round(multiple, 2) if multiple is not None else None, "multiple_pe": mult_pe,
                "multiple_adjustment": factor, "eps_at_horizon": eps, "multiple_eps": mult_eps,
                "w_dcf": weight, "blended": round(blended, 2),
                "blended_operating": op["price_at_horizon"] if op else None,
                "revenue_growth": economics.revenue_growth, "operating_margin": economics.operating_margin,
                "policy": sp.to_dict(), "forecast_adjustments": proj.get("adjustments", []),
                "funding_adjustments": funding_adjustments, "funded_quarters": qs}
        if funding_notes:
            method["warnings"].append("Cash-limited buybacks increase ending shares versus the requested path ("
                + ", ".join(funding_notes) + "). EPS and both valuation legs include this additional dilution.")
        def weighted(key, mode=None):
            return sum(probs[n] * (s[mode][key] if mode else s[key]) for n, s in scenarios.items())
        fv, pt = weighted("fair_value_per_share", "dcf"), weighted("blended")
        modes = {"gaap": {"fair_value": round(fv, 2), "price_target": round(pt, 2), "upside": round(pt / px.close - 1, 4)}}
        if all(s["dcf_operating"] for s in scenarios.values()):
            opfv, oppt = weighted("fair_value_per_share", "dcf_operating"), weighted("price_at_horizon", "dcf_operating")
            modes["operating"] = {"fair_value": round(opfv, 2), "price_target": round(oppt, 2), "upside": round(oppt / px.close - 1, 4)}
        method["status"] = "ready"
        method["w_dcf"] = scenarios["base"]["w_dcf"]
        base_dcf = scenarios["base"]["dcf"]["price_at_horizon"]
        base_multiple = scenarios["base"]["multiple_value"]
        if base_multiple is not None and base_dcf > 0 and abs(base_multiple / base_dcf - 1) > .35:
            method["warnings"].append(f"The base methods disagree materially: DCF ${base_dcf:.0f}, comparable earnings ${base_multiple:.0f}. Review growth duration, cash conversion and the peer multiple before relying on the blended target.")
        if scenarios["bear"]["blended"] > scenarios["base"]["blended"] or scenarios["bull"]["blended"] < scenarios["base"]["blended"]:
            method["warnings"].append("Scenario prices cross: review the growth, cash conversion, and dilution assumptions before relying on the range.")
        rates = [discount.cost_of_equity + d for d in (-.01, 0, .01)]
        growths = [policy.terminal_growth + d for d in (-.005, 0, .005)]
        grid = [[equity_dcf(funded_projections["base"], conv, r, replace(policy, terminal_growth=g),
                at, target_date, shares, normalized_income=normalized_income, reference_price=px.close, stock_comp_ratio=sbc_ratio)["fair_value_per_share"]
                if r > g else None for g in growths] for r in rates]
        values.update(fair_value=round(fv, 2), price_target=round(pt, 2), upside=round(pt / px.close - 1, 4),
                      scenarios=scenarios, modes=modes, sensitivity={"discount_basis": "cost_of_equity", "rates": rates, "terminal_growths": growths, "grid": grid})
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        method["status"] = "unavailable"
        method["issues"].append(str(exc))
        logger.info("[pt] %s unavailable: %s", ticker, exc)
    row = None
    if persist:
        row = (await db.execute(select(PriceTarget).where(PriceTarget.ticker == ticker, PriceTarget.as_of == at))).scalar_one_or_none()
    if row is None:
        row = PriceTarget(ticker=ticker, as_of=at, **values)
        if persist:
            db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    if persist:
        await db.commit()
    return row
