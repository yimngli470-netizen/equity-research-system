"""Archetype classification wiring (roadmap 1.1) with the LLM mocked.

Asserts the two things that make it trustworthy: the call is GROUNDED on the measured numbers,
and an out-of-vocabulary label is rejected rather than written.
"""

import json

import pytest

from app.ingestion.archetype import classify_archetype
from app.models.stock import Stock
from tests.conftest import seed_financials, seed_stock

pytestmark = pytest.mark.integration


async def test_classify_writes_label_features_and_is_grounded(db, mock_anthropic, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "test-key", raising=False)
    # Avoid the yfinance network lookup inside _company_info.
    monkeypatch.setattr("app.ingestion.archetype._company_info",
                        lambda t, s: {"name": "Micron", "sector": "Tech", "industry": "Semis", "summary": ""})
    mock_anthropic.set_response(json.dumps(
        {"archetype": "cyclical-commodity", "rationale": "deep drawdowns", "confidence": "high"}))

    await seed_stock(db, "MU")
    # A cyclical-ish series (volatile) so a profile is computable.
    await seed_financials(db, "MU", n=12, gross_margin=0.3, op_margin=0.1, net_margin=0.05)

    res = await classify_archetype(db, "MU")
    assert res.status == "ok"
    assert res.archetype == "cyclical-commodity"

    # Persisted with the grounding features attached.
    stock = await db.get(Stock, "MU")
    assert stock.archetype == "cyclical-commodity"
    assert stock.archetype_features and "gross_margin_mean" in stock.archetype_features
    assert stock.archetype_as_of is not None

    # The model actually SAW the measured numbers (grounding).
    assert "quant profile" in mock_anthropic.last_user.lower()
    assert "%" in mock_anthropic.last_user


async def test_unknown_archetype_is_rejected_not_written(db, mock_anthropic, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "test-key", raising=False)
    monkeypatch.setattr("app.ingestion.archetype._company_info",
                        lambda t, s: {"name": "X", "sector": None, "industry": None, "summary": ""})
    mock_anthropic.set_response(json.dumps({"archetype": "meme-stock", "rationale": "lol"}))

    await seed_stock(db, "ZZZ")
    await seed_financials(db, "ZZZ")
    res = await classify_archetype(db, "ZZZ")
    assert res.status == "failed"
    stock = await db.get(Stock, "ZZZ")
    assert stock.archetype is None


async def test_insufficient_history_returns_insufficient_data(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "test-key", raising=False)
    await seed_stock(db, "NEW")
    await seed_financials(db, "NEW", n=3)  # below MIN_QUARTERS
    res = await classify_archetype(db, "NEW")
    assert res.status == "insufficient_data"
