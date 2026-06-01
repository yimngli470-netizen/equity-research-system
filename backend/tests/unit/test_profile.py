"""Quant-profile math (roadmap 1.1) + the archetype grounding render."""

import pytest

from app.ingestion.archetype import _profile_lines
from app.measurement.profile import QuantProfile, _safe_div, _stats, _ttm

pytestmark = pytest.mark.unit


def test_ttm_sums_trailing_four_quarters():
    s = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _ttm(s, 3) == 10.0   # 1+2+3+4
    assert _ttm(s, 4) == 14.0   # 2+3+4+5


def test_ttm_none_when_window_incomplete_or_has_gap():
    assert _ttm([1.0, 2.0], 1) is None                  # i < 3
    assert _ttm([1.0, None, 3.0, 4.0], 3) is None       # missing quarter in window


def test_stats_tolerates_short_and_empty_lists():
    mean, std, mn = _stats([2.0])
    assert (mean, std, mn) == (2.0, 0.0, 2.0)
    assert _stats([]) == (None, None, None)


def test_safe_div_guards_zero_and_none():
    assert _safe_div(None, 1) is None
    assert _safe_div(1.0, 0) is None
    assert _safe_div(1.0, 2.0) == 0.5


def test_to_dict_drops_none_fields():
    p = QuantProfile(n_quarters=8, gross_margin_mean=0.5)
    d = p.to_dict()
    assert d["gross_margin_mean"] == 0.5
    assert "revenue_growth_std" not in d   # None values omitted


def test_profile_lines_grounds_the_prompt_on_the_numbers():
    # The LLM archetype call must SEE the measured numbers — this is what makes it "grounded".
    p = QuantProfile(
        n_quarters=12, revenue_growth_mean=0.10, revenue_max_drawdown=0.52, gross_margin_mean=0.32,
    )
    text = _profile_lines(p)
    assert "12 quarters" in text
    assert "52.0%" in text   # drawdown
    assert "32.0%" in text   # gross margin
