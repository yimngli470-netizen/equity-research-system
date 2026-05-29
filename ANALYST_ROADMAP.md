# Roadmap: From Quant Screener → Reliable AI Research Analyst

> Status: planning. Authored 2026-05-29. This is the long-term plan; near-term we finish the
> screener and harden data. See `CLAUDE.md` for current system state, `PROJECT_PLAN.md` for the
> original architecture.

---

## 1. Vision & Definition of Success

**Short-term (≈done):** a personal screener/dashboard that ranks a watchlist consistently and
flags what to investigate.

**Long-term goal:** an **auditable AI research analyst** the user can rely on for real investment
decisions.

### What "reliable" means here (the trust model)
We are **not** building an oracle that emits a verdict to obey. We are building an analyst whose
**process and track record** you trust, the way you'd trust a good human analyst:

1. **Auditable** — every quantitative claim links to a primary source (SEC filing, IR slide,
   transcript line, price row). No unsourced numbers.
2. **Two-sided** — it argues bull *and* bear, then takes a calibrated view; skepticism is a
   first-class participant, not a footnote.
3. **Self-aware of uncertainty** — states confidence, and what would prove the thesis wrong
   (falsifiable kill criteria).
4. **Track-recorded** — every thesis is journaled with predictions and graded against outcomes,
   producing a calibration curve. *This is what earns reliance.*
5. **Human-in-the-loop** — the analyst produces decision-grade research; the human sizes and
   pulls the trigger.

### Non-goals
- Auto-trading / order execution.
- Bespoke code per company (we condition on ~6 business-model *archetypes*, not per-ticker).
- Paid data vendors (hard constraint: **free sources only** for now).
- Treating the composite score as the answer (it is a *screen rank*, not a verdict).

---

## 2. Problems That MUST Be Resolved

These are the diagnosed defects from analysis of MU (a cyclical at cycle-peak, scored
0.88 STRONG_BUY while street consensus implied downside). Ordered by severity.

| ID | Problem | Evidence | Severity |
|----|---------|----------|----------|
| **P1** | **Absolute, not peer-relative, normalization** — one fixed ruler (`forward_pe 10→60`) for cyclicals and platforms alike. P/E 7 is meaningless in absolute terms. | `quant/normalizer.py` fixed `(low,high)` bounds | Critical |
| **P2** | **Systematic over-bullish bias on cyclicals** — skepticism quarantined in the 10%-weight risk bucket + the *excluded* validation channel; scored verdicts anchor on momentum + management guidance. | risk=0.69 buried; validation reliability 0.38 ignored; valuation agent said $1100 "significantly undervalued" | Critical |
| **P3** | **Data starvation & shallowness** — 6 quarters (one empty), segment + cycle KPIs (DRAM ASP, HBM rev, inventory days) come back "not disclosed", no analyst consensus fed in. | earnings agent `key_metrics` mostly "not disclosed"; `consensus_comparison: null` | Critical |
| **P4** | **No verifiability / provenance** — agents cite numbers (segment growth) not present in their source; no `source`/`as_of` on stored data. | validation flagged 5/8 segment claims UNVERIFIABLE | Critical |
| **P5** | **No regime / archetype awareness** — cannot distinguish cyclical-commodity vs platform vs compounder; can't reason "is this a re-rate or a peak?" | the MU-as-Nvidia question the agent can't address | High |
| **P6** | **Single-point verdicts; no dialectic, no calibrated uncertainty, no falsifiable theses** | valuation agent emits one bullish verdict + self-rated score 0.85 | High |
| **P7** | **No track record / calibration loop** — no way to know whether to trust any output | nothing journaled or graded | High |
| **P8** | **Prompt output-contract bugs** — `margin_of_safety` emitted as percent (53.3, unstable 31.5 on rerun) vs normalizer expecting a fraction; free `number` fields have undefined units. | clamps to 1.0; non-deterministic | Medium |
| **P9** | **Composite-as-oracle framing** — UI + decision flow treat the weighted average as the recommendation | dashboard signal badge | Medium |

---

## 3. Target Architecture (layers)

```
┌─ ACCOUNTABILITY ── thesis journal · outcome grading · calibration curve · position sizing
│
├─ REASONING ─────── bull agent ⇄ bear agent → judge · regime/archetype-aware valuation
│                    · evidence-gating (validation = gate, not sidecar) · calibrated confidence
│
├─ FEATURES/SCORE ── peer-relative normalization · archetype-conditioned weights
│                    · composite = screen RANK (not verdict)
│
└─ DATA SUBSTRATE ── EDGAR XBRL (financials spine, 10yr) · yfinance (prices, multiples, consensus)
                     · IR slides (segments + cycle KPIs) · transcript (qualitative)
                     · PROVENANCE on every datum (source / source_url / as_of)
```

Source-of-truth split (all free):

| Domain | Source of truth | Notes |
|---|---|---|
| Consolidated financials + full history | **SEC EDGAR `companyfacts`** | authoritative, ~10yr, real fiscal labels; needs tag-stitching |
| Prices + valuation multiples | yfinance | market-derived; EDGAR can't provide |
| **Analyst consensus** | **yfinance estimate endpoints** (NOT FMP) | `earnings_estimate`, `revenue_estimate`, `analyst_price_targets`, `eps_trend` |
| Segments + cycle KPIs | IR slides (existing scraper + LLM extraction) | dimensional data absent from `companyfacts` |
| Qualitative / tone / Q&A | transcript (FMP→IR fallback) | spoken-only content |

---

## 4. Workstreams & Action Items

Effort: **S** ≤1 day · **M** ~few days · **L** ~1–2 weeks. "Done when" = acceptance criteria.

> **Progress (2026-05-29):** Items **0.1, 0.2, 0.3, 0.4 DONE.** 0.4: consensus now comes from
> **yfinance** (`ingestion/estimates_yf.py`), not FMP; migration `c3f5a1e8b740` added
> `source`/`as_of`/`revisions_30d` to `analyst_estimates`. Per user guidance it is a
> **low-weight divergence check**: the valuation agent is told never to defer to it, and when
> STALE (our copy >30d old OR zero analyst revisions in 30d) it is dropped → `consensus_comparison`
> null → excluded from scoring (zero weight). Follow-up: apply the same low-weight framing to the
> earnings agent's forward_outlook; optionally ingest the consensus price target as a divergence anchor.
>
> Items **0.1, 0.2, 0.3 DONE.** `ingestion/edgar.py` is wired into
> `pipeline.py` as the source of truth for `financials` (yfinance = fallback only); migration
> `b1d4e7a90c22` added `source`/`source_url`/`as_of` provenance. All 13 real watchlist tickers
> re-ingested from EDGAR (21–67 quarters each, 100% `source='edgar'`); the shallow yfinance rows
> were replaced. Reconciled to the cent on directly-filed quarters.
> **Known follow-ups:** (a) `total_debt` + `shares_outstanding` not yet mapped → NULL on EDGAR
> rows (add `LongTermDebt*` + dei `EntityCommonStockSharesOutstanding`); (b) AMZN FCF wrong —
> capex split across finance-lease tags my map misses; (c) derived-Q4 operating income drifts
> ~1–2% (annual-minus-3Q opex classification) — flag as lower confidence; (d) derived-Q4 EPS now
> left NULL (subtraction breaks across stock splits, e.g. NVDA) — recompute from NI/diluted shares
> later; (e) EDGAR's filed GAAP operating income differs ~1–2% from yfinance for acquirers (AVGO)
> — expected, EDGAR is authoritative; (f) `computed_metrics` still fetches only `limit=8` quarters
> — can raise now that deep history exists.

### Phase 0 — Data Foundation (resolves P3, P4; prerequisite for everything)

| # | Action | Effort | Output / Artifact | Done when |
|---|--------|--------|-------------------|-----------|
| 0.1 | **EDGAR `companyfacts` ingester** — new `ingestion/edgar.py`; ticker→CIK via `company_tickers.json`; polite UA + rate limit | M | financials sourced from filings | MU's EDGAR series reconciles to existing DB rows; ≥10yr history loaded |
| 0.2 | **Concept→tag mapping layer** — canonical concept → ordered us-gaap tags (handles ASC606 split: `SalesRevenueNet`→`RevenueFromContractWithCustomerExcludingAssessedTax`) | M | `edgar_tagmap.py` (or yaml) | continuous revenue/NI/EPS/FCF series across the tag transition for all watchlist names |
| 0.3 | **Provenance columns** — add `source`, `source_url`, `as_of` to `financials`, `valuations`, new KPI/estimate tables (Alembic migration) | S | migration + model changes | every stored datum carries source + as-of |
| 0.4 | **yfinance consensus pull** — ingest `earnings_estimate`, `revenue_estimate`, `analyst_price_targets`, `eps_trend`, `eps_revisions` → estimates table; feed earnings + valuation agents | S–M | populated estimates; `consensus_comparison` non-null | MU shows street mean $674/median $550 targets + EPS/rev consensus by period in agent context |
| 0.5 | **IR structured KPI/segment extraction** — extend `ingestion/ir/` + `transcript_summarizer` with an LLM pass that pulls segment revenue + cycle KPIs (ASP dir, HBM rev, bit growth, inventory days) into structured rows | L | `segment_metrics` + `ticker_kpis` tables populated | MU `key_metrics` stop returning "not disclosed"; values cite IR source_url |
| 0.6 | **Data integrity gate** — extend `data_freshness`; block/flag agent runs on stale or unverifiable inputs | S | freshness/integrity report in pipeline | gate emits warnings already-present; adds "unverifiable source" check |

### Phase 1 — Normalization & Archetype (resolves P1, P5)

| # | Action | Effort | Output | Done when |
|---|--------|--------|--------|-----------|
| 1.1 | **Archetype classification** — add `archetype` to `stocks` (secular-grower / cyclical-commodity / platform / mature-compounder / financial / deep-value-turnaround); one cached LLM+sector pass | M | `stocks.archetype` populated | each watchlist name classified + rationale stored; re-runnable |
| 1.2 | **Peer-relative normalization** — replace fixed `(low,high)` bounds with cross-sectional percentile/z-score within sector (or archetype); leverage EDGAR `frame` (CY-aligned) for cross-company comparability | L | rewritten `quant/normalizer.py` | MU valuation scored relative to semis peers, not absolute; Meta scored vs platform peers |
| 1.3 | **Archetype-conditioned weight profiles** — extend `scoring/weights.py` with per-archetype profiles (cyclicals ↑ cycle-position & normalized earnings, ↓ spot multiples; platforms ↑ moat/growth durability) | M | weight-profile table + selector | composite recomputes per-archetype; documented profiles |
| 1.4 | **Composite reframed as screen-rank** — relabel in API/UI; surface percentile-within-peers, not an absolute verdict | S | UI/API copy + ranking field | dashboard shows "rank vs peers"; signal no longer presented as the recommendation |

### Phase 2 — Reasoning Layer (resolves P2, P5, P6, P8)

| # | Action | Effort | Output | Done when |
|---|--------|--------|--------|-----------|
| 2.1 | **Bull / Bear / Judge dialectic** — new `agents/bull_agent.py`, `bear_agent.py`, `judge_agent.py`; orchestrator runs adversarial pass; bear is first-class (cannot be down-weighted) | L | three agents + orchestrator wiring | every report has explicit bull case, bear case, and a judged synthesis with a leaning |
| 2.2 | **Regime-aware valuation** — rewrite `valuation_agent` system prompt: archetype branch; for cyclicals require normalized/mid-cycle earnings; permit domain knowledge; output bull/base/bear + explicit "re-rate vs peak?" section | M | new valuation prompt + schema | MU report contains a memory-cycle regime call + normalized-earnings valuation |
| 2.3 | **Valuation triangulation** — agent must compare its fair value to (a) management guidance and (b) street consensus, and justify any divergence beyond a threshold | M | triangulation block in report | a >X% gap above the $674 consensus must carry an explicit defensible argument |
| 2.4 | **Evidence-gating** — `validation_agent` becomes a publish *gate*: require source citation per quantitative claim; CONTRADICTED/UNVERIFIABLE above threshold blocks or down-confidences the report. Wire `agent_reliability` into conviction in `decision/engine.py` (today it's excluded). | M | validation-as-gate + conviction wiring | a 0.38-reliability report cannot ship as high-confidence STRONG_BUY |
| 2.5 | **Calibrated confidence + kill criteria** — every thesis emits a confidence and ≥2 falsifiable predictions with dates | S–M | schema fields | MU thesis lists e.g. "wrong if HBM ASPs roll over 2 quarters / if all 3 add wafer capacity" |
| 2.6 | **Prompt output-contract fixes** — define units for `margin_of_safety` (fraction) and audit every free `number` field; add post-parse validation | S | fixed schemas + validators | `margin_of_safety` stable + correctly normalized; no undefined-unit fields |

### Phase 3 — Accountability & Decisions (resolves P7, P9)

| # | Action | Effort | Output | Done when |
|---|--------|--------|--------|-----------|
| 3.1 | **Thesis journal** — `stock_theses` table: thesis, bull/bear, predictions[], confidence, price_at, archetype, links to score/decision | M | persisted theses | each analyst run writes an immutable thesis snapshot |
| 3.2 | **Outcome grading** — scheduler job revisits theses at horizon, scores each falsifiable prediction (hit/miss/partial) and price vs target | M | graded outcomes | predictions auto-scored after their date |
| 3.3 | **Calibration metrics** — Brier-style score + reliability curve, segmented by archetype | M | calibration dashboard | "when it says 80%, it's right ~X%" answerable, per archetype |
| 3.4 | **Position-sizing / portfolio context** — recommendation includes size guidance conditioned on conviction + concentration + correlation with existing book | L | sizing block | recommendation is "how much," not just direction |

### Cross-cutting
- **Observability & cost** — log every agent's prompt/raw output/tokens (the dry-run harness we built); budget guardrails.
- **Schema/versioning** — version report schemas; migrations for all new tables.
- **Backfill** — re-run EDGAR + IR extraction historically so the calibration loop has data to learn from sooner.

---

## 5. Expected Output: the Research Report Spec

The analyst's work product per ticker. Every numeric field carries provenance.

```
ResearchReport {
  header:        { ticker, as_of, price (+ as_of), archetype, peer_set[] }
  thesis:        { one_paragraph, direction, conviction (calibrated 0-1), time_horizon }
  regime_call:   { cycle_position | business_model_verdict,
                   "re-rate vs peak" reasoning }              # e.g. MU: structurally tighter
                                                              # cyclical, NOT a platform
  bull_case:     [ { claim, evidence{ source, source_url, value }, weight } ]
  bear_case:     [ { claim, evidence{ source, source_url, value }, weight } ]
  valuation:     { agent_fair_value{ bear, base, bull },
                   vs_management_guidance, vs_street_consensus{ mean, median, n_analysts },
                   divergence_reasoning }                     # must justify gap vs $674 street
  key_metrics:   [ { name, value, source_url, vs_warning_line } ]   # ASP, HBM rev, DSI, capex
  risks:         [ { risk, severity, evidence } ]
  kill_criteria: [ { falsifiable_prediction, by_date } ]      # ≥2; what would change the view
  recommendation:{ action, conviction, suggested_size_context }
  reliability:   { validation_verdict, evidence_coverage_pct, agent_reliability }
  provenance:    { every number traceable }
  track_record:  { prior_theses_on_ticker[], how_they_scored }
}
```

---

## 6. How We Know It's Reliable (acceptance gates)

Non-negotiable bars before calling it "decision-grade":

1. **Verifiability:** 100% of quantitative claims cite a primary source; validation gate blocks
   publish if UNVERIFIABLE/CONTRADICTED exceeds threshold. (Directly fixes P4.)
2. **Two-sidedness:** every report contains a non-trivial bear case; the judge's leaning is
   explicit. (Fixes P2.)
3. **Triangulation:** valuation reconciles agent FV vs guidance vs consensus; >X% divergence
   requires written justification. (Fixes the $1100-vs-$674 failure.)
4. **Falsifiability:** ≥2 dated kill criteria per thesis. (Fixes P6.)
5. **Calibration target:** over a rolling window, high-confidence (>0.75) calls hit at a rate
   within tolerance of stated confidence, tracked per archetype. (Fixes P7.)
6. **Peer-relativity:** no absolute-threshold scoring remains in the valuation path. (Fixes P1.)

---

## 7. Constraints, Risks, Open Decisions

**Constraints:** free data only; small personal watchlist (~15 large-cap tech); single user;
LLM token budget is real (each analyst run = several Opus/Sonnet calls).

**Risks:**
- yfinance/IR scraping is unofficial → can break on site changes (already-accepted risk; add
  defensive parsing + freshness gate).
- EDGAR XBRL tag inconsistency across companies → mitigated by the concept→tag map; budget time.
- Consensus for cyclicals lags/chases (MU EPS est. moved $44→$105 in 90d) → treat as one leg of
  the triangle, surface revision velocity, never as truth.
- Calibration needs *time*; start journaling early even on the imperfect system.

**Open decisions (need user input):**
1. **EDGAR scope:** source-of-truth for `financials` (replace yfinance there) vs verification/backfill alongside. *(Leaning: replace for fundamentals; yfinance keeps prices+multiples+consensus.)*
2. **Build order:** harden data foundation fully first (Phase 0) vs start the thesis-journal loop (3.1) in parallel now so calibration data accumulates earlier. *(Leaning: Phase 0 as main thread; stand up 3.1 journaling early in parallel.)*
3. **Dialectic cost:** bull+bear+judge multiplies token cost per run — acceptable for a ~15-name watchlist on a manual cadence?
4. **Archetype granularity:** are 6 archetypes enough, or do we need sub-types (e.g., memory vs logic semis)?

---

## 8. Recommended Sequencing (critical path)

1. **Phase 0.1–0.4** (EDGAR spine + provenance + yfinance consensus) — unblocks verifiability,
   depth, and the consensus anchor that would have caught the MU over-bullishness.
2. **3.1 thesis journal** in parallel — start accruing calibration data immediately.
3. **Phase 0.5** (IR KPI extraction) — fills the cyclical-metric blind spots.
4. **Phase 1** (peer-relative + archetype) — fixes the "one ruler" problem.
5. **Phase 2** (dialectic + regime + evidence-gate) — the actual analyst reasoning.
6. **Phase 3.2–3.4** (grading, calibration, sizing) — closes the trust loop.

> First concrete deliverables to implement (after this plan is approved): **0.1+0.2 EDGAR
> ingester + tag map** (proven on MU vs DB) and **0.4 yfinance consensus pull**. Both bounded,
> both free, both directly attack the bias diagnosed this session.
