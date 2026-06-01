"""GET /api/scoring/screen (roadmap 1.5) — the peer-rank screen contract."""

from datetime import date

import pytest

from tests.conftest import seed_score, seed_stock

pytestmark = pytest.mark.api

TODAY = date(2026, 1, 1)


async def test_screen_ranks_by_composite_and_within_archetype(db, client):
    await seed_stock(db, "MU", archetype="cyclical-commodity")
    await seed_stock(db, "NVDA", archetype="secular-grower")
    await seed_stock(db, "MRVL", archetype="secular-grower")
    await seed_score(db, "MU", TODAY, composite=0.85, signal="STRONG_BUY")
    await seed_score(db, "NVDA", TODAY, composite=0.80, signal="STRONG_BUY")
    await seed_score(db, "MRVL", TODAY, composite=0.60, signal="BUY")

    resp = await client.get("/api/scoring/screen")
    assert resp.status_code == 200
    rows = resp.json()

    # Sorted by composite desc, ranked 1..N over the watchlist.
    assert [r["ticker"] for r in rows] == ["MU", "NVDA", "MRVL"]
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert all(r["total"] == 3 for r in rows)

    # Archetype-relative rank: NVDA #1 of 2 secular-growers, MRVL #2 of 2.
    by_ticker = {r["ticker"]: r for r in rows}
    assert by_ticker["NVDA"]["archetype_rank"] == 1
    assert by_ticker["NVDA"]["archetype_total"] == 2
    assert by_ticker["MRVL"]["archetype_rank"] == 2
    assert by_ticker["MU"]["archetype_rank"] == 1
    assert by_ticker["MU"]["archetype_total"] == 1


async def test_screen_omits_names_without_scores(db, client):
    await seed_stock(db, "MU", archetype="cyclical-commodity")
    await seed_stock(db, "NOSCORE")
    await seed_score(db, "MU", TODAY, composite=0.70, signal="BUY")

    rows = (await client.get("/api/scoring/screen")).json()
    assert [r["ticker"] for r in rows] == ["MU"]
