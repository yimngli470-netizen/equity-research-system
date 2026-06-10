"""End-to-end backend workflow: data ingestion → AI analysis → composite scoring.

This drives the REAL orchestration in one test — `ingest_ticker` → `run_all_agents` →
`calculate_score` → the screen API — with only the external boundaries faked:

  * SEC EDGAR `companyfacts` (a canned payload, so the real XBRL parser + financials spine run);
  * the Anthropic API (agents + archetype get canned structured responses);
  * the yfinance-backed sub-ingests (prices / valuation / estimates / news) and the transcript /
    IR scrapers (stubbed with canned data — they're network scrapers, not core logic).

Beyond "it runs", it asserts the DATA FLOW end to end:
  1. the mocked ingestion data is persisted to the DB with the right values;
  2. that DB data actually appears in the prompt sent to the agents;
  3. the agents' output is correctly mapped into quant features and the composite score.

No network, no real LLM. See ANALYST_ROADMAP.md / CLAUDE.md (Testing).
"""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.models.analysis import AnalysisReport
from app.models.financial import Financial
from app.models.price import DailyPrice
from app.models.score import QuantFeature
from app.models.stock import Stock
from app.models.valuation import Valuation
from tests.conftest import seed_stock

pytestmark = pytest.mark.e2e

TICKER = "TESTCO"

# Sentinel values we can recognise downstream (in the DB, in the prompt, in the features).
Q_REVENUE = 5_000_000_000.0      # $5.00B/quarter
Q_COST = 3_000_000_000.0         # → gross profit $2.00B, gross margin 40%
Q_OPINC = 1_000_000_000.0        # operating margin 20%
Q_NETINC = 750_000_000.0         # $0.75B
Q_EPS = 0.50
FWD_PE = 13.3                    # distinctive → "Forward P/E: 13.3x" in the prompt


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
            rev.append(rec(s, e, Q_REVENUE, fy, fp))
            cor.append(rec(s, e, Q_COST, fy, fp))
            oi.append(rec(s, e, Q_OPINC, fy, fp))
            ni.append(rec(s, e, Q_NETINC, fy, fp))
            eps.append(rec(s, e, Q_EPS, fy, fp))
        # Full-year facts so Q4 derives (FY − Q1 − Q2 − Q3).
        rev.append(rec(f"{fy}-01-01", f"{fy}-12-31", Q_REVENUE * 4, fy, "FY"))
        cor.append(rec(f"{fy}-01-01", f"{fy}-12-31", Q_COST * 4, fy, "FY"))
        oi.append(rec(f"{fy}-01-01", f"{fy}-12-31", Q_OPINC * 4, fy, "FY"))
        ni.append(rec(f"{fy}-01-01", f"{fy}-12-31", Q_NETINC * 4, fy, "FY"))
        # Operating cash flow is filed cumulative YTD.
        for n, (fp, e) in enumerate(
            [("Q1", f"{fy}-03-31"), ("Q2", f"{fy}-06-30"), ("Q3", f"{fy}-09-30"), ("FY", f"{fy}-12-31")],
            start=1,
        ):
            ocf.append(rec(f"{fy}-01-01", e, 1_250_000_000.0 * n, fy, fp))

    return {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": rev}},
        "CostOfGoodsAndServicesSold": {"units": {"USD": cor}},
        "OperatingIncomeLoss": {"units": {"USD": oi}},
        "NetIncomeLoss": {"units": {"USD": ni}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": eps}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf}},
    }}}


# One superset report covering every field the AI-feature extractor reads across all five agents;
# saved as each agent's report, so each category picks up its own keys. The mapped feature values
# (asserted below) are: valuation_verdict moderately_undervalued → 0.75; cycle_position mid_cycle
# → 0.6; earnings_quality_score → 0.7.
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
    # Judge fields (2.1/2.4): a bear leaning here must cap the decision signal below the screen.
    # conviction is rubric-anchored off the unresolved-bear-point count (3 of 4 → low band).
    "leaning": "bear",
    "conviction": 0.3,
    "unresolved_bear_points": 3,
    "total_bear_points": 4,
}


@pytest.fixture
def patch_world(engine, monkeypatch):
    """Redirect the pipeline/agents to the test DB and fake every external boundary.

    Returns the list of prompts the agents 'sent' to the LLM, so the test can assert the DB data
    reached the prompt.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    captured_prompts: list[dict] = []

    class _FakeAnthropic:
        def __init__(self, *a, **k):
            class _Messages:
                def create(_self, *, system, messages, **kw):
                    captured_prompts.append({"system": system, "user": messages[-1]["content"]})
                    text = json.dumps(_AGENT_REPORT)
                    return type("R", (), {"content": [type("C", (), {"text": text})()]})()

            self.messages = _Messages()

    test_sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
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
        start = date(2024, 1, 1)
        for i in range(80):
            px = 100.0 + i
            db.add(DailyPrice(ticker=ticker, date=start + timedelta(days=i), open=px, high=px,
                              low=px, close=px, adj_close=px, volume=1000))
        await db.commit()
        return 80

    async def _seed_valuation(db, ticker):
        db.add(Valuation(ticker=ticker, date=date.today(), forward_pe=FWD_PE, trailing_pe=20.0,
                         peg_ratio=1.5, price_to_sales=5.0, price_to_book=4.0, ev_to_revenue=5.0,
                         ev_to_ebitda=12.0, earnings_growth=0.2, revenue_growth=0.15,
                         market_cap=1.0e11, gross_margins=0.4, operating_margins=0.2))
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

    return captured_prompts


# ── the end-to-end test ──────────────────────────────────────────────────────

async def test_full_backend_workflow(db, client, patch_world):
    captured_prompts = patch_world
    await seed_stock(db, TICKER)

    # ========== 1) INGEST → the real pipeline orchestration against the faked externals ==========
    from app.ingestion.pipeline import ingest_ticker
    ing = await ingest_ticker(TICKER)
    assert ing.errors == [], f"ingestion errors: {ing.errors}"
    assert ing.financials >= 6
    assert ing.archetype == "secular-grower"

    # --- (a) the mocked ingestion data is actually persisted, with the right values ---
    # EDGAR: a directly-filed quarter (Q3 2024) is parsed to exact values from the canned payload.
    q3 = (await db.execute(
        select(Financial).where(Financial.ticker == TICKER,
                                Financial.period_end_date == date(2024, 9, 30))
    )).scalar_one()
    assert q3.revenue == Q_REVENUE
    assert q3.gross_profit == Q_REVENUE - Q_COST       # derived: revenue − cost
    assert q3.operating_income == Q_OPINC
    assert q3.net_income == Q_NETINC
    assert q3.eps == Q_EPS
    assert q3.source == "edgar"

    # yfinance-stubbed valuation + prices landed too.
    val = (await db.execute(select(Valuation).where(Valuation.ticker == TICKER))).scalar_one()
    assert val.forward_pe == FWD_PE
    assert (await db.execute(
        select(func.count()).select_from(DailyPrice).where(DailyPrice.ticker == TICKER)
    )).scalar() == 80

    # ========== 2) ANALYZE → all five agents run and persist reports ==========
    from app.agents.orchestrator import run_all_agents
    analysis = await run_all_agents(TICKER, force=True)
    assert analysis.all_succeeded, [r.error for r in analysis.results if not r.success]

    agent_types = set((await db.execute(
        select(AnalysisReport.agent_type).where(AnalysisReport.ticker == TICKER)
    )).scalars())
    # Four analytical agents + the bull/bear/judge dialectic (2.1) + validation.
    assert agent_types == {"news", "earnings", "industry", "valuation",
                           "bull", "bear", "judge", "validation"}

    # --- (b) the DB data actually reached the agent prompt ---
    all_user_prompts = "\n\n".join(p["user"] for p in captured_prompts)
    assert TICKER in all_user_prompts
    assert f"Forward P/E: {FWD_PE:.1f}x" in all_user_prompts          # from the Valuation row
    assert f"${Q_REVENUE / 1e9:.2f}B" in all_user_prompts            # quarterly revenue from EDGAR

    # ========== 3) SCORE → AI features from agent reports feed the composite ==========
    db.expire_all()
    from app.scoring.calculator import calculate_score
    score = await calculate_score(db, TICKER)

    # --- (c) agent output is correctly mapped into quant features ---
    feats = {f.feature_name: f.feature_value for f in (await db.execute(
        select(QuantFeature).where(QuantFeature.ticker == TICKER)
    )).scalars()}
    assert feats["valuation_verdict_score"] == 0.75   # "moderately_undervalued" → 0.75
    assert feats["cycle_position_score"] == 0.6       # "mid_cycle" → 0.6
    assert feats["earnings_quality"] == 0.7           # earnings_quality_score passthrough

    # --- the composite is archetype-weighted, valid, and deterministic (golden value) ---
    from app.scoring.weights import ARCHETYPE_WEIGHTS
    assert score.signal in {"STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"}
    assert 0.0 < score.composite_score <= 1.0
    # Fully deterministic inputs → a fixed composite. A change to the scoring math (even to another
    # "valid" number) trips this. Update intentionally when the math legitimately changes.
    assert score.composite_score == pytest.approx(GOLDEN_COMPOSITE, abs=0.001)

    # ========== 4) DECIDE → the judge verdict binds the signal (2.4) ==========
    from app.decision.engine import run_decision
    dec = await run_decision(db, TICKER)
    # The quant screen is a BUY (composite 0.6373), but the bear-leaning, low-conviction judge
    # must cap the final signal below a buy — the reasoning layer binds the screen.
    assert dec.raw_signal == "BUY"
    assert dec.final_signal in {"HOLD", "REDUCE", "SELL"}
    assert dec.judge_leaning == "bear"
    assert dec.judge_conviction == pytest.approx(0.3)

    # running the decision also journals an immutable thesis snapshot (3.1).
    from app.models.thesis import StockThesis
    th = (await db.execute(select(StockThesis).where(StockThesis.ticker == TICKER))).scalar_one()
    assert th.leaning == "bear"
    assert th.decision_signal == dec.final_signal
    assert th.fair_value == 120.0          # from the canned valuation target mid
    assert th.status == "open"

    # position sizing (3.4): a capped-to-HOLD/REDUCE decision commits no new capital — the sizer
    # returns a 0% target with a non-accumulate action.
    sizing = dec.position_sizing
    assert sizing is not None
    assert sizing["action"] in {"hold", "trim", "exit"}
    assert sizing["target_weight_pct"] == 0.0
    assert sizing["max_weight_pct"] == 10.0

    # ========== 5) API → the screen reflects the freshly-scored name ==========
    rows = (await client.get("/api/scoring/screen")).json()
    me = next(r for r in rows if r["ticker"] == TICKER)
    assert me["archetype"] == "secular-grower"
    assert me["rank"] == 1 and me["total"] == 1


# Golden composite for the fully-deterministic fixture above (see the assertion in stage 3).
GOLDEN_COMPOSITE = 0.6373
