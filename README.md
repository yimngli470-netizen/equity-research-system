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

`backend/tests/` — 39 tests across three tiers. The **measurement layer** (deterministic scoring
logic) is the focus; no test hits the network or the real LLM (Anthropic calls are mocked). CI
(`.github/workflows/test.yml`) runs the suite (testcontainers Postgres) + frontend `tsc` on every
push/PR. Run locally: see the Testing section in [`CLAUDE.md`](./CLAUDE.md).

What's verified:

**Unit — pure logic**
- Quant-profile math (trailing-twelve-month aggregation, safe division, stats).
- Peer closeness: fundamental similarity is 1.0 for identical profiles and monotonic in distance;
  the blend renormalizes and treats anti-correlation as "not close".
- Peer-relative normalization: cheaper multiple → higher score, ties count half, inversion correct.
- Archetype weights: every profile sums to 1.0; cyclicals don't reward a peak earnings beat.

**Integration — DB-backed (Postgres)**
- Peer recompute over a seeded universe: identical names rank closest, self is excluded.
- Peer-relative valuation scores against peers, and falls back to the absolute ruler when too few
  peers carry a metric.
- The composite picks **archetype-conditioned weights** by the stock's archetype (vs default).
- Archetype classification writes a label grounded on the measured numbers; unknown labels are
  rejected, not stored.

**API — endpoint contracts**
- `/api/scoring/screen` ranks names by composite within the watchlist and within their archetype.
- `/stocks/{ticker}/scores/latest` returns the archetype and the actual weights used.
