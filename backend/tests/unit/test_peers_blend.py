"""Peer-closeness math (roadmap 1.2) — fundamental similarity, the blend, standardization."""

import numpy as np
import pytest

from app.measurement.peers import _FEATURES, _blend, _fundamental_sim, _standardize
from app.measurement.profile import QuantProfile

pytestmark = pytest.mark.unit


def test_identical_profiles_have_similarity_one():
    z = np.array([0.5, -1.0, 2.0])
    assert _fundamental_sim(z, z.copy()) == pytest.approx(1.0)


def test_similarity_is_monotonic_in_distance():
    base = np.zeros(3)
    near = np.array([0.2, 0.0, 0.0])
    far = np.array([2.0, 0.0, 0.0])
    assert _fundamental_sim(base, near) > _fundamental_sim(base, far)
    assert 0.0 < _fundamental_sim(base, far) < 1.0


def test_blend_returns_fundamental_when_only_component():
    assert _blend(0.8, None, None) == pytest.approx(0.8)


def test_blend_treats_anticorrelation_as_not_close():
    # fundamental .8 (w .5), returns max(0,-0.9)=0 (w .5) → 0.4
    assert _blend(0.8, -0.9, None) == pytest.approx(0.4)


def test_blend_combines_fundamental_and_returns():
    # (.5*.6 + .5*.4) / 1.0
    assert _blend(0.6, 0.4, None) == pytest.approx(0.5)


def test_standardize_zscores_and_imputes_missing_to_zero():
    p1 = QuantProfile(n_quarters=10, gross_margin_mean=0.8)
    p2 = QuantProfile(n_quarters=10, gross_margin_mean=0.4)
    tickers, z = _standardize({"AAA": p1, "BBB": p2})
    j = _FEATURES.index("gross_margin_mean")
    assert tickers == ["AAA", "BBB"]
    # population z of [0.8, 0.4] → [+1, -1]
    assert z[0, j] == pytest.approx(1.0)
    assert z[1, j] == pytest.approx(-1.0)
    # an all-missing feature column stays 0 (mean-imputed), never NaN
    k = _FEATURES.index("revenue_growth_std")
    assert not np.isnan(z[:, k]).any()
    assert z[:, k].tolist() == [0.0, 0.0]
