"""End-to-end backend workflow: data ingestion → AI analysis → composite scoring.

This drives the REAL orchestration in one test — `ingest_ticker` → `run_all_agents` →
`calculate_score` → the screen API — with only the external boundaries faked:

  * SEC EDGAR `companyfacts` (a canned payload, so the real XBRL parser + financials spine run);
  * the Anthropic API (agents + archetype get canned structured responses);
  * the yfinance-backed sub-ingests (prices / valuation / estimates / news) and the transcript /
    IR scrapers (stubbed with canned data — they're network scrapers, not core logic).

So everything that's *our* logic runs for real: EDGAR parsing, archetype classification, all five
agents, AI-feature extraction, peer-relative valuation, archetype-weighted composite, the API.
No network, no real LLM. See ANALYST_ROADMAP.md / CLAUDE.md (Testing).
"""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.models.analysis import AnalysisReport
from app.models.financial import Financial
from app.models.score import QuantFeature
from app.models.stock import Stock
from tests.conftest import seed_stock

pytestmark = pytest.mark.e2e

TICKER = "TESTCO"


# ── canned external payloads ─────────────────────────────────────────────────

def _fake_companyfacts() -> dict:
    """Three fiscal years of quarterly XBRL facts → 12 quarters after the real parser runs."""
    def rec(start, end, val, fy, fp):
        return {"start": start, "end": end, "val": val, "fy": fy, "fp": fp, "filed": f"{fy + 1}-02-01"}

    rev, cor, oi, ni, eps, ocf = [], [], [], [], [], []
    for fy in (2022, 2023, 2024):
        quarters = {
            "Q1": (f"{fy}-01-01", f"{fy}-03-31"),
            "Q2": (f"{fy}-04-01", f"{fy}-06-30"),
            "Q3": (f"{fy}-07-01", f"{fy}-09-30"),
        }
        for fp, (s, e) in quarters.items():
            rev.append(rec(s, e, 1000.0, fy, fp))
            cor.append(rec(s, e, 600.0, fy, fp))
            oi.append(rec(s, e, 200.0, fy, fp))
            ni.append(rec(s, e, 150.0, fy, fp))
            eps.append(rec(s, e, 0.50, fy, fp))
        # Full-year facts so Q4 derives (FY − Q1 − Q2 − Q3).
        rev.append(rec(f"{fy}-01-01", f"{fy}-12-31", 4000.0, fy, "FY"))
        cor.append(rec(f"{fy}-01-01", f"{fy}-12-31", 2400.0, fy, "FY"))
        oi.append(rec(f"{fy}-01-01", f"{fy}-12-31", 800.0, fy, "FY"))
        ni.append(rec(f"{fy}-01-01", f"{fy}-12-31", 600.0, fy, "FY"))
        # Operating cash flow is filed cumulative YTD.
        ocf.append(rec(f"{fy}-01-01", f"{fy}-03-31", 250.0, fy, "Q1"))
        ocf.append(rec(f"{fy}-01-01", f"{fy}-06-30", 500.0, fy, "Q2"))
        ocf.append(rec(f"{fy}-01-01", f"{fy}-09-30", 750.0, fy, "Q3"))
        ocf.append(rec(f"{fy}-01-01", f"{fy}-12-31", 1000.0, fy, "FY"))

    return {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": rev}},
        "CostOfGoodsAndServicesSold": {"units": {"USD": cor}},
        "OperatingIncomeLoss": {"units": {"USD": oi}},
        "NetIncomeLoss": {"units": {"USD": ni}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": eps}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf}},
    }}}


# One superset report covering every field the AI-feature extractor reads across all five agents;
# saved as each agent's report, so each category picks up its own keys.
_AGENT_REPORT = {
    "overall_sentiment": 0.4,
    "items": [{"impact_score": 0.6, "impact_direction": "positive"}],
    "earnings_quality_score": 0.7,
    "trend_analysis": {"revenue_trend": "accelerating", "margin_trend": "expanding", "earnings_quality": "high"},
    "forward_outlook": {"revenue_direction": "accelerating", "margin_direction": "stable", "confidence": "high"},
    "risks": [{"severity": 0.3}],
    "transcript_analysis": {"management_tone": "confident"},
    "beat_miss_history": {"last_4q_eps_beats": 3, "avg_surprise_pct": 0.05, "trend": "improving"},
    "cycle_position": "mid_cycle",
    "competitive_position": {"market_share_trend": "gaining", "moat_strength": "strong"},
    "theme_exposures": [{"exposure_score": 0.7}],
    "industry_risks": [{"severity": 0.3}],
    "key_indicators": [{"signal": "bullish"}],
    "valuation_score": 0.6,
    "margin_of_safety": 0.2,
    "multiples_analysis": {"vs_historical": "discount", "vs_peers": "in_line"},
    "valuation_verdict": "moderately_undervalued",
    "target_price_range": {"mid": 120.0},
    "current_price": 100.0,
    "consensus_comparison": {"your_eps_vs_consensus": "above", "your_revenue_vs_consensus": "in_line"},
    "guidance_assessment": {"management_guidance_tone": "confident", "guidance_vs_consensus": "above"},
    "summary": {"reliability_score": 0.8, "total_checks": 10, "contradicted": 1},
}


class _FakeAnthropic:
    """Every agent gets the same canned JSON report."""

    def __init__(self, *a, **k):
        report = json.dumps(_AGENT_REPORT)

        class _Messages:
            def create(self, **kw):
                text = report
                return type("R", (), {"content": [type("C", (), {"text": text})()]})()

        self.messages = _Messages()


@pytest.fixture
def patch_world(engine, monkeypatch):
    """Redirect the pipeline/agents to the test DB and fake every external boundary."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    test_sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # The pipeline and orchestrator open their own sessions from these module-level names.
    monkeypatch.setattr("app.ingestion.pipeline.async_session", test_sm)
    monkeypatch.setattr("app.agents.orchestrator.async_session", test_sm)
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "test-key", raising=False)
    # No real third-party calls: FMP (earnings surprises) is gated on this key being set.
    monkeypatch.setattr("app.config.settings.fmp_api_key", None, raising=False)

    # EDGAR — keep the real parser, fake the HTTP.
    monkeypatch.setattr("app.ingestion.edgar.get_cik", lambda t: 1)
    monkeypatch.setattr("app.ingestion.edgar.fetch_companyfacts", lambda cik: _fake_companyfacts())

    # Archetype — keep the real grounding/scoring, fake the LLM + the yfinance company lookup.
    monkeypatch.setattr("app.ingestion.archetype._company_info",
                        lambda t, s: {"name": "Test Co", "sector": "Tech", "industry": "Semis",
                                      "summary": "", "ticker": t})
    monkeypatch.setattr("app.ingestion.archetype._classify",
                        lambda info, profile: {"archetype": "secular-grower",
                                               "rationale": "durable growth", "confidence": "high"})

    # Bootstrap (LLM KPI defs + IR scraping + file writes) — out of scope; no-op.
    from app.ingestion.bootstrap import BootstrapResult

    async def _noop_bootstrap(db, ticker, force=False):
        return BootstrapResult(ticker=ticker)

    monkeypatch.setattr("app.ingestion.bootstrap.bootstrap_ticker", _noop_bootstrap)

    # yfinance-backed sub-ingests + scrapers — stub with canned data (network, not core logic).
    async def _noop_update(ticker):
        return None

    async def _seed_prices(db, ticker):
        from app.models.price import DailyPrice
        start = date(2024, 1, 1)
        for i in range(80):
            px = 100.0 + i
            db.add(DailyPrice(ticker=ticker, date=start + timedelta(days=i), open=px, high=px,
                              low=px, close=px, adj_close=px, volume=1000))
        await db.commit()
        return 80

    async def _seed_valuation(db, ticker):
        from app.models.valuation import Valuation
        db.add(Valuation(ticker=ticker, date=date.today(), forward_pe=15.0, trailing_pe=20.0,
                         peg_ratio=1.5, price_to_sales=5.0, price_to_book=4.0, ev_to_revenue=5.0,
                         ev_to_ebitda=12.0, earnings_growth=0.2, revenue_growth=0.15,
                         market_cap=1.0e10, gross_margins=0.4, operating_margins=0.2))
        await db.commit()
        return True

    async def _zero(db, ticker):
        return 0

    monkeypatch.setattr("app.ingestion.pipeline._update_stock_info", _noop_update)
    monkeypatch.setattr("app.ingestion.pipeline.ingest_prices", _seed_prices)
    monkeypatch.setattr("app.ingestion.pipeline.ingest_valuation", _seed_valuation)
    monkeypatch.setattr("app.ingestion.pipeline.ingest_estimates_yf", _zero)
    monkeypatch.setattr("app.ingestion.pipeline.ingest_news", _zero)
    monkeypatch.setattr("app.ingestion.transcripts.ingest_transcripts", _zero)
    monkeypatch.setattr("app.ingestion.kpi_extractor.extract_kpis",
                        lambda db, ticker, force=False: _zero(db, ticker))

    # Agents — canned structured reports.
    monkeypatch.setattr("anthropic.Anthropic", _FakeAnthropic)

    return test_sm


# ── the end-to-end test ──────────────────────────────────────────────────────

async def test_full_backend_workflow(db, client, patch_world):
    await seed_stock(db, TICKER)

    # 1) INGEST — runs the real pipeline orchestration against the faked externals.
    from app.ingestion.pipeline import ingest_ticker
    ing = await ingest_ticker(TICKER)
    assert ing.errors == [], f"ingestion errors: {ing.errors}"
    assert ing.financials >= 6                       # EDGAR parser produced quarters
    assert ing.archetype == "secular-grower"         # grounded classification ran

    # 2) ANALYZE — all five agents run and persist reports.
    from app.agents.orchestrator import run_all_agents
    analysis = await run_all_agents(TICKER, force=True)
    assert analysis.all_succeeded, [r.error for r in analysis.results if not r.success]

    # 3) SCORE — composite from hard (EDGAR/valuation) + AI (agent) features, archetype-weighted.
    db.expire_all()  # other sessions committed; drop stale identity-map state
    from app.scoring.calculator import calculate_score
    score = await calculate_score(db, TICKER)

    # ── assert the chain landed end to end ──
    fin_count = (await db.execute(
        select(func.count()).select_from(Financial).where(Financial.ticker == TICKER)
    )).scalar()
    assert fin_count >= 6
    assert (await db.execute(
        select(func.count()).select_from(Financial)
        .where(Financial.ticker == TICKER, Financial.source == "edgar")
    )).scalar() == fin_count

    stock = await db.get(Stock, TICKER)
    assert stock.archetype == "secular-grower"
    assert stock.archetype_features  # grounding profile stored

    agent_types = set((await db.execute(
        select(AnalysisReport.agent_type).where(AnalysisReport.ticker == TICKER)
    )).scalars())
    assert agent_types == {"news", "earnings", "industry", "valuation", "validation"}

    feat_count = (await db.execute(
        select(func.count()).select_from(QuantFeature).where(QuantFeature.ticker == TICKER)
    )).scalar()
    assert feat_count > 0

    assert 0.0 < score.composite_score <= 1.0
    assert score.signal in {"STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"}

    # 4) API — the screen reflects the freshly-scored name.
    rows = (await client.get("/api/scoring/screen")).json()
    assert any(r["ticker"] == TICKER for r in rows)
    me = next(r for r in rows if r["ticker"] == TICKER)
    assert me["archetype"] == "secular-grower"
    assert me["rank"] == 1 and me["total"] == 1
