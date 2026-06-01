# AI-Augmented Equity Research System

A personal, auditable equity-research platform. It tracks a watchlist of stocks, ingests
authoritative data (SEC EDGAR financials, prices, analyst consensus, earnings transcripts), runs
AI research agents, and turns everything into a **peer-relative composite score** — a screening
rank, not a recommendation. Every number is traceable to its source.

Each stock is classified into a business-model **archetype** (cyclical-commodity, secular-grower,
platform, mature-compounder, financial, deep-value-turnaround), and that archetype sets both its
peer group and its scoring weights — so a memory cyclical and an ad platform aren't judged on the
same ruler.

- **Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 (async) · PostgreSQL 16 + pgvector · React/TS ·
  Docker Compose · Claude API (Opus/Sonnet).
- **Run:** `docker compose up -d` → UI at http://localhost:3000, API at http://localhost:8000.
- **Docs:** [`CLAUDE.md`](./CLAUDE.md) (architecture) · [`ANALYST_ROADMAP.md`](./ANALYST_ROADMAP.md)
  (direction + progress log).

## Tests

One **end-to-end test** (`backend/tests/test_pipeline_e2e.py`) drives the whole backend workflow in
a single run, with only external boundaries faked — no network, no real LLM. CI
(`.github/workflows/test.yml`) runs it on an ephemeral Postgres (testcontainers) + frontend `tsc` on
every push/PR. Run locally: see the Testing section in [`CLAUDE.md`](./CLAUDE.md).

The test exercises the real code at every stage and asserts the data flows through:

1. **Ingestion** — `ingest_ticker`: the real SEC EDGAR XBRL parser turns a canned `companyfacts`
   payload into 12 quarterly `financials` rows, and the real grounded archetype classifier labels
   the stock from those numbers.
2. **Analysis** — `run_all_agents`: all five research agents run (LLM mocked) and persist reports.
3. **Scoring** — `calculate_score`: hard features (EDGAR financials + valuation) + AI features
   (agent reports) → peer-relative valuation → an **archetype-weighted composite** + signal.
4. **API** — `/api/scoring/screen` returns the freshly-scored name with its rank.

It checks the data actually flows, not just that it runs: the ingested values are **persisted to the
DB** (exact financials/valuation/prices), that DB data **appears in the agent prompts** (e.g.
`Forward P/E: 13.3x`, quarterly revenue), the agent output is **mapped into the right quant
features** (e.g. verdict → `valuation_verdict_score = 0.75`), and — since every input is
deterministic — the composite is pinned to a **golden value**, so any change to the scoring math
trips the test.

Faked at the edges only: SEC HTTP, the Anthropic API, and the yfinance/scraper sub-ingests
(prices, valuation, estimates, news, transcripts). Everything that is *our* logic runs for real.
