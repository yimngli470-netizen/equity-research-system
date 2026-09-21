"""A generated forecast alone cannot qualify an unsupported GAAP earnings peer."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.forecast.model import COMPILER_VERSION, ScenarioPath, _add_months, compile_scenario
from app.models.financial import Financial
from app.models.forecast import Forecast
from app.models.peer import PeerWeight
from app.models.price import DailyPrice
from app.models.stock import Stock
from app.models.valuation import Valuation
from app.valuation_model.economics import Economics
from app.valuation_model.target import _comparable_anchor, _gaap_peer_baseline


AT = date(2026, 9, 20)
END = _add_months(AT, -1)


def history(ticker="PEER", incomes=None):
    if incomes is None:
        incomes = [100.] * 4
    return [Financial(ticker=ticker, period_end_date=_add_months(END, -3 * i),
                      revenue=1000., operating_income=125., net_income=ni,
                      shares_outstanding=100., free_cash_flow=100., stock_based_comp=0.) for i, ni in enumerate(incomes)]


def test_gaap_baseline_requires_complete_actuals_not_positive_forecast_eps():
    assert _gaap_peer_baseline(history(incomes=[None] * 4)) is None
    assert _gaap_peer_baseline(history(incomes=[100., None, 100., 100.])) is None
    assert _gaap_peer_baseline(history()[:3]) is None
    assert _gaap_peer_baseline(history(incomes=[-100.] * 4)) is None
    gap = history()
    gap[-1].period_end_date = _add_months(gap[-1].period_end_date, -3)
    assert _gaap_peer_baseline(gap) is None
    missing_shares = history()
    missing_shares[0].shares_outstanding = None
    assert _gaap_peer_baseline(missing_shares) is None


def test_gaap_baseline_includes_loss_quarters_with_positive_full_year():
    actuals = history(incomes=[-100., 100., 100., 100.])
    baseline = _gaap_peer_baseline(actuals)
    assert baseline["quarters"] == 4
    assert baseline["net_income"] == 200.
    assert baseline["operating_income"] == 500.
    assert baseline["net_factor"] == .4


def query_result(rows):
    return SimpleNamespace(scalars=lambda: rows)


@pytest.mark.parametrize("missing_gaap", [True, False])
@pytest.mark.parametrize("industry", ["Semiconductors", "Software - Application", " SOFTWARE - INFRASTRUCTURE "])
async def test_anchor_requires_supported_earnings_and_narrow_business_scope(missing_gaap, industry):
    stocks = [Stock(ticker=t, name=t, industry=industry, sector="Technology",
                    archetype="secular-grower") for t in ("VALID", "UNVERIFIED")]
    quarters = compile_scenario(ScenarioPath([.2] * 12, [.3] * 12, .8, 0.),
                                [1000.] * 4, END, 100.)
    forecasts = [Forecast(ticker=s.ticker, as_of=AT,
                         input_fingerprint={"compiler": COMPILER_VERSION},
                         projections={"base": {"quarters": quarters}}) for s in stocks]
    prices = [DailyPrice(ticker=s.ticker, date=AT, close=100.) for s in stocks]
    valuations = [Valuation(ticker=s.ticker, date=AT, market_cap=1e4) for s in stocks]
    actuals = history("VALID") + history("UNVERIFIED", [None] * 4 if missing_gaap else None)
    # Fake only persistence; all eligibility, EPS windows, and weighting run for real.
    db = SimpleNamespace(execute=AsyncMock(side_effect=[
        query_result([PeerWeight(peer=s.ticker, weight=1.) for s in stocks]),
        query_result(stocks), query_result(forecasts), query_result(prices),
        query_result(valuations), query_result(actuals),
    ]))
    subject = Economics("SUBJECT", industry, "Technology", "secular-grower", .2, .3, 1e4)
    pe, anchor = await _comparable_anchor(db, subject, AT)
    if industry != "Semiconductors":
        # Even two complete positive GAAP forecasts cannot establish a marketplace/SaaS match.
        assert pe is None and anchor["constituents"] == []
        assert "does not establish comparable business models" in anchor["reason"]
        assert "narrower business-model coverage" in anchor["reason"]
        db.execute.assert_not_awaited()
    elif missing_gaap:
        assert pe is None  # one supported peer cannot satisfy the two-peer minimum
        assert {c["ticker"] for c in anchor["constituents"]} == {"VALID"}
        assert anchor["exclusions"]["unsupported_gaap_history"] == 1
        assert anchor["excluded_gaap_peers"] == ["UNVERIFIED"]
    else:
        assert pe is not None and pe > 0
        assert {c["ticker"] for c in anchor["constituents"]} == {"VALID", "UNVERIFIED"}
        assert all(c["gaap_history"]["net_income"] == 400. for c in anchor["constituents"])
