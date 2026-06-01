"""Peer-relative valuation (roadmap 1.3) against seeded peers — scoring + graceful fallback."""

from datetime import date

import pytest

from app.measurement.peer_normalize import peer_relative_valuation
from tests.conftest import seed_peer_weight, seed_stock, seed_valuation

pytestmark = pytest.mark.integration

TODAY = date(2026, 1, 1)


async def _seed_universe(db):
    # Subject MU plus four peers with a spread of forward P/E values.
    for t in ("MU", "P1", "P2", "P3", "P4"):
        await seed_stock(db, t)
        await seed_peer_weight(db, "MU", t, weight=0.5) if t != "MU" else None
    await seed_valuation(db, "MU", TODAY, forward_pe=10.0)
    await seed_valuation(db, "P1", TODAY, forward_pe=20.0)
    await seed_valuation(db, "P2", TODAY, forward_pe=30.0)
    await seed_valuation(db, "P3", TODAY, forward_pe=40.0)
    await seed_valuation(db, "P4", TODAY, forward_pe=50.0)


async def test_cheapest_pe_scores_high_against_peers(db):
    await _seed_universe(db)
    res = await peer_relative_valuation(db, "MU", {"forward_pe": 10.0})
    # MU is the cheapest of 4 peers → inverted percentile near 1.0, scored peer-relative.
    assert res.n_peer_relative == 1
    assert res.normalized["forward_pe"] > 0.9


async def test_falls_back_to_absolute_when_too_few_peers(db):
    # Only 2 peers carry forward_pe (< MIN_PEERS) → fall back to the absolute norm.
    await seed_stock(db, "MU")
    for t in ("P1", "P2"):
        await seed_stock(db, t)
        await seed_peer_weight(db, "MU", t, weight=0.5)
        await seed_valuation(db, t, TODAY, forward_pe=20.0)
    res = await peer_relative_valuation(db, "MU", {"forward_pe": 10.0})
    assert res.n_peer_relative == 0
    assert res.n_absolute == 1
    assert res.normalized["forward_pe"] is not None  # still scored, via absolute ruler


async def test_no_peer_graph_uses_absolute(db):
    await seed_stock(db, "MU")
    res = await peer_relative_valuation(db, "MU", {"forward_pe": 10.0})
    assert res.peer_count == 0
    assert res.normalized["forward_pe"] is not None


async def test_nonpositive_multiple_scores_zero(db):
    await _seed_universe(db)
    res = await peer_relative_valuation(db, "MU", {"forward_pe": -5.0})
    assert res.normalized["forward_pe"] == 0.0
