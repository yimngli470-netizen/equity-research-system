"""Valuation invariants, independent cash-flow checks and dated integration fixtures."""
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace
import math

import pytest
from sqlalchemy import select

from app.forecast.model import COMPILER_VERSION, ScenarioPath, _add_months, compile_scenario
from app.ingestion.estimates_yf import resolve_period
from app.models.estimate import AnalystEstimate
from app.models.financial import Financial
from app.models.forecast import Forecast
from app.models.peer import PeerWeight
from app.models.price import DailyPrice
from app.models.price_target import PriceTarget
from app.models.stock import Stock
from app.models.valuation import Valuation
from app.valuation_model.economics import Economics, ValuationPolicy, adjusted_multiple, comparable_weight, select_policy, window_total
from app.valuation_model.equity import equity_dcf
from app.valuation_model.presentation import price_target_payload
from app.valuation_model.target import cash_conversion, compute_price_target, scenario_probabilities


def path(growth=.2, margin=.3, dilution=0):
    return ScenarioPath([growth] * 12, [margin] * 12, .8, dilution)


def quarters(at, growth=.2, margin=.3, dilution=0):
    return compile_scenario(path(growth, margin, dilution), [1e9] * 4, at, 1e8)


def test_no_60_percent_margin_ceiling_and_visible_safety_adjustments():
    raw = {"revenue_yoy_path": [.5] * 12, "operating_margin_path": [.655] * 12,
           "net_factor": .85, "share_change_qoq": 0}
    p = ScenarioPath.from_llm(raw, {})
    assert p.operating_margin == [.655] * 12
    assert not p.adjustments
    assert compile_scenario(p, [1e9] * 4, date(2026, 6, 30), 1e8)[0]["eps"] == pytest.approx(8.351, abs=.001)
    raw["operating_margin_path"][1] = 1.2
    p = ScenarioPath.from_llm(raw, {})
    assert p.operating_margin[1] == 1
    assert any("q2" in a and "1.2" in a for a in p.adjustments)
    for invalid in (float("nan"), float("inf"), True, "0.6"):
        raw["operating_margin_path"][1] = invalid
        with pytest.raises(ValueError):
            ScenarioPath.from_llm(raw, {})


def test_company_economics_change_method_but_small_cap_alone_does_not():
    amd_like = Economics("FAST", "Semis", "Tech", "secular-grower", .35, .25, 1e11)
    apple_like = Economics("MATURE", "Hardware", "Tech", "mature-compounder", .05, .30, 3e12)
    assert select_policy(amd_like).maturity_year > select_policy(apple_like).maturity_year
    assert select_policy(amd_like).dcf_weight < select_policy(apple_like).dcf_weight
    # The same archetype also gets different treatment when growth changes.
    slow = replace(amd_like, revenue_growth=.05)
    assert select_policy(amd_like) != select_policy(slow)
    assert select_policy(amd_like) == select_policy(replace(amd_like, market_cap=3e12))
    assert adjusted_multiple(25, amd_like, .1, .25)[0] > adjusted_multiple(25, slow, .1, .25)[0]
    assert adjusted_multiple(25, amd_like, .1, .25) == adjusted_multiple(25, replace(amd_like, market_cap=1e9), .1, .25)
    bank = Economics("BANK", "Banks", "Finance", "financial", .1, .4, 1e11)
    assert comparable_weight(amd_like, bank, 1) == 0
    assert comparable_weight(amd_like, replace(amd_like, ticker="ADS", industry="Software"), 1) == 0
    assert comparable_weight(amd_like, replace(amd_like, ticker="MEMORY", archetype="cyclical-commodity"), 1) == 0
    with pytest.raises(ValueError, match="Financial"):
        select_policy(bank)


def test_earnings_windows_roll_past_future_target_and_require_complete_coverage():
    at = date(2026, 6, 30)
    q = quarters(at, growth=.5)
    assert window_total(q, at, _add_months(at, 12), "eps") == pytest.approx(14.4)
    assert window_total(q, _add_months(at, 12), _add_months(at, 24), "eps") == pytest.approx(21.6)
    assert window_total(q[:8], _add_months(at, 13), _add_months(at, 25), "eps") is None
    assert window_total(q, _add_months(at, 18), _add_months(at, 30), "eps") > 21.6
    assert window_total(q[:2] + q[3:], at, _add_months(at, 12), "eps") is None


def test_equity_dcf_matches_independent_discounted_cash_flow_sum():
    at = date(2026, 6, 30)
    policy = ValuationPolicy(5, .025, .5, "test")
    rate = .10
    result = equity_dcf(quarters(at, growth=.1), .8, rate, policy, at, _add_months(at, 12), 1e8, reference_price=100, stock_comp_ratio=0)
    cashflows = result["cash_flows"]
    terminal_end = date.fromisoformat(cashflows[-1]["end"])
    tv = cashflows[-1]["value"] * 1.025 / (.10 - .025)
    pv = sum(c["value"] / 1.1 ** ((date.fromisoformat(c["end"]) - at).days / 365.25) for c in cashflows)
    pv += tv / 1.1 ** ((terminal_end - at).days / 365.25)
    assert result["fair_value_per_share"] == pytest.approx(pv / 1e8, abs=.01)
    # Future share price excludes distributions already paid; simply growing PV double counts them.
    assert result["price_at_horizon"] < result["fair_value_per_share"] * (1 + rate)
    assert result["enterprise_value"] is None  # equity cash flow, no net debt subtraction
    cycle = equity_dcf(quarters(at, growth=.4), .8, rate, policy, at, _add_months(at, 12), 1e8, reference_price=100, stock_comp_ratio=0, normalized_income=5e8)
    boom = equity_dcf(quarters(at, growth=.4), .8, rate, policy, at, _add_months(at, 12), 1e8, reference_price=100, stock_comp_ratio=0)
    assert cycle["fair_value_per_share"] < boom["fair_value_per_share"]
    diluted = equity_dcf(quarters(at, growth=.1, dilution=.01), .8, rate, policy, at, _add_months(at, 12), 1e8, reference_price=100, stock_comp_ratio=0)
    assert diluted["price_at_horizon"] < result["price_at_horizon"]


def test_bad_probabilities_and_negative_cash_conversion_do_not_create_values():
    p, source = scenario_probabilities({"scenario_probabilities": {"bull": float("nan"), "base": 1, "bear": -1}})
    assert math.isclose(sum(p.values()), 1) and all(v >= 0 for v in p.values())
    assert source.startswith("fallback")
    rows = [Financial(period_end_date=_add_months(date(2026, 6, 30), -3*i), net_income=100, free_cash_flow=-10) for i in range(4)]
    assert cash_conversion(rows)[0] is None
    rows[0].free_cash_flow = None
    assert cash_conversion(rows)[0] is None


def test_consensus_fiscal_year_is_not_latest_quarter_plus_twelve_months():
    latest = SimpleNamespace(period="Q1 FY2027", period_end_date=date(2026, 4, 26))
    assert resolve_period("0y", "2027-01-31", latest, date(2026, 6, 30)) == (date(2027, 1, 31), "provider")
    end, precision = resolve_period("0y", None, latest, date(2026, 6, 30))
    assert end.month == 1 and end.year == 2027 and precision == "approximate"
    assert resolve_period("+1y", None, latest, date(2026, 6, 30))[0].year == 2028


async def seed_model(db, ticker, at, *, growth=.2, margin=.3, industry="Semis", archetype="secular-grower", price=100):
    end = _add_months(at, -1)
    stock = Stock(ticker=ticker, name=ticker, sector="Tech", industry=industry, archetype=archetype, active=True)
    db.add(stock)
    for i in range(8):
        db.add(Financial(ticker=ticker, period=f"Q{4-i%4} FY2026", period_end_date=_add_months(end, -3*i),
            filed_date=_add_months(end, -3*i)+timedelta(days=15), revenue=1e9, operating_income=margin*1e9,
            net_income=margin*.8*1e9, eps=margin*8, free_cash_flow=margin*.8*1e9,
            shares_outstanding=1e8, total_debt=1e9, cash_and_equivalents=1e9, stock_based_comp=0))
    f = Forecast(ticker=ticker, as_of=at, horizon_quarters=12, status="open", archetype=archetype,
        input_fingerprint={"compiler": COMPILER_VERSION}, assumptions={},
        projections={s: {"quarters": quarters(end, growth+delta, margin)} for s, delta in (("base",0), ("bull",.1), ("bear",-.1))})
    db.add_all([f, DailyPrice(ticker=ticker, date=at, open=price, high=price, low=price, close=price, adj_close=price, volume=1000),
        Valuation(ticker=ticker, date=at, market_cap=price*1e8, shares_outstanding=1e8, forward_pe=.5)])
    await db.commit()
    return f


async def test_target_uses_valid_gaap_peers_and_shared_agent_calculator(db, monkeypatch):
    at = date.today()
    monkeypatch.setattr("app.valuation_model.wacc._fetch_risk_free", lambda: .04)
    await seed_model(db, "SUBJECT", at, growth=.35)
    await seed_model(db, "PEER1", at)
    await seed_model(db, "PEER2", at, growth=.15)
    await seed_model(db, "AIRLINE", at, industry="Airlines", archetype="cyclical-commodity", price=1)
    for t in ("PEER1", "PEER2", "AIRLINE"):
        db.add(PeerWeight(ticker="SUBJECT", peer=t, weight=1, as_of=at))
    await db.commit()
    pt = await compute_price_target(db, "SUBJECT", {"scenario_probabilities": {"bull": .2, "base": .5, "bear": .3}})
    assert pt.method["status"] == "ready", pt.method
    constituents = pt.method["comparable_anchor"]["constituents"]
    assert {c["ticker"] for c in constituents} == {"PEER1", "PEER2"}
    assert all(c["pe"] > 1 for c in constituents)  # provider .5x explicitly excluded
    base = pt.scenarios["base"]
    assert base["multiple_adjustment"] > 1  # growth premium applies to the base case, too
    assert base["multiple_value"] == pytest.approx(base["eps_at_horizon"] * base["multiple_pe"], abs=.01)
    assert pt.price_target == pytest.approx(sum(pt.probabilities[s] * pt.scenarios[s]["blended"] for s in ("base", "bull", "bear")), abs=.01)
    assert pt.method["earnings_start"] == _add_months(at, 12).isoformat()
    assert pt.method["earnings_end"] == _add_months(at, 24).isoformat()
    # Analyst output cannot replace the engine with a fabricated DCF.
    from app.agents.valuation_agent import ValuationAgent
    agent = object.__new__(ValuationAgent)
    agent._model_values = {"SUBJECT": price_target_payload(pt)}
    r = agent.postprocess_report({"dcf_analysis": {"intrinsic_value_base": 999}, "target_price_range": {"mid": 999}}, "SUBJECT")
    assert r["dcf_analysis"]["intrinsic_value_base"] == base["dcf"]["fair_value_per_share"]
    assert r["target_price_range"]["mid"] == base["blended"]
    assert r["valuation_model"]["status"] == "verified"
    # 18-month horizon uses another dated EPS window, without overwriting the stored 12-month row.
    alternate = await compute_price_target(db, "SUBJECT", None, persist=False, horizon_months=18)
    assert alternate.method["status"] == "ready"
    assert alternate.scenarios["base"]["eps_at_horizon"] > base["eps_at_horizon"]
    assert (await db.execute(select(PriceTarget))).scalar_one().horizon_months == 12


async def test_missing_forecast_coverage_and_stale_artifacts_are_not_buy_prices(db, monkeypatch):
    at = date.today()
    monkeypatch.setattr("app.valuation_model.wacc._fetch_risk_free", lambda: .04)
    f = await seed_model(db, "STALE", at)
    f.input_fingerprint = {}
    await db.commit()
    pt = await compute_price_target(db, "STALE", None)
    assert pt.price_target is None and "previous compiler" in pt.method["issues"][0]
    f.input_fingerprint = {"compiler": COMPILER_VERSION}
    f.projections = {s: {"quarters": v["quarters"][:8]} for s,v in f.projections.items()}
    await db.commit()
    pt = await compute_price_target(db, "STALE", None)
    assert pt.price_target is None and pt.method["status"] == "unavailable"
    old = PriceTarget(as_of=at, price_target=148, fair_value=131, method={}, probabilities={}, scenarios={}, modes={}, wacc={}, sensitivity={}, horizon_months=12)
    payload = price_target_payload(old)
    assert payload["price_target"] is None and payload["method"]["status"] == "refresh_required"


async def test_quarter_and_annual_consensus_can_share_date_and_only_gaap_quarter_compares(db):
    at = date.today()
    from app.forecast.engine import _street_eps_near
    for period_type, eps, basis in (("quarter", 2, "gaap"), ("fiscal_year", 12, "provider_unspecified"), ("legacy", 99, "provider_unspecified")):
        db.add(AnalystEstimate(ticker="TEST", period_end_date=at, period_type=period_type,
            eps_consensus=eps, accounting_basis=basis, date_precision="provider", as_of=at))
    await db.commit()
    assert await _street_eps_near(db, "TEST", at) == 2


async def test_provider_duplicate_quarter_date_cannot_replace_another_quarters_eps(db, monkeypatch):
    import pandas as pd
    from app.ingestion.estimates_yf import ingest_estimates_yf
    at = date.today()
    df = pd.DataFrame({'avg': [2., 3., 10., 14.]}, index=['0q', '+1q', '0y', '+1y'])
    monkeypatch.setattr('app.ingestion.estimates_yf._fetch', lambda t: {
        'earnings_estimate': df, 'revenue_estimate': None, 'eps_revisions': None,
        'period_dates': {'0q': at.isoformat(), '+1q': at.isoformat(), '0y': at.isoformat(), '+1y': _add_months(at,12).isoformat()}})
    assert await ingest_estimates_yf(db, 'DUP') == 3
    row = (await db.execute(select(AnalystEstimate).where(AnalystEstimate.ticker=='DUP', AnalystEstimate.period_type=='quarter'))).scalar_one()
    assert row.period_key == '0q' and row.eps_consensus == 2


async def test_live_calculator_rejects_historical_or_future_dates(db):
    for offset in (-1, 1):
        with pytest.raises(ValueError, match="does not support historical dates"):
            await compute_price_target(db, "TEST", None, as_of=date.today() + timedelta(days=offset))


async def test_consensus_without_financial_calendar_or_provider_date_is_skipped(db, monkeypatch):
    import pandas as pd
    from app.ingestion.estimates_yf import ingest_estimates_yf
    monkeypatch.setattr("app.ingestion.estimates_yf._fetch", lambda _: {
        "earnings_estimate": pd.DataFrame({"avg": [2., 10.]}, index=["0q", "0y"]),
        "revenue_estimate": None, "eps_revisions": None, "period_dates": {}})
    assert await ingest_estimates_yf(db, "MISSING") == 0


async def test_optional_operating_failure_preserves_gaap_target(db, monkeypatch):
    at = date.today()
    monkeypatch.setattr("app.valuation_model.wacc._fetch_risk_free", lambda: .04)
    await seed_model(db, "GAAP", at)
    real_dcf = equity_dcf
    def fail_operating(*args, **kwargs):
        if kwargs.get("operating"):
            raise ValueError("Operating cash does not fund buybacks")
        return real_dcf(*args, **kwargs)
    monkeypatch.setattr("app.valuation_model.target.equity_dcf", fail_operating)
    pt = await compute_price_target(db, "GAAP", None)
    assert pt.method["status"] == "ready" and pt.price_target > 0
    assert "operating" not in pt.modes
    assert len([w for w in pt.method["warnings"] if "sensitivity unavailable" in w]) == 3


async def test_forecast_cache_reuses_compiler_inputs_but_invalidates_archetype(db, monkeypatch):
    from app.forecast.engine import ensure_forecast
    calls = []
    async def assumptions(*args):
        calls.append(True)
        return {"scenarios": {s: {"revenue_yoy_path": [.1] * 12,
            "operating_margin_path": [.3] * 12, "net_factor": .8,
            "share_change_qoq": 0} for s in ("bull", "base", "bear")}}
    monkeypatch.setattr("app.forecast.assumptions.generate_assumptions", assumptions)
    await seed_model(db, "CACHE", date.today())
    first, reused = await ensure_forecast(db, "CACHE")
    assert not reused and len(calls) == 1
    first.input_fingerprint = {**first.input_fingerprint, "compiler": "prior-compiler"}
    await db.commit()
    rebuilt, reused = await ensure_forecast(db, "CACHE")
    assert not reused and len(calls) == 1
    assert rebuilt.input_fingerprint["compiler"] == COMPILER_VERSION
    # Promoting an old fingerprint's recorded label preserves its dated evidence.
    rebuilt.input_fingerprint = {k:v for k,v in rebuilt.input_fingerprint.items() if k != "archetype"}
    await db.commit()
    _, reused = await ensure_forecast(db, "CACHE")
    assert reused and len(calls) == 1
    stock = await db.get(Stock, "CACHE")
    stock.archetype = "mature-compounder"
    await db.commit()
    changed, reused = await ensure_forecast(db, "CACHE")
    assert not reused and len(calls) == 2
    assert changed.archetype == "mature-compounder"


async def test_target_reconciles_requested_buybacks_to_cash_and_carries_dilution_into_eps(db, monkeypatch):
    at = date.today()
    monkeypatch.setattr("app.valuation_model.wacc._fetch_risk_free", lambda: .04)
    f = await seed_model(db, "FUNDED", at)
    f.projections = {s: {"quarters": quarters(_add_months(at, -1), .2, .3, dilution=-.05)}
                     for s in ("base", "bull", "bear")}
    await db.commit()
    raw_eps = window_total(f.projections["base"]["quarters"], _add_months(at, 12), _add_months(at, 24), "eps")
    pt = await compute_price_target(db, "FUNDED", None)
    assert pt.method["status"] == "ready", pt.method
    base = pt.scenarios["base"]
    assert base["funding_adjustments"]
    assert base["eps_at_horizon"] < raw_eps
    assert base["funded_quarters"][-1]["shares"] > f.projections["base"]["quarters"][-1]["shares"]
    assert all(q["repurchase_cash"] <= q["reported_fcf"] + 1e-5
               for q in base["dcf"]["cash_flows"] if q["phase"] == "explicit")
    assert any("additional dilution" in w for w in pt.method["warnings"])
    # Saved forecast assumptions remain reviewable beside the valuation's funded path.
    assert window_total(f.projections["base"]["quarters"], _add_months(at, 12), _add_months(at, 24), "eps") == raw_eps
