"""Peer-relative normalization math (roadmap 1.3) — the weighted-percentile core."""

import pytest

from app.measurement.peer_normalize import _FEATURE_COLUMN, _INVERT, _weighted_percentile

pytestmark = pytest.mark.unit

_EVEN = [(20.0, 1.0), (30.0, 1.0), (40.0, 1.0)]


def test_cheaper_multiple_scores_high_when_inverted():
    # P/E 10 vs peers 20/30/40 — cheapest → near 1.0
    assert _weighted_percentile(10.0, _EVEN, invert=True) > 0.9


def test_expensive_multiple_scores_low_when_inverted():
    assert _weighted_percentile(50.0, _EVEN, invert=True) < 0.1


def test_higher_is_better_when_not_inverted():
    pairs = [(0.1, 1.0), (0.2, 1.0), (0.3, 1.0)]
    assert _weighted_percentile(0.4, pairs, invert=False) > 0.9


def test_ties_count_half():
    # subject 10 equals two peers, two peers above → pct = (0 + 0.5*2)/4 = 0.25
    pairs = [(10.0, 1.0), (10.0, 1.0), (30.0, 1.0), (40.0, 1.0)]
    assert _weighted_percentile(10.0, pairs, invert=False) == pytest.approx(0.25)


def test_weights_bias_the_percentile():
    # a heavily-weighted cheap peer dominates: below-weight 10 of total 11
    pairs = [(5.0, 10.0), (100.0, 1.0)]
    assert _weighted_percentile(50.0, pairs, invert=True) == pytest.approx(1 - 10 / 11, abs=1e-3)


def test_every_inverted_feature_is_a_known_column():
    assert _INVERT <= set(_FEATURE_COLUMN)
