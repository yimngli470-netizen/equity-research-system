"""Current valuation displays share dates and numbers while stored predictions stay immutable."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.stocks import get_analysis_reports
from app.models.analysis import AnalysisReport
from app.models.financial import Financial
from app.notes.builder import _render, _summary_payload
from app.valuation_model.economics import MODEL_VERSION
from app.valuation_model.presentation import price_target_payload, valuation_report_payload


def target(as_of=None, *, version=MODEL_VERSION):
    today = date.today()
    scenario = lambda fair, future: {
        "dcf": {"fair_value_per_share": fair, "price_at_horizon": future},
        "blended": future, "multiple_value": None,
    }
    return SimpleNamespace(
        as_of=as_of or today, forecast_as_of=today - timedelta(days=10), price_at=100.,
        fair_value=140., price_target=177., horizon_months=12, upside=.77,
        probabilities={"bear": .25, "base": .5, "bull": .25},
        scenarios={"bear": scenario(100., 110.), "base": scenario(150., 177.), "bull": scenario(200., 250.)},
        modes={"gaap": {"fair_value": 140., "price_target": 177., "upside": .77}},
        method={"version": version, "status": "ready", "financial_end": "2026-03-31", "issues": [],
                "target_date": (today + timedelta(days=365)).isoformat()},
        wacc={"cost_of_equity": .10}, sensitivity={"grid": [[123.]]}, street_target_mean=200.,
    )


def report_for(pt):
    return {
        "summary": "The model supports a $177 target.", "current_price": 100.,
        "valuation_model": {"version": MODEL_VERSION, "status": "verified", "as_of": pt.as_of.isoformat(),
                            "forecast_as_of": pt.forecast_as_of.isoformat(), "method": deepcopy(pt.method)},
        "dcf_analysis": {"intrinsic_value_base": 150.},
        "target_price_range": {"low": 110., "mid": 177., "high": 250.},
        "valuation_verdict": "significantly_undervalued", "margin_of_safety": .5,
        "triangulation": {"your_target_price": 177., "reconciliation": "Our $177 target is lower than street."},
    }


@pytest.mark.parametrize("invalid", ["version", "age", "new_filing", "future"])
def test_stale_targets_suppress_every_current_numeric_view_without_mutating_history(invalid):
    pt = target()
    latest_end = date(2026, 3, 31)
    if invalid == "version":
        pt.method["version"] = "old"
    elif invalid == "age":
        pt.as_of = date.today() - timedelta(days=31)
    elif invalid == "future":
        pt.as_of = date.today() + timedelta(days=1)
    else:
        latest_end = date(2026, 6, 30)
    old = deepcopy(pt.__dict__)
    payload = price_target_payload(pt, latest_financial_end=latest_end)
    assert payload["method"]["status"] == "refresh_required"
    assert payload["fair_value"] is payload["price_target"] is payload["upside"] is None
    assert payload["scenarios"] == payload["modes"] == payload["sensitivity"] == {}
    assert pt.__dict__ == old
    report = report_for(pt)
    original = deepcopy(report)
    shown = valuation_report_payload(report, price_target=pt, latest_financial_end=latest_end)
    assert shown["valuation_model"]["status"] == "refresh_required"
    assert shown["dcf_analysis"]["intrinsic_value_base"] is None
    assert shown["target_price_range"]["mid"] is None
    assert shown["valuation_verdict"] == "unknown"
    assert "$177" not in shown["summary"]
    assert report == original


def test_report_values_come_from_the_current_base_scenario_and_prose_is_separately_dated():
    pt = target()
    report = report_for(pt)
    report["valuation_model"]["as_of"] = (date.today() - timedelta(days=2)).isoformat()
    report["summary"] = "My independent DCF gives $245."
    report["dcf_analysis"]["intrinsic_value_base"] = 245.
    report["model_assessment"] = "Buy on my $245 fair value."
    original = deepcopy(report)
    shown = valuation_report_payload(report, price_target=pt)
    assert shown["dcf_analysis"]["intrinsic_value_base"] == 150.  # base, not weighted 140
    assert shown["target_price_range"] == {"low": 110., "mid": 177., "high": 250.}
    assert shown["triangulation"]["divergence_pct"] == -.115
    assert shown["valuation_model"]["as_of"] == pt.as_of.isoformat()
    assert shown["valuation_model"]["narrative_as_of"] == report["valuation_model"]["as_of"]
    assert shown["valuation_model"]["narrative_stale"] is True
    assert "$245" not in str(shown)
    assert report == original


def test_same_day_peer_repricing_hides_the_old_narrative_without_a_new_llm_run():
    pt = target()
    report = report_for(pt)
    pt.scenarios["base"]["blended"] = 188.
    shown = valuation_report_payload(report, price_target=pt)
    assert shown["target_price_range"]["mid"] == 188.
    assert shown["valuation_model"]["narrative_stale"] is True
    assert "$177" not in str(shown)


def test_matching_current_narrative_is_retained_and_missing_target_never_falls_back_to_llm():
    pt = target()
    report = report_for(pt)
    shown = valuation_report_payload(report, price_target=pt)
    assert shown["valuation_model"]["narrative_stale"] is False
    assert shown["summary"] == report["summary"]
    absent = valuation_report_payload(report)
    assert absent["valuation_model"]["status"] == "unavailable"
    assert absent["dcf_analysis"]["intrinsic_value_base"] is None
    assert absent["target_price_range"]["mid"] is None


@pytest.mark.parametrize("invalid", ["age", "new_filing"])
def test_note_headline_and_scenarios_use_the_same_freshness_decision(invalid):
    pt = target(date.today() - timedelta(days=31) if invalid == "age" else None)
    fins = [] if invalid == "age" else [Financial(ticker="TEST", period="Q2 2026", period_end_date=date(2026, 6, 30))]
    g = {"stock": None, "decision": SimpleNamespace(final_signal="HOLD", confidence="high", position_sizing={}, risk_flags=[]),
         "pt": pt, "forecast": None, "judge": {}, "validation": {}, "score": None, "price": 100.,
         "bull": {}, "bear": {}, "theses": [], "financials": fins}
    summary = _summary_payload(g)
    note = _render("TEST", g, summary, [], None)
    assert summary["price_target"] is None
    assert "$177" not in note and "$150" not in note and "$250" not in note
    assert "Valuation unavailable / refresh required" in note
    assert ("more than 30 days" if invalid == "age" else "newer financial quarter") in note


@pytest.mark.asyncio
async def test_analysis_get_returns_a_display_copy_and_preserves_raw_reports():
    pt = target()
    raw = report_for(pt)
    old = deepcopy(raw)
    valuation = AnalysisReport(id=1, ticker="TEST", agent_type="valuation", run_date=date.today(),
                               report=raw, version=1, created_at=datetime.now(timezone.utc))
    news = AnalysisReport(id=2, ticker="TEST", agent_type="news", run_date=date.today(),
                          report={"summary": "Unchanged news."}, version=1, created_at=datetime.now(timezone.utc))
    db = SimpleNamespace(execute=AsyncMock(side_effect=[
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [valuation, news])),
        SimpleNamespace(scalar_one_or_none=lambda: pt),
        SimpleNamespace(scalar_one_or_none=lambda: date(2026, 6, 30)),
    ]))
    responses = await get_analysis_reports("TEST", db=db)
    assert responses[0].report["dcf_analysis"]["intrinsic_value_base"] is None
    assert responses[0].report["valuation_model"]["status"] == "refresh_required"
    assert valuation.report == old
    assert responses[1].report == news.report
