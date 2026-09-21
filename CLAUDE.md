# AI-Augmented Equity Research System

## What This Is
A 6-layer AI-augmented equity research platform for personal stock analysis. Tracks a portfolio of stocks, runs AI-powered research agents, quantifies everything into composite scores, and generates buy/hold/sell signals.

**`ANALYST_ROADMAP.md` is the current source of truth** for direction and recent work — the long-term goal is an *auditable AI research analyst*, and the dated progress log there records what's been built (EDGAR financials spine, yfinance consensus, per-ticker KPI extraction, auto-bootstrap of new stocks, etc.). This file documents the standing architecture.

## Tech Stack
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic
- **Database:** PostgreSQL 16 + pgvector (vector search for documents)
- **Frontend:** React + TypeScript + Vite + Tailwind CSS
- **Infrastructure:** Docker Compose (local), 4 services: db, redis, backend, frontend (pull-model for all LLM analysis; the ONE scheduled job is an LLM-free daily data refresh — see Refresh Strategy)
- **AI:** Claude through a shared client factory — **Opus 5** for forecast, earnings, industry, valuation, debate, and judge; **Sonnet 5** for news and utilities. Validation is deterministic. Model IDs are set in `config.py` (`opus_model` / `sonnet_model`), overridable via `OPUS_MODEL` / `SONNET_MODEL`; callers declare a tier. Every LLM call uses `app/llm/client.py::make_llm_client()` to select the subscription CLI or explicit production API backend.

## How to Run
```bash
docker compose up -d          # Start all services
docker compose logs -f        # Watch logs
docker compose down           # Stop all services
```
- Frontend: http://localhost:3000
- Phone on the same Wi-Fi: http://10.0.0.71:3000 (verified 2026-09-20; check `ipconfig getifaddr en1` if the address changes). The Mac must be awake. Browser API requests use relative `/api` URLs through Vite's proxy, so the phone does not contact its own localhost.
- Backend API: http://localhost:8000
- API Docs (Swagger): http://localhost:8000/docs
- Postgres exposed on host port 5433 (not 5432, which is used by local Postgres)

### Dev vs Prod LLM backend
`APP_ENV` selects `backend/config/<APP_ENV>.yaml`; all callers use the same client factory.
If environment YAML is absent, `llm_backend` defaults to `claude_code`, not a paid API fallback.

| Env | `APP_ENV` | `llm_backend` | Pays via | Where |
|-----|-----------|---------------|----------|-------|
| **dev** (DEFAULT) | `dev` | `claude_code` | Claude plan usage limits; overage governed by account settings | this laptop / local docker |
| **prod** | `prod` | `api` | `ANTHROPIC_API_KEY` (per-token credits) | servers |

- **Dev (subscription):** the image includes Claude Code **2.1.278**, pinned in `backend/Dockerfile`
  when `INSTALL_CLAUDE_CLI=1`. Each completion uses `claude -p --output-format json` with
  `CLAUDE_CODE_OAUTH_TOKEN`. Set up the token with `claude setup-token`, store it in `.env`, then
  recreate the backend to pick it up. Missing CLI/token stops the call without API-key fallback.
  The adapter removes inherited API/provider overrides and alternate credentials, disables
  user/project settings, tools, and MCP servers, and logs the actual returned model IDs. The
  September 20 audit found first-party OAuth routing and no API key in the local runtime.
- **Billing boundary:** the current [official subscription guidance](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
  says the proposed monthly Agent SDK credit change is paused: `claude -p` still draws from plan
  usage limits. The lower, superseded section of that page is not the active policy. The user
  confirmed **Usage credits OFF on 2026-09-20**. That account setting controls paid overage; the
  application cannot guarantee it with a CLI flag. Routing guards prevent accidental API use but
  do not replace the account setting. Logged API-equivalent cost estimates are not billing receipts.
- **Prod (API key):** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` → sets
  `APP_ENV=prod` (→ `llm_backend=api`), passes `ANTHROPIC_API_KEY`, builds with `INSTALL_CLAUDE_CLI=0`
  (lean image, no CLI). The standard Anthropic SDK path, unchanged.
- **Secrets** (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`) live in gitignored `.env`, never in the
  committed `config/*.yaml` (which hold only the non-secret `llm_backend` switch).

The configured `claude-opus-5` and `claude-sonnet-5` are the latest models in their respective
families as checked on 2026-09-20 against the [official model configuration](https://code.claude.com/docs/en/model-config).
Sonnet was upgraded from 4.6; the CLI pin was upgraded from 2.1.183 to support the configured models.
Five mocked billing regressions verify the local routing protections without spending model usage.
Live subscription smoke checks returned both requested model IDs; the rebuilt image passed all
92 backend tests, and the frontend production build passed.

## Testing
One end-to-end test (`backend/tests/test_pipeline_e2e.py`) drives the full backend workflow —
`ingest_ticker` → `run_all_agents` → `calculate_score` → the screen API — in a single run. Only the
external boundaries are faked (SEC EDGAR HTTP, the Anthropic API, the yfinance/scraper sub-ingests);
everything that's our logic (EDGAR XBRL parsing, archetype grounding, the five agents, AI-feature
extraction, peer-relative valuation, archetype-weighted composite) runs for real. No network, no LLM.

- **DB strategy:** an ephemeral Postgres via **testcontainers** by default (what CI uses). For fast
  local runs, point at a throwaway DB instead:
  ```bash
  docker compose exec db psql -U researcher -d equity_research -c "CREATE DATABASE equity_research_test;"
  docker compose exec -e TEST_DATABASE_URL="postgresql+asyncpg://researcher:changeme_local_dev@db:5432/equity_research_test" \
    backend pytest -q
  ```
- **CI:** `.github/workflows/test.yml` runs the test (testcontainers) + frontend `tsc` on every push/PR.
- **Valuation regressions:** the valuation test modules cover dated earnings windows, company
  policies and peer eligibility, dilution and funded repurchases, estimate period/basis handling,
  and stale-value suppression across the decision, agent, and research-note surfaces. Use only a
  throwaway database: integration fixtures truncate tables.

## Project Structure
```
backend/
  app/
    main.py                  # FastAPI app, CORS, 5 routers (stocks, ingestion, analysis, scoring, decision)
    config.py                # Pydantic Settings (env vars: DATABASE_URL, ANTHROPIC_API_KEY, etc.)
    database.py              # Async SQLAlchemy engine, session factory, DeclarativeBase, get_db
    models/                  # SQLAlchemy ORM models
      stock.py               #   Stock (ticker PK, name, sector, industry, active)
      price.py               #   DailyPrice (ticker, date, OHLCV)
      financial.py           #   Financial (quarterly; EDGAR-sourced + provenance), Segment
      valuation.py           #   Valuation (multiples, margins, market_cap, analyst price targets)
      document.py            #   Document (news articles, embedding Vector(1536))
      analysis.py            #   AnalysisReport (ticker, agent_type, run_date, report JSONB)
      score.py               #   QuantFeature (per-feature scores), StockScore (composite + signal)
      decision.py            #   StockDecision (raw/final signal, confidence, risk_flags JSONB, reasoning)
      earnings.py            #   EarningsEvent (beat/miss, guidance)
      estimate.py            #   AnalystEstimate (forward EPS/rev consensus + as_of/revisions_30d)
      transcript.py          #   EarningsTranscript (text, summary JSONB, source, has_qa)
      key_metric.py          #   TickerKeyMetric (per-ticker KPI defs), TickerKpiValue (extracted values)
      onboarding.py          #   DevTickerBootstrapStatus (dev-only: auto-bootstrap status)
      insider.py             #   InsiderTrade (model only — ingestion deferred, unused)
    schemas/stock.py         # Pydantic response models with from_attributes = True
    api/
      stocks.py              #   GET/POST /api/stocks/, prices, financials, valuation, scores, analysis
      ingestion.py           #   POST /api/ingestion/run
      analysis.py            #   POST /api/analysis/run, GET /api/analysis/agents
      scoring.py             #   POST /api/scoring/run, GET /api/scoring/weights, GET /api/scoring/features/{ticker}
      decision.py            #   POST /api/decision/run, GET /api/decision/{ticker}/latest
      kill_signals.py        #   CRUD /api/kill-signals/{ticker} (+ /generate, /sync-judge)
    ingestion/               # Layer 1: data collection (all sources free)
      pipeline.py            #   run_full_ingestion() orchestrator (bootstrap → prices → financials → …)
      bootstrap.py           #   Auto-onboard new tickers: LLM KPI defs (IR URL is set MANUALLY at add-time — auto-discovery removed)
      edgar.py               #   SEC EDGAR XBRL — SOURCE OF TRUTH for financials (full history)
      prices.py              #   Daily prices via yfinance (upsert)
      fundamentals.py        #   yfinance: valuation snapshot + price targets; financials FALLBACK
      estimates_yf.py        #   Forward EPS/revenue consensus from yfinance → analyst_estimates
      news.py                #   News articles from yfinance (STORY type only)
      kpi_extractor.py       #   LLM: extract per-ticker KPI values from transcript → ticker_kpi_values
      fmp_client.py          #   FMP API client (free tier; only earnings_surprises uses it now)
      transcripts.py         #   Orchestrator: FMP → IR scraper fallback chain, calendar-gated
      earnings_surprises.py  #   EPS beat/miss history from FMP → earnings_events table
      computed_metrics.py    #   Derived growth rates, margins, momentum (on-the-fly, not stored)
      ir/                    #   IR-site scraper (BUILT): FMP-miss fallback + auto-discovery target
        sources.yaml         #     Per-ticker IR config: URL + discovery strategy + artifact_type
        registry.py          #     Load/get/update IRSource; persists repaired strategies back to YAML
        fetcher.py           #     fetch_transcript_from_ir(ticker, year, quarter) main entry
        discovery.py         #     Programmatic link discovery (link_regex | css_selector | url_template)
        extract.py           #     Text extraction dispatcher (pdfplumber | beautifulsoup | python-pptx)
        repair.py            #     LLM-driven discovery fallback when programmatic strategy breaks
    agents/                  # Layer 2: AI research agents
      base.py                #   BaseAgent ABC: cache check → Claude API call → save JSONB
      news_agent.py          #   Sonnet tier, daily refresh, news sentiment + impact scoring
      earnings_agent.py      #   Opus tier, monthly refresh, earnings deep-dive + transcript analysis
      industry_agent.py      #   Opus tier, weekly refresh, cycle position + competitive landscape
      valuation_agent.py     #   Opus tier, explains/challenges deterministic valuation + consensus comparison
      validation_agent.py    #   Deterministic claim checks after agents; no LLM
      orchestrator.py        #   run_all_agents(): analytical → bull/bear debate (1 call) → judge → validation
      debate.py              #   DebateAgent: one Opus call → both bull + bear report rows (roadmap 2.1)
      transcript_utils.py    #   Keyword-based transcript filtering for agent context windows
    forecast/                # Cited 12-quarter bear/base/bull assumptions → deterministic earnings/share paths
    valuation_model/
      economics.py           #   Versioned company policies, dated EPS windows, eligible weighted peers
      equity.py              #   Dated per-share equity distributions after funded repurchases
      target.py              #   Present DCF + 12/18-month scenario targets; persists auditable inputs
      presentation.py        #   Shared current-value/staleness guards for APIs, reports, and notes
      wacc.py                #   Measured rate inputs; current equity DCF uses cost_equity
      dcf.py                 #   Legacy implementation; not the current price-target calculator
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
   → bootstrap.py: if new ticker, auto-generate KPI defs (idempotent). IR earnings URL is provided by the user as a REQUIRED field on add (api/stocks.py writes it to sources.yaml) — LLM IR auto-discovery was removed (guessed non-obvious domains wrong too often, e.g. ISRG → isrg.intuitive.com)
   → prices.py: daily OHLCV from yfinance (upsert by ticker+date)
   → edgar.py: quarterly financials from SEC XBRL (source of truth); yfinance fallback if EDGAR fails
   → fundamentals.py: valuation snapshot + analyst price targets (yfinance .info)
   → estimates_yf.py: forward EPS/revenue consensus → analyst_estimates table
   → news.py: recent news articles → documents table
   → transcripts.py: earnings transcript (FMP if key set → IR scraper fallback) → earnings_transcripts
   → kpi_extractor.py: extract per-ticker KPI values from the transcript → ticker_kpi_values
   → (if FMP_API_KEY set) earnings_surprises.py: EPS beat/miss history → earnings_events

2. POST /api/analysis/run {ticker}
   → Build/reuse the cited 12-quarter forecast first (compiler + input fingerprint)
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
Three run modes (`/analysis/run` `mode` param; `agents/base.py`):
- **`smart` (default for the pipeline button, 2026-06-11)** — INPUT-fingerprint caching: each report
  stores a fingerprint of the data it was built from (`agents/fingerprints.py`: latest filing,
  transcript, estimates hash, price ±5% band, news marker… + a hash of the system prompt, so prompt
  edits auto-invalidate). Re-run only if the fingerprint changed; otherwise reuse, zero LLM. Cascade
  is automatic: new quarter → earnings re-runs → debate fingerprint (upstream report ids) breaks →
  judge re-runs. News only re-litigates the debate via a **materiality trigger** (sentiment swing
  >0.3 or a new high-impact report). Safety ceiling `smart_max_age_days` (35d; news 3d).
- **`cache`** — legacy time-based `max_age_days` window.
- **`force`** — always call the LLM.
Caching the judge is deliberate: identical bull/bear inputs ⇒ identical verdict; re-rolling adds
conviction noise, not information. `snapshot_thesis` also dedups — an unchanged verdict doesn't
journal a duplicate thesis (would poison calibration with pseudo-replication).

| Agent | Model | Refresh | Purpose | Data Sources |
|-------|-------|---------|---------|-------------|
| Forecast | Opus 5 | Input fingerprint, typically quarterly | Cited assumption paths compiled deterministically | Filed drivers, guidance, dated consensus |
| News | Sonnet 5 | Daily | Factual news impact scoring | yfinance news |
| Earnings | Opus 5 | Monthly | Quarterly deep-dive + transcript analysis | yfinance financials + transcript (FMP → IR fallback) + FMP surprises |
| Industry | Opus 5 | Weekly | Cycle position, competitive landscape | yfinance + transcript competitive excerpts (FMP → IR fallback) |
| Valuation | Opus 5 | Weekly / input fingerprint | Explains and challenges the shared deterministic DCF/target; numeric outputs come from the calculator | Filed financials + own forecasts + eligible peers + dated yfinance consensus + transcript guidance |
| Bull + Bear (debate) | Opus 5 | Every run | Strongest honest bull AND bear case — **one Opus call** (`debate.py`) writes both rows | Shared evidence pack (financials + archetype + screen + analyst reports) |
| Judge | Opus 5 | Every run | Reconciles bull vs bear → leaning + rubric-anchored conviction + dated kill-criteria | Bull + bear cases |
| Validation | **None (deterministic)** | Every run | Re-derive numeric claims vs hard DB data (no LLM) | All agent reports + DB financials/valuation/estimates |

### Current Valuation Model (2026-09-20)

The [valuation audit](docs/valuation-audit-2026-09-07.md) records the defects that motivated this
repair. `valuation_model/target.py` is the single numeric source for the decision panel, valuation
agent, and research note. `economics.py` versions the policy (`economics-2026-09-20.3`). The LLM
supplies cached, cited assumptions and explains their implications; it does not calculate a second
fair value or adjust the deterministic result to match the current price or Street target.

- **Dates and earnings basis:** each bear/base/bull forecast needs 12 explicit quarterly revenue
  growth and operating-margin assumptions. The compiler records adjustments and rejects nonfinite
  inputs; it no longer caps every company's operating margin at 60%. The target defaults to 12
  months and the calculator also supports 18 months. Its multiple leg uses modeled GAAP EPS for the
  **12 months after the target date**. Calendar windows prorate partial quarters, disclose approximate
  quarter dates, and require complete coverage. Present DCF fair value and the future price target
  are separate outputs; the target is not today's blended value multiplied by cost of equity.
- **Company economics:** a cached archetype selects a starting policy, then each scenario's revenue
  growth, operating margin, and cash generation determine its method and growth duration. Profitable
  noncyclicals reach mature growth in years 5–10 according to forecast growth; there are no ticker
  exceptions or automatic premiums for smaller market capitalization. Policy coefficients, terminal
  growth, and sustainable ROE are declared assumptions, not fitted or calibrated findings.
- **Comparable multiples:** require at least two fresh companies in the same industry with compatible
  cycle characteristics, positive earnings, and complete modeled GAAP EPS for the same current
  next-12-month window. Each peer also needs four consecutive actual quarters of net income,
  operating income, revenue, and shares, with positive aggregate net and operating income. Provider
  buckets `Software - Application` and `Software - Infrastructure` remain DCF-only until narrower
  business-model coverage can establish suitable peers; sharing a broad software label is insufficient.
  Use an economic-distance weighted median; growth, margins, leverage, and
  measured similarity affect weights, while size supplies only a secondary symmetric penalty. A
  bounded growth/margin adjustment applies to every scenario, including base. If eligible peers are
  insufficient, use DCF alone with an explicit reason; never substitute unrelated universe names,
  provider EPS of unknown basis, the subject's own spot P/E, or an invented default multiple.
- **Cyclicals and unsupported businesses:** cyclical DCF tails revert to normalized earning power;
  the multiple leg requires measured historical through-cycle P/E based on filed earnings. Missing
  history removes that leg. Financial businesses need a separate capital/distribution model and
  remain unavailable; loss-making or transition businesses cannot receive a P/E valuation.
- **Cash-flow/share consistency:** `equity.py` values an equity cash-flow proxy at **cost of equity**,
  assumes zero net borrowing, and does not subtract net debt again. Cash conversion is measured from
  consecutive filed FCF and earnings, including negative quarters; missing or unstable data does not
  receive a conversion floor. Historical SBC/revenue estimates compensation in each forecast
  quarter. Desired gross repurchases are `max(0, SBC - requested net share issuance × reference price)`,
  with the constant reference price disclosed. Funded repurchases are capped at that quarter's
  modeled FCF; unmet retirements remain as additional shares in every later quarter. This produces
  a warning and recomputed EPS, DCF, and multiple values, rather than rejecting a positive-FCF
  company solely because its requested buybacks exceed available cash. Peer EPS uses the same
  funding adjustment. The original forecast is preserved beside the funded share path and its
  adjustment audit. Remaining distributions use each quarter's funded shares, including dilution
  after the target date. Negative projected FCF or an unsupported cash-flow basis remains unavailable:
  no cash reserves, borrowing, or issuance proceeds are invented. Beyond the explicit forecast,
  shares freeze, compensation is cash
  settled, and the cash bridge fades to terminal retention implied by growth and declared sustainable
  ROE. The future DCF excludes distributions before its target date. Cash streams, share counts,
  funding assumptions, and sensitivity to cost of equity/terminal growth are saved for inspection.
- **Filed input repairs:** EDGAR accepts `ProfitLoss` only after exact-filing/period reconciliation
  against diluted EPS and diluted weighted shares (within reported EPS rounding), or an explicit
  minority-interest deduction; an available parent `NetIncomeLoss` takes priority. Capex includes
  `PaymentsForCapitalImprovements`. The forecast's starting share count uses the greater of filed
  quarterly diluted shares and period-end basic shares as a disclosed conservative proxy; issued
  shares including treasury stock are excluded. Annual weighted diluted shares are not subtracted
  to invent a Q4 denominator. These repairs restored AVGO earnings and GLW cash-flow/share coverage.
- **Labels and freshness:** the second view is **Operating sensitivity**, a normalized after-tax
  operating-income-to-cash bridge, not company-reconciled non-GAAP EPS. It holds the GAAP-funded
  share path fixed; if this optional sensitivity cannot fund that path, its reason is shown without
  suppressing an otherwise valid GAAP valuation. Analyst estimates retain
  period type/key, date precision, accounting basis, and as-of date; legacy/unknown-basis estimates
  cannot silently become same-period GAAP comparisons. Targets show model, forecast, target, price,
  and Street dates. Shared presentation guards hide incompatible model versions, stale targets,
  and targets predating newer financials. Agent API responses hydrate numeric fields from the latest
  valid target and identify stale narrative without rewriting historical report storage; notes use
  the same guard for headlines and scenario tables. Missing or unsupported required inputs produce
  an unavailable result with reasons, rather than an older target or invented fallback value.

Scenario probabilities come from the judge when valid; a refresh without a current judge explicitly
uses a provisional 25%/50%/25% bear/base/bull prior. These are conditional valuation scenarios, not
automatic entry prices. A target more than 20% below the reference price alongside BUY/STRONG_BUY
adds an assumption/thesis-conflict notice; targets do not independently rewrite the binding decision
or position sizing. The live calculator rejects historical/future `as_of` overrides because its
current rate and normalization inputs are not a point-in-time replay; use stored dated artifacts for
historical review.

### Refresh Strategy
The system is **pull-model for LLM work**: no agent, judge, or scoring run ever fires on a timer (decision 2026-06-11: avoid unattended LLM cost; the old `scheduler` service + `ingestion/scheduler.py` were removed 2026-06-19). The trigger paths:

- **"Run Full Pipeline" button (frontend, `state/pipelineTracker.ts`)** — runs the WHOLE chain for the ticker: `/ingestion/run` (incl. bootstrap, EDGAR financials, consensus, transcript fetch, KPI extraction) → `/analysis/run` with **`mode: "smart"`** → `/scoring/run` → `/decision/run`. Quiet day: ~0 LLM calls (cached agents reused; scoring/decision still recompute fresh from daily prices). News day: ~1 Sonnet. Earnings day: the new filing auto-invalidates the cascade (~6 calls). The UI shows "N re-ran · M reused (inputs unchanged)". (The same chain is also reachable via the API endpoints directly.)

- **Daily data refresh (`ingestion/daily_job.py`, APScheduler in the FastAPI lifespan)** — the one scheduled job, and it makes **zero LLM calls**: it runs `ingest_ticker(..., data_only=True)`, which skips bootstrap, archetype, transcripts, and KPI extraction. It exists so a company *reporting* is noticed without you clicking anything. Config: `DAILY_DATA_JOB` (default true), `DAILY_DATA_JOB_HOUR` (7), `DAILY_DATA_JOB_TIMEZONE` (America/New_York). Force one with `POST /api/ingestion/daily-refresh`. This is the roadmap:649 carve-out — the no-scheduler rule was about LLM cost, and this job has none.
- **Post-earnings notification (`earnings_watch.py` → `GET /api/stocks/earnings-alerts`)** — compares the latest reported quarter against the quarter baked into the earnings agent's stored `input_fingerprint`. When the company has reported since the agent ran, the dashboard shows a banner + a dot on the row. It **notifies, never runs** — spending the Opus call stays your click.

**The old staleness gotcha is FIXED by smart mode:** time-based caching could return a stale earnings report for up to 30 days after a new quarterly release; fingerprint invalidation re-runs the earnings agent the moment a new filing/transcript is ingested, no button-clicking discipline required.

### Transcript Fallback Chain (BUILT)
FMP free-tier coverage is sparse outside the largest names. The earnings/industry/valuation agents are transcript-hungry, so missing transcripts silently degrade analysis quality. The fallback chain lives in `ingestion/transcripts.py`:

```
For each (ticker, year, quarter) we don't yet have a transcript for:
  1. CALENDAR GATE — skip unless today is within [period_end + 14d, period_end + 120d].
     Avoids pointless scrapes between earnings cycles (transcripts ship once per quarter).
  2. TIER 1: FMP — call fmp_client.get_earnings_transcript(ticker, year, quarter)
  3. TIER 2: IR scraper — call ir.fetcher.fetch_transcript_from_ir(ticker, year, quarter)
     a. Look up the ticker in ir/sources.yaml. Skip if no entry (no fallback configured).
     b. Apply the configured discovery strategy on the IR landing page to find the
        latest transcript/release URL.
     c. If discovery returns nothing → call ir.repair.repair_discovery() (Sonnet tier),
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

**Dependencies (installed):** `pdfplumber`, `beautifulsoup4`, `python-pptx`, `pyyaml`, `curl_cffi`, `playwright` (+ Chromium, installed in the Docker image).

**Fetch chain (`discovery._fetch` / `fetcher._download`):** `curl_cffi` Chrome-TLS impersonation (PRIMARY) → headless Chromium render (`ir/render.py`, for JS-injected links) → give up. curl_cffi is the primary because plain httpx and even a headless browser get reset by WAF **JA3/TLS-fingerprint blocking** (see note below); it's also cheaper than spawning a browser.

**IR reachability note:** IR sites block automated clients at two different layers.
- **IP-level** (MU, TSLA, AVGO): block this project's *datacenter* IP (timeout/403); reachable from a residential IP, so the scraper works when the app runs on the user's own machine.
- **Fingerprint-level** (ISRG, likely UBER/FIG): WAF resets the connection on the TLS/HTTP2 handshake fingerprint (JA3), *before* any HTTP body or JS — so it defeats plain httpx (RemoteProtocolError/ReadTimeout) AND headless Chromium (ERR_HTTP2_PROTOCOL_ERROR), even from a residential IP (a HEAD returns 200 while GET is reset). The fix is `curl_cffi` browser-TLS impersonation, which speaks a real Chrome JA3 and is let through. A headless browser cannot beat this — the block is below the browser layer.

Note: ISRG (like Apple) posts **no text transcript** — its `sources.yaml` strategy targets the *"Intuitive Announces [Ordinal] Quarter Earnings"* press release (financials + da Vinci procedure/installed-base KPIs), NOT the conference-call event page (register/webcast boilerplate). When configuring a new IR site, point the link_regex at the press release, not the event/webcast page.

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
POST /api/decision/run                    # Run decision engine {ticker} (incl. position sizing)
GET  /api/decision/{ticker}/latest        # Latest decision with risk flags + position sizing
GET  /api/decision/calibration            # Brier score + reliability curve over graded theses, per archetype
```

## Database
- Key tables: `stocks`, `daily_prices` (incl. SPY benchmark rows), `financials` (EDGAR + provenance; 4.1 added total_debt/shares_outstanding population + stock_based_comp/buybacks), `valuations`, `documents`, `analysis_reports` (JSONB + input_fingerprint), `quant_features`, `stock_scores`, `stock_decisions`, `stock_theses` (journal; outcomes incl. excess_return vs SPY), `consensus_snapshots` (append-only revisions history), `earnings_transcripts`, `analyst_estimates`, `earnings_events`, `segments` (populated from transcript summaries, 4.1), `ticker_key_metrics` (KPI defs), `ticker_kpi_values` (extracted KPI values), `dev_ticker_bootstrap_status` (dev-only debug)
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

## Data Sources (all free)
| Source | Data | Tables |
|--------|------|--------|
| **SEC EDGAR XBRL** | **Source of truth for financials** — full filed history (companyfacts), provenance-tagged | financials |
| **yfinance** | Prices, valuation multiples, analyst price targets, forward EPS/revenue consensus, news | daily_prices, valuations, analyst_estimates, documents; financials fallback |
| **IR site scraper** | Earnings transcripts / prepared remarks / slides (FMP-miss fallback; auto-discovered for new tickers) | earnings_transcripts (`source`/`source_url`/`has_qa`) |
| **FMP** | Earnings transcripts (tier 1) + EPS surprises only — estimates moved to yfinance | earnings_transcripts, earnings_events |
| **Claude API** | 5 analysis agents + transcript summarizer + KPI extraction + bootstrap (KPI gen, IR repair) | analysis_reports, ticker_kpi_values, ticker_key_metrics |

FMP is gated behind `FMP_API_KEY`; if unset, transcripts fall back to the IR scraper and FMP surprises are skipped. Consensus estimates no longer depend on FMP (yfinance).

The IR scraper needs a `sources.yaml` entry per ticker; for new tickers `bootstrap.py` auto-discovers one (see **Transcript Fallback Chain**). Note: EDGAR was rejected *for transcripts only* (it doesn't host call transcripts) — but it IS the source of truth for **financials**.

## What's Not Yet Built / Next
- **Phase 1 (next): peer-relative normalization + business-model archetypes** — the current normalizer uses fixed absolute bounds (one ruler for MU and Meta); see `ANALYST_ROADMAP.md`.
- Interactive DCF calculator (frontend); stock comparison page; settings page (watchlist, weights)
- Document embeddings (pgvector) not yet active
- Insider trades ingestion deferred (`InsiderTrade` model exists, unused)
