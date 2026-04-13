# AI-Augmented Equity Research System

## What This Is
A 6-layer AI-augmented equity research platform for personal stock analysis. Full architecture and design documented in `PROJECT_PLAN.md`. Current progress tracked in `PROGRESS.md`.

## Goals
- Track a personal portfolio of stocks with deep fundamental, industry, and sentiment analysis
- Use Claude API to power specialized research agents (news, earnings, industry, valuation)
- Quantify analysis into composite scores and generate buy/hold/sell signals
- Surface everything through a clean, interactive dashboard

## Tech Stack
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, APScheduler
- **Database:** PostgreSQL 16 + pgvector (vector search for documents)
- **Frontend:** React + TypeScript + Vite + Tailwind CSS
- **Infrastructure:** Docker Compose (local), 5 services: db, redis, backend, frontend, scheduler
- **AI:** Claude API (Anthropic SDK) for research agents

## How to Run
```bash
docker compose up -d          # Start all services
docker compose logs -f        # Watch logs
docker compose down           # Stop all services
```
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs (Swagger): http://localhost:8000/docs
- Postgres exposed on host port 5433 (not 5432, which is used by local Postgres)

## Project Structure
```
backend/
  app/
    main.py              # FastAPI app entry point
    config.py            # Pydantic settings (env vars)
    database.py          # SQLAlchemy async engine + session
    models/              # SQLAlchemy ORM models (11 tables)
    schemas/             # Pydantic request/response schemas
    api/stocks.py        # REST endpoints (CRUD stocks, prices, scores, analysis)
    ingestion/           # Layer 1: data collection (scheduler.py runs daily)
    agents/              # Layer 2: AI research agents
    quant/               # Layer 3: feature extraction
    scoring/             # Layer 4: composite scoring
    decision/            # Layer 5: signal generation
  alembic/               # DB migrations
frontend/
  src/
    api/client.ts        # API client + TypeScript interfaces
    pages/               # Dashboard, StockDetail
    components/          # ScoreCard, ScoreBreakdown
```

## 6 Layers
1. **Data Ingestion** — daily collection of prices, fundamentals, news, transcripts, insider trades
2. **AI Research Agents** — news analyst, earnings analyst, industry analyst, valuation analyst (Claude API)
3. **Quant Feature Engine** — hard quant, event-based, and AI-derived features normalized to 0-1
4. **Scoring System** — weighted composite score per stock across all feature categories
5. **Decision Engine** — rule-based signals (STRONG_BUY → SELL) with risk flag system
6. **Dashboard** — React UI with portfolio overview, stock deep-dive, DCF calculator, signals feed

## Conventions
- Backend uses async everywhere (asyncpg, async SQLAlchemy sessions)
- All API responses validated by Pydantic schemas with `from_attributes = True`
- Frontend uses `import type` for TypeScript interfaces (Vite strips type-only exports at runtime)
- Docker volumes mount source code for hot-reload during development
- `.env` file at project root (copied from `.env.example`, gitignored)
- DB migrations via Alembic: `docker compose exec backend alembic upgrade head`
