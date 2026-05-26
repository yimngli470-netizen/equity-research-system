# AI-Augmented Equity Research System

## What This Is
A 6-layer AI-augmented equity research platform for personal stock analysis. Tracks a portfolio of stocks, runs AI-powered research agents, quantifies everything into composite scores, and generates buy/hold/sell signals. Full design in `PROJECT_PLAN.md`, progress in `PROGRESS.md`.

## Tech Stack
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, APScheduler
- **Database:** PostgreSQL 16 + pgvector (vector search for documents)
- **Frontend:** React + TypeScript + Vite + Tailwind CSS
- **Infrastructure:** Docker Compose (local), 5 services: db, redis, backend, frontend, scheduler
- **AI:** Claude API (Anthropic SDK) — Opus 4 for deep analysis, Sonnet 4 for daily tasks

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
    main.py                  # FastAPI app, CORS, 4 routers (stocks, ingestion, analysis, scoring)
    config.py                # Pydantic Settings (env vars: DATABASE_URL, ANTHROPIC_API_KEY, etc.)
    database.py              # Async SQLAlchemy engine, session factory, DeclarativeBase, get_db
    models/                  # SQLAlchemy ORM models (11 tables)
      stock.py               #   Stock (ticker PK, name, sector, industry, active)
      price.py               #   DailyPrice (ticker, date, OHLCV)
      financial.py           #   Financial (quarterly income/cashflow/balance), Segment
      valuation.py           #   Valuation (point-in-time: forward_pe, peg, margins, market_cap)
      document.py            #   Document (news articles, embedding Vector(1536))
      analysis.py            #   AnalysisReport (ticker, agent_type, run_date, report JSONB)
      score.py               #   QuantFeature (per-feature scores), StockScore (composite + signal)
      decision.py            #   StockDecision (raw/final signal, confidence, risk_flags JSONB, reasoning)
      earnings.py            #   EarningsEvent (beat/miss, guidance)
      insider.py             #   InsiderTrade
    schemas/stock.py         # Pydantic response models with from_attributes = True
    api/
      stocks.py              #   GET/POST /api/stocks/, prices, financials, valuation, scores, analysis
      ingestion.py           #   POST /api/ingestion/run
      analysis.py            #   POST /api/analysis/run, GET /api/analysis/agents
      scoring.py             #   POST /api/scoring/run, GET /api/scoring/weights, GET /api/scoring/features/{ticker}
      decision.py            #   POST /api/decision/run, GET /api/decision/{ticker}/latest
    ingestion/               # Layer 1: data collection
      pipeline.py            #   run_full_ingestion() orchestrator
      prices.py              #   Daily prices via yfinance (upsert)
      fundamentals.py        #   Quarterly financials + valuation snapshots via yfinance
      news.py                #   News articles from yfinance (STORY type only)
      fmp_client.py          #   FMP API client (250 calls/day free tier, rate-limited)
      transcripts.py         #   Orchestrator: FMP → IR scraper fallback chain, calendar-gated
      earnings_surprises.py  #   EPS beat/miss history from FMP → earnings_events table
      analyst_estimates.py   #   Consensus estimates from FMP → analyst_estimates table
      scheduler.py           #   APScheduler daily cron at 21:30 UTC
      computed_metrics.py    #   Derived growth rates, margins, momentum (on-the-fly, not stored)
      ir/                    #   IR-site transcript scraper (tier-3 fallback when FMP misses) — planned
        sources.yaml         #     Per-ticker IR config: URL + discovery strategy + artifact_type
        registry.py          #     Load/get/update IRSource; persists repaired strategies back to YAML
        fetcher.py           #     fetch_transcript_from_ir(ticker, year, quarter) main entry
        discovery.py         #     Programmatic link discovery (link_regex | css_selector | url_template)
        extract.py           #     Text extraction dispatcher (pdfplumber | beautifulsoup | python-pptx)
        repair.py            #     LLM-driven discovery fallback when programmatic strategy breaks
    agents/                  # Layer 2: AI research agents
      base.py                #   BaseAgent ABC: cache check → Claude API call → save JSONB
      news_agent.py          #   Sonnet 4, daily refresh, news sentiment + impact scoring
      earnings_agent.py      #   Opus 4, monthly refresh, earnings deep-dive + transcript analysis
      industry_agent.py      #   Opus 4, weekly refresh, cycle position + competitive landscape
      valuation_agent.py     #   Opus 4, weekly refresh, DCF + multiples + consensus comparison
      validation_agent.py    #   Sonnet 4, runs after all agents, cross-checks claims vs hard data
      orchestrator.py        #   run_all_agents() sequential execution, validation always last
      transcript_utils.py    #   Keyword-based transcript filtering for agent context windows
    quant/                   # Layer 3: feature extraction
      hard_features.py       #   31 features from financials: growth, profitability, valuation, momentum
      ai_features.py         #   32+ features from agent JSONB reports: sentiment, risk, event, ai_valuation, validation
      normalizer.py          #   Piecewise linear normalization to 0-1 with per-feature configs
    scoring/                 # Layer 4: composite scoring
      weights.py             #   7-category weights (sum to 1.0) + signal thresholds (configurable)
      calculator.py          #   Weighted composite score → signal, saves to quant_features + stock_scores
    decision/                # Layer 5: decision engine
      risk_flags.py          #   21 rules across 7 categories → CRITICAL/MAJOR/WATCH flags
      engine.py              #   Adjusts raw signal based on flags, assesses confidence, saves to stock_decisions
  alembic/                   # DB migrations
frontend/
  src/
    api/client.ts            # Typed API client: stocks, prices, scores, analysis, scoring endpoints
    pages/
      Dashboard.tsx          # Stock grid with score bars + signal badges, add-stock form
      StockDetail.tsx        # Score breakdown, Calculate Score button, agent report cards
    components/
      ScoreCard.tsx          # Card: ticker, price, change%, composite bar, signal badge
      ScoreBreakdown.tsx     # 7 category score bars with signal badge
```

## Architecture: How Data Flows

### Pipeline: Ingestion → Agents → Scoring
```
1. POST /api/ingestion/run {ticker}
   → prices.py: daily OHLCV from yfinance (upsert by ticker+date)
   → fundamentals.py: quarterly financials + valuation snapshot
   → news.py: recent news articles → documents table
   → (if FMP_API_KEY set):
     → transcripts.py: earnings call transcripts → earnings_transcripts table
     → earnings_surprises.py: EPS beat/miss history → earnings_events table
     → analyst_estimates.py: consensus estimates → analyst_estimates table

2. POST /api/analysis/run {ticker}
   → For each agent (news, earnings, industry, valuation):
     → Check cache: if analysis_reports row exists and is fresh (within max_age_days), return cached
     → Else: build context from DB → call Claude API → parse JSON → save to analysis_reports (JSONB)

3. POST /api/scoring/run {ticker}
   → hard_features.py: extract 31 features from computed_metrics (financials + prices + valuation)
   → ai_features.py: extract 22 features from cached agent JSONB reports
   → normalizer.py: normalize all features to 0-1
   → calculator.py: average features per category → weighted composite → signal
   → Save to quant_features + stock_scores tables

4. POST /api/decision/run {ticker}
   → Fetch latest stock_scores + quant_features from DB
   → risk_flags.py: evaluate 18 rules across 7 categories → list of RiskFlag(level, rule, category, message)
   → engine.py: adjust signal based on flags, assess confidence, generate reasoning
   → Save to stock_decisions table
```

### Agent Caching Strategy
Each agent has a `max_age_days` setting. When triggered:
- If a report exists in `analysis_reports` within that window → return cached (no API call)
- Else → call Claude, save new report
- `force=true` bypasses cache

| Agent | Model | Refresh | Purpose | Data Sources |
|-------|-------|---------|---------|-------------|
| News | Sonnet 4 | Daily | Factual news impact scoring | yfinance news |
| Earnings | Opus 4 | Monthly | Quarterly deep-dive + transcript analysis | yfinance financials + transcript (FMP → IR fallback) + FMP surprises |
| Industry | Opus 4 | Weekly | Cycle position, competitive landscape | yfinance + transcript competitive excerpts (FMP → IR fallback) |
| Valuation | Opus 4 | Weekly | DCF, multiples, consensus comparison | yfinance + FMP estimates + transcript guidance (FMP → IR fallback) |
| Validation | Sonnet 4 | Every run | Cross-check agent claims vs hard DB data | All agent reports + DB financials/valuation/estimates |

### Refresh Strategy
The system has two trigger paths with deliberately different cache semantics:

- **"Run Full Pipeline" button (frontend, `StockDetail.tsx`)** — passes `force=true` to `/api/analysis/run`. Bypasses the cache for all 5 agents → scoring → decision. This is the user-facing **hard refresh**: use it after earnings releases, news shocks, or any time you want guaranteed-fresh analysis. Cost: ~4 Claude calls (Sonnet news + 3 Opus + Sonnet validation) per click.
- **Daily scheduler (`ingestion/scheduler.py`, 21:30 UTC)** — runs ingestion for all active stocks. Agent/scoring/decision wiring is **not yet hooked up** ("What's Not Yet Built" item). When wired, it should run **cache-aware** (no `force`) so news refreshes daily but Opus agents only re-run when their windows lapse.

**Known staleness gotcha:** time-based caching alone can return a stale earnings report for up to 30 days after a new quarterly release (the cache window is exactly long enough to span an entire quarter). Mitigation by design: the user clicks the button after earnings. We rejected event-aware cache invalidation as overkill — the button's existence makes it unnecessary.

### Transcript Fallback Chain (planned, not yet built)
FMP free-tier coverage is sparse outside the largest names. The earnings/industry/valuation agents are transcript-hungry, so missing transcripts silently degrade analysis quality. The fallback chain is built into `ingestion/transcripts.py`:

```
For each (ticker, year, quarter) we don't yet have a transcript for:
  1. CALENDAR GATE — skip unless today is within [earnings_date, earnings_date + 7d]
     from earnings_events (sourced via FMP earnings calendar). Avoids pointless scrapes
     between earnings cycles, since transcripts only ship once per quarter.
  2. TIER 1: FMP — call fmp_client.get_earnings_transcript(ticker, year, quarter)
  3. TIER 2: IR scraper — call ir.fetcher.fetch_transcript_from_ir(ticker, year, quarter)
     a. Look up the ticker in ir/sources.yaml. Skip if no entry (no fallback configured).
     b. Apply the configured discovery strategy on the IR landing page to find the
        latest transcript/release URL.
     c. If discovery returns nothing → call ir.repair.repair_discovery() (Sonnet 4),
        which finds the link AND emits a replacement strategy. Persist the new strategy
        back to sources.yaml via registry.update_strategy() so the next run doesn't pay
        the LLM cost again.
     d. Fetch the document, dispatch to ir.extract by content-type (PDF/HTML/PPTX).
     e. Return IRFetchResult with content + source_url + artifact_type + has_qa.
  4. STORE — upsert into earnings_transcripts with source ∈ {fmp, ir_pdf, ir_html, ir_pptx},
     source_url, and has_qa. Then run transcript_summarizer (existing Sonnet pass).
  5. GIVE UP — if after 7d the transcript still isn't available anywhere, log a warning
     and wait for the next earnings date. Don't retry indefinitely.
```

**Schema additions to `earnings_transcripts`** (Alembic migration required when implementing):
- `source: str` — `"fmp" | "ir_pdf" | "ir_html" | "ir_pptx"`. Drives agent confidence weighting.
- `source_url: str | None` — original document URL for audit.
- `has_qa: bool` — true for full transcripts, false for press releases / slide decks. The earnings agent uses this to skip Q&A-tone features when absent.

**`ir/sources.yaml` schema** (one entry per ticker that needs fallback):
```yaml
AAPL:
  ir_url: https://investor.apple.com/investor-relations/default.aspx
  strategy: { type: link_regex, pattern: "(?i)Q\\d.*Transcript.*\\.pdf" }
  artifact_type: press_release   # honest labeling: Apple doesn't post transcripts
  notes: "Apple IR posts press release + 10-Q link only; no call transcript."
MSFT:
  ir_url: https://www.microsoft.com/en-us/investor/earnings/FY-{year}-Q{quarter}/...
  strategy: { type: url_template, pattern: "..." }
  artifact_type: transcript
```

Strategy types supported by `ir.discovery`:
- `link_regex` — find an `<a href>` whose text or URL matches a regex
- `css_selector` — CSS selector returning the transcript link
- `url_template` — direct URL with `{year}` / `{quarter}` interpolation (no scraping needed)

**Design rationale (why programmatic with LLM repair, not LLM-driven navigation):** per-scrape Claude calls × small watchlist × multi-weekly runs adds avoidable cost; LLMs hallucinate URLs in ways that are hard to debug; YAML configs are 5-minute fixes when IR sites redesign (1-2x/yr per ticker). LLM is the repair tool, not the runtime.

**Dependencies to add when implementing:** `pdfplumber`, `beautifulsoup4`, `python-pptx`, `pyyaml`. `httpx` is already a dep.

### Scoring System
**60+ features** across 9 extraction categories, mapped to **7 scoring categories** (+ validation meta-category):

| Scoring Category | Weight | Sources |
|-----------------|--------|---------|
| Growth (20%) | Revenue/EPS/NI YoY & QoQ, consistency, acceleration | hard_features |
| Valuation (20%) | 50% hard multiples (P/E, PEG, P/S) + 50% AI assessment | hard + ai_features |
| Profitability (15%) | Margins, margin trends, operating leverage, FCF conversion | hard_features |
| Event (15%) | Earnings quality, trend signals, forward outlook, management tone, beat/miss history | ai_features (earnings agent + FMP) |
| Momentum (10%) | 1M, 3M, 12M price returns | hard_features |
| Sentiment (10%) | News sentiment, industry cycle, indicator signals | ai_features (news + industry) |
| Risk (10%) | Risk severity, moat strength, market share trend | ai_features (earnings + industry) |

**Normalization**: each feature has a (low, high, invert) config. Values are linearly mapped to [0,1] and clamped. `invert=True` for metrics where lower is better (P/E, risk severity).

**Signal thresholds** on composite score: ≥0.75 STRONG_BUY, ≥0.60 BUY, ≥0.45 HOLD, ≥0.30 REDUCE, <0.30 SELL.

Missing categories (no agent reports yet) default to 0.5 (neutral).

### Decision Engine & Risk Flags
The decision engine sits on top of the scoring system. The raw composite score is purely mathematical (weighted average). The decision engine adds rule-based judgment to catch specific red flags that a simple average might wash out.

**Signal adjustment rules** (applied sequentially):
1. Any **CRITICAL** flag → cap signal at HOLD (never recommend buying)
2. Each **MAJOR** flag → downgrade signal by one step (max 2 downgrades from major flags)
3. **WATCH** flags → informational only, no signal change

Signal ladder: `SELL → REDUCE → HOLD → BUY → STRONG_BUY`

**Confidence assessment** (how much to trust the signal):
- **High**: 45+ features (all agents ran), ≤1 major flag
- **Moderate**: decent data but some flags, or 1 critical, or ≤3 major
- **Low**: <35 features (missing agent reports), or 2+ critical flags

**Risk flag rules** (18 rules across 7 categories):

| Level | Rule | Category | Condition (on normalized 0-1 features) |
|-------|------|----------|---------------------------------------|
| CRITICAL | ai_overvalued | valuation | `valuation_verdict_score < 0.15` — AI says significantly overvalued |
| CRITICAL | severe_decline_12m | momentum | `momentum_12m < 0.1` — severe 12-month price decline |
| CRITICAL | deteriorating_outlook | quality | `fwd_revenue_signal < 0.2` AND `fwd_margin_signal < 0.2` |
| MAJOR | extreme_pe | valuation | `forward_pe < 0.05` — extremely elevated P/E |
| MAJOR | high_peg | valuation | `peg_ratio < 0.1` — growth doesn't justify premium |
| MAJOR | low_valuation_score | valuation | valuation category score `< 0.25` |
| MAJOR | revenue_decline | growth | `revenue_yoy < 0.2` — revenue declining YoY |
| MAJOR | negative_operating_margin | profitability | `operating_margin < 0.05` |
| MAJOR | margin_compression | profitability | `gross_margin_change_yoy < 0.3` AND `operating_margin_change_yoy < 0.3` |
| MAJOR | sharp_decline_3m | momentum | `momentum_3m < 0.15` |
| MAJOR | low_earnings_quality | quality | `earnings_quality < 0.3` |
| MAJOR | value_trap | quality | valuation score `> 0.75` but profitability score `< 0.3` |
| WATCH | growth_deceleration | growth | `revenue_acceleration < 0.15` |
| WATCH | inconsistent_growth | growth | `growth_consistency < 0.3` |
| WATCH | op_margin_declining | profitability | `operating_margin_change_yoy < 0.2` (when no margin_compression) |
| WATCH | negative_leverage | profitability | `operating_leverage < 0.2` |
| WATCH | low_fcf_conversion | quality | `fcf_conversion < 0.1` |
| WATCH | dead_cat_bounce | momentum | `momentum_1m > 0.7` AND `momentum_12m < 0.3` |
| WATCH | negative_sentiment | sentiment | `news_sentiment < 0.15` |
| WATCH | high_industry_risk | sentiment | `industry_risk_avg < 0.2` (inverted: high risk = low score) |
| WATCH | weak_moat | sentiment | `moat_strength < 0.3` |
| WATCH | growth_valuation_gap | valuation | growth score `> 0.8` but valuation score `< 0.3` |
| WATCH | low_conviction | quality | all category scores between 0.35-0.65 |
| WATCH | fwd_revenue_weak | quality | `fwd_revenue_signal < 0.2` (when no deteriorating_outlook) |
| MAJOR | consistent_misses | quality | `eps_beat_rate < 0.25` — missed EPS in 3+ of last 4 quarters |
| WATCH | low_agent_reliability | quality | `agent_reliability < 0.4` — validation found significant contradictions |
| WATCH | management_evasive | quality | `management_tone < 0.2` — evasive/defensive tone on earnings call |

Note: feature thresholds are on **normalized** values (0-1), not raw values. E.g., `forward_pe < 0.05` means the P/E is extremely high (normalized inverted: expensive = low score).

### Computed Metrics (not stored — derived on-the-fly)
`ingestion/computed_metrics.py` builds a `ComputedSnapshot` from raw DB data:
- QoQ and YoY growth rates for revenue, gross profit, operating income, net income, EPS
- Margins: gross, operating, profit, FCF
- Margin changes QoQ/YoY
- Operating leverage, FCF conversion
- Price momentum (1M, 3M, 12M)

Used as context input for both AI agents and hard feature extraction.

## Key API Endpoints
```
GET  /api/health                          # Health check
GET  /api/stocks/                         # List all stocks with latest price
POST /api/stocks/                         # Add stock {ticker, name, sector?, industry?}
GET  /api/stocks/{ticker}/prices          # Price history
GET  /api/stocks/{ticker}/financials      # Quarterly financials
GET  /api/stocks/{ticker}/valuation       # Latest valuation multiples
GET  /api/stocks/{ticker}/scores/latest   # Latest composite score + signal
GET  /api/stocks/{ticker}/analysis        # Agent reports (filterable by agent_type)
POST /api/ingestion/run                   # Trigger data ingestion {tickers?: [...]}
POST /api/analysis/run                    # Run AI agents {ticker, agent_types?, force?}
POST /api/scoring/run                     # Calculate score {ticker, weights?}
GET  /api/scoring/weights                 # View default weights + thresholds
GET  /api/scoring/features/{ticker}       # View all normalized features
GET  /api/analysis/agents                 # List agents with cache settings + models
POST /api/decision/run                    # Run decision engine {ticker}
GET  /api/decision/{ticker}/latest        # Latest decision with risk flags
```

## Database
- **15 tables** across models/. Key tables: `stocks`, `daily_prices`, `financials`, `valuations`, `documents`, `analysis_reports` (JSONB), `quant_features`, `stock_scores`, `stock_decisions`, `earnings_transcripts`, `analyst_estimates`, `earnings_events`
- Migrations via Alembic: `docker compose exec backend alembic upgrade head`
- Postgres on host port 5433 (5432 used by local Postgres)

## Conventions
- Backend uses async everywhere (asyncpg, async SQLAlchemy sessions)
- All API responses validated by Pydantic schemas with `from_attributes = True`
- Frontend uses `import type` for TypeScript interfaces (Vite strips type-only exports at runtime)
- Docker volumes mount source code for hot-reload during development
- `.env` file at project root (copied from `.env.example`, gitignored) — contains ANTHROPIC_API_KEY, DATABASE_URL
- Agent reports stored as JSONB for schema flexibility across agent types
- Upserts use `on_conflict_do_update` on unique constraints for idempotent data ingestion

## Data Sources
| Source | Cost | Data | Tables |
|--------|------|------|--------|
| **yfinance** | Free | Prices, financials, valuation multiples, news | daily_prices, financials, valuations, documents |
| **FMP** | Free tier (250 calls/day) | Earnings transcripts (tier 1), EPS surprises, analyst estimates, earnings calendar | earnings_transcripts, earnings_events, analyst_estimates |
| **IR site scraper (planned)** | Free | Earnings transcripts / press releases / slides — tier-3 fallback when FMP has no coverage | earnings_transcripts (with `source` field) |
| **Claude API** | Per-token | AI analysis via 5 agents (news, earnings, industry, valuation, validation) + IR scraper repair fallback | analysis_reports |

FMP integration is gated behind `FMP_API_KEY` env var. If not set, FMP ingestion steps are silently skipped and agents fall back to yfinance-only context.

The IR scraper has no API key dependency but does require `backend/app/ingestion/ir/sources.yaml` to be populated for each ticker that needs fallback coverage. See **Transcript Fallback Chain** below.

## What's Not Yet Built
- Interactive DCF calculator (frontend)
- Stock comparison page
- Settings page (manage watchlist, adjust weights)
- Scheduler wiring: auto-run agents + scoring + decision after daily ingestion
- Document embeddings (pgvector) not yet active
- **IR transcript scraper (tier-3 fallback)** — designed in **Transcript Fallback Chain** above. Module layout staked out in `ingestion/ir/`; schema additions to `earnings_transcripts` pending Alembic migration. SEC EDGAR was considered and rejected (it doesn't host call transcripts, only 8-K press releases / 10-Q filings).
- Insider trades ingestion deferred
