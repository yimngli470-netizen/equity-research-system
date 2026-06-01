"""calculate_score selects archetype-conditioned weights (roadmap 1.4).

Feature extraction is patched to fixed category values so the test isolates the *weighting* —
the composite must reflect the stock's archetype profile, not the default weights.
"""

from datetime import date

import pytest

from app.measurement.peer_normalize import PeerNormResult
from app.scoring.calculator import calculate_score
from app.scoring.weights import ARCHETYPE_WEIGHTS, DEFAULT_WEIGHTS
from tests.conftest import seed_stock

pytestmark = pytest.mark.integration

# Fixed category inputs (feature key "x" is unknown to the normalizer → passes through unchanged).
_HARD = {"growth": {"x": 0.8}, "profitability": {"x": 0.6}, "momentum": {"x": 0.4}, "valuation": {}}
_AI = {"sentiment": {"x": 0.5}, "event": {"x": 0.9}, "risk": {"x": 0.3},
       "ai_valuation": {"x": 0.5}, "validation": {}}
_CATS = {"growth": 0.8, "profitability": 0.6, "valuation": 0.6,  # val = 0.5*0.7 + 0.5*0.5
         "momentum": 0.4, "sentiment": 0.5, "risk": 0.3, "event": 0.9}


def _expected(weights):
    return round(sum(_CATS[c] * w for c, w in weights.as_dict().items()), 4)


@pytest.fixture
def _patch_features(monkeypatch):
    async def fake_hard(db, ticker):
        return _HARD

    async def fake_ai(db, ticker):
        return _AI

    async def fake_peer_val(db, ticker, raw):
        return PeerNormResult(normalized={"x": 0.7}, n_peer_relative=1, n_absolute=0, peer_count=4)

    monkeypatch.setattr("app.scoring.calculator.extract_all_hard_features", fake_hard)
    monkeypatch.setattr("app.scoring.calculator.extract_all_ai_features", fake_ai)
    monkeypatch.setattr("app.scoring.calculator.peer_relative_valuation", fake_peer_val)


async def test_cyclical_uses_its_own_weights_not_default(db, _patch_features):
    await seed_stock(db, "MU", archetype="cyclical-commodity")
    res = await calculate_score(db, "MU")  # weights=None → archetype-conditioned

    expected_cyc = _expected(ARCHETYPE_WEIGHTS["cyclical-commodity"])
    assert res.composite_score == pytest.approx(expected_cyc)
    assert res.composite_score != pytest.approx(_expected(DEFAULT_WEIGHTS))
    # category scores persisted as computed
    assert res.growth_score == pytest.approx(0.8)
    assert res.event_score == pytest.approx(0.9)


async def test_unclassified_stock_uses_default_weights(db, _patch_features):
    await seed_stock(db, "XYZ", archetype=None)
    res = await calculate_score(db, "XYZ")
    assert res.composite_score == pytest.approx(_expected(DEFAULT_WEIGHTS))


async def test_explicit_weights_override_archetype(db, _patch_features):
    await seed_stock(db, "MU", archetype="cyclical-commodity")
    res = await calculate_score(db, "MU", weights=DEFAULT_WEIGHTS)
    assert res.composite_score == pytest.approx(_expected(DEFAULT_WEIGHTS))
