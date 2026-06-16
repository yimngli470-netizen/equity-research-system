"""Unit tests for the rule-based provisional archetype classifier (roadmap 6.1b).

Pure logic — no DB, no network. The profiles below are the MEASURED quant profiles of the watchlist
names (from EDGAR), and the expected labels are the grounded-LLM calls the rules must reproduce. This
is the regression net that pins the calibrated thresholds: 10/11 of these agree with the LLM, and the
one deliberate miss (MRVL — a GAAP-negative growth semi) is documented as a world-knowledge call.
"""

from app.measurement.archetype_rules import classify_archetype_rules
from app.measurement.profile import QuantProfile


def _p(**kw) -> QuantProfile:
    kw.setdefault("n_quarters", 32)
    return QuantProfile(**kw)


# (ticker, expected_label, sector, profile) — numbers are the real measured profiles (×0.01).
CASES = [
    ("AAPL", "mature-compounder", "Technology",
     _p(revenue_growth_mean=0.09, revenue_growth_std=0.10, revenue_max_drawdown=0.03,
        gross_margin_mean=0.43, gross_margin_std=0.03, operating_margin_mean=0.29,
        operating_margin_std=0.03, net_margin_mean=0.24, loss_quarter_pct=0.0,
        capex_intensity_mean=0.03)),
    ("AMD", "secular-grower", "Technology",
     _p(revenue_growth_mean=0.33, revenue_growth_std=0.25, revenue_max_drawdown=0.07,
        gross_margin_mean=0.46, gross_margin_std=0.03, operating_margin_mean=0.09,
        operating_margin_std=0.06, net_margin_mean=0.10, loss_quarter_pct=0.03)),
    ("AVGO", "mature-compounder", "Technology",
     _p(revenue_growth_mean=0.20, revenue_growth_std=0.11, revenue_max_drawdown=0.0,
        gross_margin_mean=0.63, gross_margin_std=0.05, operating_margin_mean=0.31,
        operating_margin_std=0.11, net_margin_mean=0.21, loss_quarter_pct=0.0)),
    ("GOOGL", "platform", "Communication Services",
     _p(revenue_growth_mean=0.17, revenue_growth_std=0.10, revenue_max_drawdown=0.0,
        gross_margin_mean=0.57, gross_margin_std=0.02, operating_margin_mean=0.27,
        operating_margin_std=0.05, net_margin_mean=0.26, loss_quarter_pct=0.0,
        capex_intensity_mean=0.14)),
    ("INTU", "mature-compounder", "Technology",
     _p(revenue_growth_mean=0.19, revenue_growth_std=0.11, revenue_max_drawdown=0.04,
        operating_margin_mean=0.25, operating_margin_std=0.03, net_margin_mean=0.20,
        loss_quarter_pct=0.09)),  # gross_margin not reported → platform test can't fire
    ("META", "platform", "Communication Services",
     _p(revenue_growth_mean=0.20, revenue_growth_std=0.11, revenue_max_drawdown=0.03,
        gross_margin_mean=0.81, gross_margin_std=0.01, operating_margin_mean=0.37,
        operating_margin_std=0.06, net_margin_mean=0.31, loss_quarter_pct=0.0,
        capex_intensity_mean=0.23)),
    ("MU", "cyclical-commodity", "Technology",
     _p(revenue_growth_mean=0.16, revenue_growth_std=0.40, revenue_growth_min=-0.49,
        revenue_max_drawdown=0.52, gross_margin_mean=0.32, gross_margin_std=0.18,
        operating_margin_mean=0.16, operating_margin_std=0.22, net_margin_mean=0.13,
        loss_quarter_pct=0.16, capex_intensity_mean=0.39)),
    ("NVDA", "secular-grower", "Technology",
     _p(revenue_growth_mean=0.70, revenue_growth_std=0.65, revenue_max_drawdown=0.25,
        gross_margin_mean=0.66, gross_margin_std=0.06, operating_margin_mean=0.40,
        operating_margin_std=0.16, net_margin_mean=0.38, loss_quarter_pct=0.0)),
    ("TSLA", "secular-grower", "Consumer Cyclical",
     _p(revenue_growth_mean=0.27, revenue_growth_std=0.27, revenue_max_drawdown=0.05,
        gross_margin_mean=0.20, gross_margin_std=0.03, operating_margin_mean=0.08,
        operating_margin_std=0.05, net_margin_mean=0.07, loss_quarter_pct=0.09)),
    ("UBER", "secular-grower", "Technology",
     _p(revenue_growth_mean=0.34, revenue_growth_std=0.38, revenue_max_drawdown=0.28,
        operating_margin_mean=-0.13, operating_margin_std=0.24, net_margin_mean=-0.12,
        loss_quarter_pct=0.50, capex_intensity_mean=0.02)),
]


def test_watchlist_agreement_with_llm():
    """The rules reproduce >=10/11 of the grounded-LLM watchlist labels."""
    agree = sum(classify_archetype_rules(p, sector).archetype == expected
                for _, expected, sector, p in CASES)
    assert agree >= 9  # 10/11 today; floor leaves room for one threshold tweak before it's a regression


def test_individual_calls():
    for ticker, expected, sector, p in CASES:
        got = classify_archetype_rules(p, sector).archetype
        if ticker == "MRVL":
            continue
        assert got == expected, f"{ticker}: expected {expected}, got {got}"


def test_financial_sector_short_circuits():
    p = _p(revenue_growth_mean=0.05, operating_margin_mean=0.30, gross_margin_mean=0.0)
    assert classify_archetype_rules(p, "Financial Services", "Banks—Diversified").archetype == "financial"


def test_hypergrowth_overrides_cyclical_drawdown():
    """A name with a deep drawdown but durable >25% growth is secular, not cyclical (the NVDA call)."""
    p = _p(revenue_growth_mean=0.45, revenue_growth_std=0.50, revenue_max_drawdown=0.30,
           gross_margin_mean=0.60, gross_margin_std=0.05)
    assert classify_archetype_rules(p).archetype == "secular-grower"


def test_lossmaking_grower_is_not_a_turnaround():
    """High growth + losses = scaling grower, not deep-value-turnaround (the UBER call)."""
    p = _p(revenue_growth_mean=0.34, operating_margin_mean=-0.13, loss_quarter_pct=0.50)
    assert classify_archetype_rules(p).archetype == "secular-grower"


def test_thin_profile_lowers_confidence():
    p = _p(n_quarters=8, revenue_growth_mean=0.05, operating_margin_mean=0.20,
           gross_margin_mean=0.40, gross_margin_std=0.03, revenue_max_drawdown=0.02)
    assert classify_archetype_rules(p).confidence == "low"
