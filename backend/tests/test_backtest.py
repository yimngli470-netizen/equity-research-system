"""Unit tests for the backtest harness core (roadmap 6.3) — pure logic, no DB.

The correctness that matters most is NO LOOKAHEAD: a quarter must not be visible before its filing
would have been public, and forward returns must look strictly after the as-of date. Plus the screen
scorer (percentile ranking + valuation inversion) and the Spearman IC.
"""

from datetime import date

from app.backtest.evaluate import _spearman
from app.backtest.panel import (
    REPORTING_LAG_DAYS,
    TickerSeries,
    _available_financials,
    features_asof,
    forward_return,
    price_asof,
)
from app.backtest.screen import _percentile_rank, score_cross_section


class _Fin:
    def __init__(self, period_end, **kw):
        self.period_end_date = period_end
        self.filed_date = None  # default: no exact filing date → 75d-lag fallback (pre-M4 rows)
        for k, v in kw.items():
            setattr(self, k, v)


def _series_with_fins(fins):
    return TickerSeries(ticker="T", dates=[], closes=[], adj=[], financials=fins)


# ── No lookahead: reporting lag gates fundamentals ───────────────────────────
def test_reporting_lag_excludes_unfiled_quarter():
    q_end = date(2024, 3, 31)
    s = _series_with_fins([_Fin(q_end)])
    # The day after quarter-end: the 10-Q isn't public yet → excluded.
    assert _available_financials(s, q_end) == []
    assert _available_financials(s, q_end.replace(month=4, day=1)) == []
    # After the lag: visible.
    from datetime import timedelta
    assert len(_available_financials(s, q_end + timedelta(days=REPORTING_LAG_DAYS + 1))) == 1


def test_available_financials_newest_first():
    fins = [_Fin(date(2023, 3, 31)), _Fin(date(2023, 6, 30)), _Fin(date(2023, 9, 30))]
    s = _series_with_fins(fins)
    avail = _available_financials(s, date(2024, 6, 1))
    assert [f.period_end_date for f in avail] == [date(2023, 9, 30), date(2023, 6, 30), date(2023, 3, 31)]


def test_filed_date_gates_exactly():
    """M4: a row carrying the exact SEC filed_date is public the day AFTER filing — earlier than
    the 75d blanket for a typical ~35d filer, but never on the filing day itself."""
    q_end, filed = date(2024, 3, 31), date(2024, 5, 4)   # ~34d filer (AAPL-like)
    s = _series_with_fins([_Fin(q_end, filed_date=filed)])
    assert _available_financials(s, filed) == []                      # filing day: not yet
    assert len(_available_financials(s, date(2024, 5, 5))) == 1      # day after: visible
    # …which beats the 75d fallback (would have waited until mid-June)
    assert _available_financials(_series_with_fins([_Fin(q_end)]), date(2024, 5, 5)) == []


# ── No lookahead: prices ──────────────────────────────────────────────────────
def _price_series():
    dates = [date(2024, 1, d) for d in range(1, 11)]
    adj = [100.0 + i for i in range(10)]  # 100..109
    return TickerSeries(ticker="P", dates=dates, closes=adj[:], adj=adj[:], financials=[])


def test_price_asof_uses_only_past():
    s = _price_series()
    assert price_asof(s, date(2024, 1, 5)) == 104.0       # bar on the date
    assert price_asof(s, date(2024, 1, 7)) == 106.0
    assert price_asof(s, date(2023, 12, 31)) is None       # before history


def test_forward_return_looks_strictly_forward():
    s = _price_series()
    # from index 0 (100) forward 4 trading days → index 4 (104): +4%
    assert round(forward_return(s, date(2024, 1, 1), 4), 4) == 0.04
    # not enough forward history → None
    assert forward_return(s, date(2024, 1, 9), 5) is None


# ── Screen scorer ─────────────────────────────────────────────────────────────
def test_percentile_rank_and_invert():
    vals = {"a": 10.0, "b": 20.0, "c": 30.0}
    asc = _percentile_rank(vals, invert=False)
    assert asc["a"] == 0.0 and asc["c"] == 1.0
    inv = _percentile_rank(vals, invert=True)
    assert inv["a"] == 1.0 and inv["c"] == 0.0  # cheap (low) ranks high when inverted


def test_score_cross_section_rewards_growth_and_cheapness():
    # Two names: A is cheaper (low P/E) and faster-growing → should score higher than B.
    feats = {
        "A": {"rev_growth": 0.30, "pe": 10.0, "op_margin": 0.25, "mom_12m": 0.20},
        "B": {"rev_growth": 0.05, "pe": 40.0, "op_margin": 0.10, "mom_12m": 0.02},
        "C": {"rev_growth": 0.15, "pe": 25.0, "op_margin": 0.18, "mom_12m": 0.10},
    }
    scores = score_cross_section(feats)
    assert scores["A"] > scores["C"] > scores["B"]


# ── Spearman IC ───────────────────────────────────────────────────────────────
def test_spearman_monotonic():
    a = [1, 2, 3, 4, 5]
    assert round(_spearman(a, [10, 20, 30, 40, 50]), 4) == 1.0       # perfect rank agreement
    assert round(_spearman(a, [50, 40, 30, 20, 10]), 4) == -1.0      # perfect inversion


def test_features_asof_needs_enough_history():
    # No prices ⇒ no features regardless of fundamentals.
    s = _series_with_fins([_Fin(date(2023, 3, 31))])
    assert features_asof(s, date(2024, 6, 1)) is None
