"""Peer recompute (roadmap 1.2) end-to-end on a seeded universe — the closeness property."""

import pytest
from sqlalchemy import select

from app.measurement.peers import recompute_peer_weights
from app.models.peer import PeerWeight
from tests.conftest import seed_financials, seed_prices, seed_stock

pytestmark = pytest.mark.integration


async def test_identical_names_are_closest_and_self_is_excluded(db):
    # TWIN_A and TWIN_B have identical fundamentals AND identical price paths.
    # ODD is different on both axes.
    for t in ("TWINA", "TWINB", "ODD"):
        await seed_stock(db, t)
    await seed_financials(db, "TWINA", gross_margin=0.6, op_margin=0.3, net_margin=0.2)
    await seed_financials(db, "TWINB", gross_margin=0.6, op_margin=0.3, net_margin=0.2)
    await seed_financials(db, "ODD", gross_margin=0.15, op_margin=-0.05, net_margin=-0.1)

    rising = [100.0 + i for i in range(70)]
    zigzag = [100.0 + (8 if i % 2 else 0) for i in range(70)]
    await seed_prices(db, "TWINA", rising)
    await seed_prices(db, "TWINB", rising)
    await seed_prices(db, "ODD", zigzag)

    n = await recompute_peer_weights(db)
    assert n == 6  # 3 names × 2 peers each

    rows = (await db.execute(select(PeerWeight).where(PeerWeight.ticker == "TWINA"))).scalars().all()
    by_peer = {r.peer: r for r in rows}

    # No self-pair; both other names present; all weights are valid 0..1.
    assert "TWINA" not in by_peer
    assert set(by_peer) == {"TWINB", "ODD"}
    assert all(0.0 <= r.weight <= 1.0 for r in rows)

    # The identical twin is the closest, by a clear margin, and near-maximal.
    assert by_peer["TWINB"].weight > by_peer["ODD"].weight
    assert by_peer["TWINB"].weight > 0.8
    # Components are recorded for audit; the twin's fundamentals match → sim ~ 1.0.
    assert by_peer["TWINB"].fundamental_sim == pytest.approx(1.0, abs=1e-6)


async def test_too_small_universe_writes_nothing(db):
    await seed_stock(db, "ONLY")
    await seed_financials(db, "ONLY")
    assert await recompute_peer_weights(db) == 0
