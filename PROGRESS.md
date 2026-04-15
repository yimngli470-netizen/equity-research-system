# Progress Tracker

## Phase 1: Foundation — COMPLETE (2026-04-13)
- [x] Project structure and Docker Compose (5 services: db, redis, backend, frontend, scheduler)
- [x] PostgreSQL + pgvector with initial Alembic migration (11 tables)
- [x] FastAPI backend: health check, stock CRUD, prices, scores, analysis endpoints
- [x] React frontend: Dashboard (stock grid + add form), StockDetail (score breakdown + reports)
- [x] Scheduler service running with daily cron stub
- [x] GitHub repo created (public): github.com/yimngli470-netizen/equity-research-system
- [x] NVDA added as first test stock

## Phase 2: Data Ingestion — COMPLETE (2026-04-13)
- [x] `ingestion/prices.py` — daily prices via yfinance (275 days per stock, upsert)
- [x] `ingestion/fundamentals.py` — quarterly financials (income, cash flow, balance sheet)
- [x] `ingestion/fundamentals.py` — valuation snapshots (forward P/E, PEG, P/S, EPS, margins)
- [x] `ingestion/news.py` — factual news from Yahoo Finance (free, no API key)
- [x] `ingestion/pipeline.py` — orchestrator with per-ticker error isolation
- [x] `ingestion/scheduler.py` — daily cron at 21:30 UTC wired to full pipeline
- [x] `api/ingestion.py` — manual trigger: `POST /api/ingestion/run`
- [x] New endpoints: `GET /stocks/{ticker}/financials`, `GET /stocks/{ticker}/valuation`
- [x] Valuations table + Alembic migration
- [x] Tested: NVDA, MU, AAPL — all zero errors
- [ ] `ingestion/transcripts.py` — earnings transcripts via SEC EDGAR (deferred to Phase 3)
- [ ] `ingestion/insider.py` — insider trades via SEC EDGAR (deferred)
- [ ] `ingestion/embeddings.py` — vector embeddings for documents (deferred to Phase 3)

## Phase 3: AI Research Agents — COMPLETE (2026-04-13)
- [x] `agents/base.py` — shared agent logic (Claude API call, caching by max_age_days, structured JSON output)
- [x] `agents/news_agent.py` — news impact scoring and sentiment (Sonnet 4, daily refresh)
- [x] `agents/earnings_agent.py` — earnings deep-dive, trend analysis (Opus 4, monthly refresh)
- [x] `agents/industry_agent.py` — cycle positioning, competitive landscape (Opus 4, weekly refresh)
- [x] `agents/valuation_agent.py` — DCF, multiples, target price range (Opus 4, weekly refresh)
- [x] `agents/orchestrator.py` — sequential agent execution per ticker with error isolation
- [x] `ingestion/computed_metrics.py` — derived growth rates, margins, momentum for agent context
- [x] `api/analysis.py` — POST /api/analysis/run, GET /api/analysis/agents
- [x] Tested: all 4 agents on NVDA with reports cached in analysis_reports table
- [ ] Frontend: render agent reports on StockDetail page (deferred to Phase 4/5)

## Phase 4: Quant & Scoring — COMPLETE (2026-04-14)
- [x] `quant/hard_features.py` — growth, profitability, valuation, momentum from computed metrics
- [x] `quant/ai_features.py` — sentiment, risk, event, valuation features from agent JSONB reports
- [x] `quant/normalizer.py` — piecewise linear normalization to 0-1 with per-feature configs
- [x] `scoring/weights.py` — configurable category weights (7 categories, sum to 1.0) + signal thresholds
- [x] `scoring/calculator.py` — weighted composite score, saves to quant_features + stock_scores tables
- [x] `api/scoring.py` — POST /api/scoring/run, GET /api/scoring/weights, GET /api/scoring/features/{ticker}
- [x] Frontend: ScoreCard shows composite score bar + signal badge on Dashboard
- [x] Frontend: StockDetail has "Calculate Score" button, agent reports show summary with expandable raw JSON
- [x] Tested: NVDA 0.76 STRONG_BUY (49 features), MU 0.77 STRONG_BUY (29), AAPL 0.60 HOLD (29)

## Phase 5: Decision Engine & Polish — NOT STARTED
- [ ] `decision/engine.py` — rule-based signal generation
- [ ] `decision/risk_flags.py` — critical/major/watch flag system
- [ ] Interactive DCF calculator (frontend)
- [ ] Stock comparison page
- [ ] Settings page (manage watchlist, adjust weights)
- [ ] Signal change alerts/notifications

## Known Issues / Notes
- Host port 5433 maps to Postgres container (5432 used by local Postgres)
- Frontend must use `import type` for TS interfaces (Vite strips them otherwise)
