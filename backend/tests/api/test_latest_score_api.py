"""GET /stocks/{ticker}/scores/latest — carries archetype + the actual weights (roadmap 1.4/1.5)."""

from datetime import date

import pytest

from app.scoring.weights import ARCHETYPE_WEIGHTS
from tests.conftest import seed_score, seed_stock

pytestmark = pytest.mark.api

TODAY = date(2026, 1, 1)


async def test_latest_score_includes_archetype_and_its_weights(db, client):
    await seed_stock(db, "MU", archetype="cyclical-commodity")
    await seed_score(db, "MU", TODAY, composite=0.85, signal="STRONG_BUY")

    body = (await client.get("/api/stocks/MU/scores/latest")).json()
    assert body["archetype"] == "cyclical-commodity"
    # The weights returned are the cyclical profile actually used, not the defaults.
    assert body["weights"] == ARCHETYPE_WEIGHTS["cyclical-commodity"].as_dict()
    assert body["weights"]["risk"] == 0.25
    assert body["weights"]["momentum"] == 0.05


async def test_unclassified_stock_returns_default_weights(db, client):
    await seed_stock(db, "XYZ", archetype=None)
    await seed_score(db, "XYZ", TODAY, composite=0.5, signal="HOLD")

    body = (await client.get("/api/stocks/XYZ/scores/latest")).json()
    assert body["archetype"] is None
    assert body["weights"]["growth"] == 0.2  # DEFAULT_WEIGHTS
