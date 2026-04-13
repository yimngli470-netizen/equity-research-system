# Progress Tracker

## Phase 1: Foundation — COMPLETE (2026-04-13)
- [x] Project structure and Docker Compose (5 services: db, redis, backend, frontend, scheduler)
- [x] PostgreSQL + pgvector with initial Alembic migration (11 tables)
- [x] FastAPI backend: health check, stock CRUD, prices, scores, analysis endpoints
- [x] React frontend: Dashboard (stock grid + add form), StockDetail (score breakdown + reports)
- [x] Scheduler service running with daily cron stub
- [x] GitHub repo created (public): github.com/yimngli470-netizen/equity-research-system
- [x] NVDA added as first test stock

## Phase 2: Data Ingestion — NOT STARTED
- [ ] `ingestion/prices.py` — fetch daily prices via yfinance
- [ ] `ingestion/fundamentals.py` — fetch quarterly financials via yfinance
- [ ] `ingestion/news.py` — fetch news articles via NewsAPI
- [ ] `ingestion/transcripts.py` — fetch earnings transcripts via SEC EDGAR
- [ ] `ingestion/insider.py` — fetch insider trades via SEC EDGAR
- [ ] `ingestion/embeddings.py` — generate vector embeddings for documents
- [ ] Wire all ingestion functions into `scheduler.py`
- [ ] Add manual trigger endpoint: `POST /api/ingestion/run`
- [ ] Test full ingestion pipeline for watchlist stocks

## Phase 3: AI Research Agents — NOT STARTED
- [ ] `agents/base.py` — shared agent logic (Claude API call, retry, structured output)
- [ ] `agents/news_agent.py` — news impact scoring and sentiment
- [ ] `agents/earnings_agent.py` — earnings deep-dive, tone analysis
- [ ] `agents/industry_agent.py` — cycle positioning, competitive landscape
- [ ] `agents/valuation_agent.py` — DCF, multiples, target price range
- [ ] `agents/orchestrator.py` — parallel agent execution per ticker
- [ ] Frontend: render agent reports on StockDetail page

## Phase 4: Quant & Scoring — NOT STARTED
- [ ] `quant/hard_features.py` — growth, profitability, valuation, momentum metrics
- [ ] `quant/event_features.py` — earnings surprise, guidance, insider signals
- [ ] `quant/ai_features.py` — sentiment, narrative change, risk, theme exposure
- [ ] `quant/normalizer.py` — normalize all features to 0-1
- [ ] `scoring/calculator.py` — weighted composite score
- [ ] `scoring/weights.py` — configurable category weights
- [ ] Frontend: score cards, breakdown bars, score history chart

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
