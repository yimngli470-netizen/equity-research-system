"""Archetype weight profiles (roadmap 1.4) — the invariants that must never silently break."""

import pytest

from app.scoring.weights import ARCHETYPE_WEIGHTS, DEFAULT_WEIGHTS, weights_for_archetype

pytestmark = pytest.mark.unit


def test_all_archetype_profiles_sum_to_one():
    for name, w in ARCHETYPE_WEIGHTS.items():
        total = sum(w.as_dict().values())
        assert w.validate(), f"{name} weights sum to {total}, not 1.0"


def test_unknown_and_none_fall_back_to_default():
    assert weights_for_archetype(None).as_dict() == DEFAULT_WEIGHTS.as_dict()
    assert weights_for_archetype("not-a-real-archetype").as_dict() == DEFAULT_WEIGHTS.as_dict()


def test_each_known_archetype_maps_to_its_own_profile():
    for name, profile in ARCHETYPE_WEIGHTS.items():
        assert weights_for_archetype(name) is profile


def test_cyclical_profile_does_not_reward_peak_beats():
    # The deliberate design choice: a beat at the cycle peak is a warning, not a positive — so
    # `event` is not upweighted; risk leads and momentum is suppressed.
    cyc = ARCHETYPE_WEIGHTS["cyclical-commodity"].as_dict()
    assert cyc["event"] <= DEFAULT_WEIGHTS.event
    assert cyc["risk"] > DEFAULT_WEIGHTS.risk
    assert cyc["momentum"] < DEFAULT_WEIGHTS.momentum


def test_secular_grower_leans_into_growth():
    assert ARCHETYPE_WEIGHTS["secular-grower"].as_dict()["growth"] > DEFAULT_WEIGHTS.growth
