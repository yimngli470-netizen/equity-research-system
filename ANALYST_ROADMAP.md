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

| ID | Problem | Severity | Status (2026-05-30) |
|----|---------|----------|---------------------|
| **P1** | **Absolute, not peer-relative, normalization** — one fixed ruler (`forward_pe 10→60`) for cyclicals and platforms alike. P/E 7 is meaningless in absolute terms. (`quant/normalizer.py` fixed `(low,high)` bounds) | Critical | ✅ **Valuation path done** (1.2 + 1.3): multiples scored as weighted percentile vs peers. Residual: growth/profitability still absolute (follow-up); peak-earnings denominator = P2.2 |
| **P2** | **Systematic over-bullish bias on cyclicals** — skepticism quarantined in the 10%-weight risk bucket + the *excluded* validation channel; scored verdicts anchor on momentum + management guidance. (valuation agent said $1100 "significantly undervalued"; validation reliability 0.38 ignored) | Critical | 🟨 **Dented** — consensus now fed as a normal-weight anchor (mean $674 would flag MU); core fix = Phase 2.1/2.4 |
| **P3** | **Data starvation & shallowness** — 6 quarters (one empty), segment + cycle KPIs come back "not disclosed", no analyst consensus fed in. | Critical | ✅ **Largely resolved** (Phase 0) — EDGAR 21–67 quarters, consensus fed, KPI extraction proven (AMD 4/5); residual = blocked-ticker IR coverage |
| **P4** | **No verifiability / provenance** — agents cite numbers not present in their source; no `source`/`as_of` on stored data. (validation flagged 5/8 segment claims UNVERIFIABLE) | Critical | 🟨 **Substrate done** (Phase 0: provenance columns + verbatim-quote KPI extraction); **publish-gate still open** → Phase 2.4 |
| **P5** | **No regime / archetype awareness** — cannot distinguish cyclical-commodity vs platform vs compounder; can't reason "is this a re-rate or a peak?" | High | 🟨 **Scoring layer done** (1.1 archetypes + 1.4 archetype-conditioned weights + 1.3 peer-relative). The "re-rate vs peak?" *reasoning* + cycle-position signal still open → P2.2 + ML M3 |
| **P6** | **Single-point verdicts; no dialectic, no calibrated uncertainty, no falsifiable theses** (valuation agent emits one bullish verdict + self-rated 0.85) | High | ⬜ **Open** → Phase 2.1/2.5 |
| **P7** | **No track record / calibration loop** — no way to know whether to trust any output (nothing journaled or graded) | High | ⬜ **Open** → Phase 3 + ML M4 |
| **P8** | **Prompt output-contract bugs** — `margin_of_safety` emitted as percent (53.3, unstable 31.5 on rerun) vs normalizer expecting a fraction; free `number` fields have undefined units. | Medium | ⬜ **Open** → Phase 2.6 |
| **P9** | **Composite-as-oracle framing** — UI + decision flow treat the weighted average as the recommendation (dashboard signal badge) | Medium | ⬜ **Open** → Phase 1.5 |

---

## 3. Target Architecture (layers)

```
┌─ ACCOUNTABILITY ── thesis journal · outcome grading · calibration curve · position sizing
│                    [LLM writes theses; ML grades/calibrates]
│
├─ REASONING ─────── bull agent ⇄ bear agent → judge · regime/archetype-aware valuation   [LLM]
│                    · evidence-gating (validation = gate, not sidecar) · calibrated confidence
│
├─ FEATURES/SCORE ── peer-relative normalization · archetype-conditioned weights
│   [measurement]    · composite = screen RANK (not verdict)
│                    ⟵ fed by MEASUREMENT layer (separate svc, §4a): peer weights (embeddings +
│                       return-corr) · cycle-state (HMM) · normalized earnings · learned weights
│
└─ DATA SUBSTRATE ── EDGAR XBRL (financials spine, 10yr) · yfinance (prices, multiples, consensus)
                     · IR slides (segments + cycle KPIs) · transcript (qualitative)
                     · PROVENANCE on every datum (source / source_url / as_of)
```

**Layer ownership:** REASONING = LLM. MEASUREMENT/FEATURES & the ML parts of ACCOUNTABILITY =
stats/ML, deployed as **independent services** (peer weights, normalization, cycle-state,
embeddings, the GBM ranker) so the main app runs and ships without them and degrades gracefully
when they're down. Full split + build order in **§4a Measurement & ML Track**.

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

> **Status (2026-05-30):** Phase 0 items **0.1–0.5 DONE** + **auto-bootstrap shipped**; **0.6
> open**. Design update folded in: LLM-vs-ML split + ML build order + microservice architecture
> (see **§4a**). Per-item detail is in `CLAUDE.md`; outstanding work is consolidated in **Phase 0
> follow-ups** below.

### Phase 0 — Data Foundation (resolves P3, P4; prerequisite for everything)

| # | Action | Effort | Status | Done when |
|---|--------|--------|--------|-----------|
| 0.1 | **EDGAR `companyfacts` ingester** — `ingestion/edgar.py`; ticker→CIK; source-of-truth for `financials` (yfinance = fallback) | M | ✅ DONE | 13 tickers re-ingested, 21–67 quarters each, reconciled to the cent |
| 0.2 | **Concept→tag mapping** — canonical concept → ordered us-gaap tags (ASC606 split stitched) | M | ✅ DONE | continuous revenue/NI/EPS/FCF series across the tag transition |
| 0.3 | **Provenance columns** — `source`/`source_url`/`as_of` on `financials`, `valuations`, KPI/estimate tables | S | ✅ DONE | every stored datum carries source + as-of |
| 0.4 | **yfinance consensus pull** — `ingestion/estimates_yf.py`; forward EPS/rev consensus (NORMAL weight) + price targets (LOW weight) → agents | S–M | ✅ DONE | MU shows street mean $674/median $550 + EPS/rev consensus by period |
| 0.5 | **IR structured KPI extraction** — `ingestion/kpi_extractor.py`; LLM pass pulls each KPI with verbatim quote + source ("not disclosed" when absent) | L | ✅ DONE (segment-rows deferred) | proven on AMD 4/5 KPIs; MU gap is IP-block, not code |
| — | **Auto-bootstrap new stocks** — `ingestion/bootstrap.py`; LLM KPI defs + IR-source discovery; user warnings + dev `dev_ticker_bootstrap_status` | M | ✅ DONE | add ticker + Run Full Pipeline auto-fills with zero manual setup |
| 0.6 | **Data integrity gate** — extend `data_freshness`; flag agent runs on stale/unverifiable inputs | S | ⬜ OPEN | gate adds an "unverifiable source" check on top of existing freshness warnings |

**Phase 0 follow-ups** (logged, non-blocking):
- **EDGAR mapping gaps:** map `total_debt` (`LongTermDebt*`) + `shares_outstanding` (dei `EntityCommonStockSharesOutstanding`) — currently NULL on EDGAR rows.
- **AMZN FCF wrong** — capex split across finance-lease tags the map misses.
- **Derived-Q4 quality:** operating income drifts ~1–2% (opex classification) → flag lower-confidence; **Q4 EPS left NULL** (subtraction breaks across stock splits, e.g. NVDA) → recompute from NI/diluted shares.
- **`computed_metrics` `limit=8`** — raise now that deep history exists.
- **Consensus/price-target framing** — apply the same forward-consensus-vs-price-target split to the earnings agent's `forward_outlook` (today only valuation agent has it).
- **IR source coverage** — persist segments as rows (string→float parse); upgrade reachable press-release tickers (AMZN, MRVL, UBER, AAPL) to richer artifacts; **blocked tickers (MU, TSLA, AVGO)** need a residential-IP/headless run, then retarget MU artifact → slides/prepared_remarks.

### Phase 1 — Normalization & Archetype (resolves P1, P5)

> **Status (2026-05-31): 1.1 DONE.** New `app/measurement/` package (the measurement-layer seam)
> with `profile.py::compute_quant_profile` — TTM cyclicality/margin/capex stats from the EDGAR
> spine; `app/ingestion/archetype.py::classify_archetype` feeds those numbers + name/sector to one
> cached Sonnet pass and writes `stocks.archetype` (+ `archetype_features`, `archetype_rationale`,
> `archetype_as_of`; migration `b2e7c1a4f309`). Wired into the pipeline after EDGAR financials;
> idempotent (LLM fires once per ticker unless `force`). **All active names classified, grounded:**
> MU = cyclical-commodity (52% rev drawdown, 40% growth vol, 32% GM), META/GOOGL = platform (81% GM),
> AAPL/INTU = mature-compounder, NVDA/AMD/MRVL/TSLA/UBER = secular-grower. The MU-vs-platform
> separation that P1 needs is now in the data.

> **Status (2026-05-31): 1.2 DONE (2 of 3 signals; embeddings = M1, pending).** `app/measurement/`
> `peers.py::recompute_peer_weights` + `peer_weights` table (migration `c4f9a2d6b815`). Closeness =
> measured blend of (a) standardized quant-profile distance + (b) trailing return correlation;
> (c) 10-K embedding cosine is a wired-but-null hook (ML M1). Deterministic/reproducible; components
> stored for audit. Cross-sectional, recomputed once at the end of `run_full_ingestion`. **Findings:**
> GOOG↔GOOGL=0.999 (sanity ✓); MU's nearest = AMD/NVDA/AVGO (semis ✓) but weak (~0.33) & return-driven
> — MU is a fundamental outlier with no true peer in-watchlist (confirms it's the lone cyclical). **Two
> gaps M1 fixes:** fundamental sim captures financial *shape*, not *what the business does* (INTU pairs
> with AAPL, not software); 1yr returns compress tech corr into 0.4–0.55. **Follow-ups:** wire M1
> embeddings (needs provider — open decision #5); expand universe beyond the 13-name watchlist (ASML/
> WDC/STX etc.) so cross-sector peers exist.

> **Status (2026-05-31): 1.3 DONE (valuation path) — P1 fix shipped.** `app/measurement/`
> `peer_normalize.py::peer_relative_valuation`, wired into `scoring/calculator.py`: each valuation
> multiple is now scored as the subject's **weighted percentile within its top-K peer set** (1.2),
> not a position on a fixed ruler. Lower-is-better inverted; ≤0 multiples → 0.0; per-metric absolute
> fallback when < 4 peers carry it (graceful degradation). **Verified:** AAPL valuation 0.53→0.36 —
> fwd P/E 28.6 reads "moderate" absolutely (0.63) but "expensive vs mega-cap peers" (0.23); the
> absolute ruler was too generous. MU 0.67→0.74 (slightly UP): vs its actual high-multiple semis,
> MU's EV/EBITDA/PS aren't expensive — **1.3 makes the comparison fair; it does NOT fix MU's
> peak-earnings denominator (Phase 2.2) or quarantined skepticism (2.4).** **Follow-up:** extend
> peer-relative to growth & profitability categories (same "one ruler" issue, lower-stakes).

> **Status (2026-05-31): 1.4 DONE — archetype-conditioned weights (resolves P5 at the scoring
> layer).** `scoring/weights.py`: 6 `ARCHETYPE_WEIGHTS` profiles over the existing 7 categories +
> `weights_for_archetype()`; `calculator.py` selects by `stocks.archetype` when the caller doesn't
> override (API now passes None by default). Profiles are reasoned priors (→ learned via §4a M6
> later). Cyclical profile deliberately does NOT upweight `event` (a beat at the peak is a warning,
> not a positive); leans on risk + profitability (margin direction = best cycle proxy we have pre-2.2).
> **Deltas (default→arch):** INTU +0.059, NVDA +0.038→STRONG_BUY, UBER −0.037, MU −0.031.
> **CRITICAL HONEST FINDING:** MU stays **0.852 STRONG_BUY** — its categories are growth=1.0,
> momentum=1.0, event=0.99, prof=0.86, val=0.78, risk=0.69. *Every signal reads bullish at the cycle
> peak*, so no reweighting produces caution. **Phase 1 cannot fix MU by construction** — that needs
> normalized/mid-cycle earnings (2.2), a cycle-position signal that makes peak-momentum a NEGATIVE
> (ML M3), and un-quarantined skepticism (2.1/2.4). Phase 1 did its structural job (P1+P5); the MU
> verdict is now a clean, well-understood Phase 2 target. **Next: 1.5 (screen-rank reframe), then
> Phase 2.**

> **Design decision (2026-05-30) — who does what, LLM vs measurement.** Each Phase-1 item is
> tagged by the *right tool* for the job (full rationale in **§4a Measurement & ML Track**). The
> rule: **knowledge/language/explanation → LLM; any number that must be stable & reproducible →
> measurement (stats/ML).** So 1.1 is *grounded* LLM (fed computed cyclicality features, not
> guessing from a ticker); 1.2 peer **weights** are measured, not LLM-opined; 1.4 weight profiles
> are hand-authored priors now, a *learned* model later (gated on the backtest panel — §4a).

| # | Action | Effort | Output | Done when |
|---|--------|--------|--------|-----------|
| 1.1 | **Archetype classification** *(grounded LLM)* — add `archetype` to `stocks` (secular-grower / cyclical-commodity / platform / mature-compounder / financial / deep-value-turnaround). First compute a quant profile from EDGAR (revenue/margin volatility, capex & R&D intensity, payout, gross-margin level/stability), **then** feed those numbers + company name to one cached LLM pass. Store label **and** the quant features + rationale for audit. | M | `stocks.archetype` (+ `archetype_features` json, rationale) populated | each watchlist name classified + rationale stored; re-runnable; label grounded on stored numbers |
| 1.2 | **Peer-set construction & closeness weights** *(measurement, not LLM)* — candidate peers from SIC/GICS + an LLM suggestion pass; **closeness weight per peer is measured**, not opined: blend of (a) fundamental-feature distance, (b) trailing return correlation, (c) 10-K Item-1 business-description **embedding** cosine. LLM proposes the set; math assigns the 0–1 weights. | M | `peer_sets` table (ticker → [peer, weight, components]) | NVDA→AMD weight > NVDA→ASML, reproducibly; weights stable across reruns |
| 1.3 | **Peer-relative normalization** — replace fixed `(low,high)` bounds in `quant/normalizer.py` with cross-sectional percentile/z-score within the **weighted peer set** (1.2) / archetype; leverage EDGAR `frame` (CY-aligned) for cross-company comparability | L | rewritten `quant/normalizer.py` | MU valuation scored relative to semis peers, not absolute; Meta scored vs platform peers |
| 1.4 | **Archetype-conditioned weight profiles** *(hand priors now → learned later)* — extend `scoring/weights.py` with per-archetype profiles (cyclicals ↑ cycle-position & normalized earnings, ↓ spot multiples; platforms ↑ moat/growth durability). Authored as documented expert priors; replaceable by learned weights once the panel exists (§4a). | M | weight-profile table + selector | composite recomputes per-archetype; documented profiles |
| 1.5 | **Composite reframed as screen-rank** — relabel in API/UI; surface percentile-within-peers, not an absolute verdict | S | UI/API copy + ranking field | dashboard shows "rank vs peers"; signal no longer presented as the recommendation |

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

## 4a. Measurement & ML Track (LLM vs ML; the long-term learned layer)

The system has two kinds of judgment, and today the LLM does several jobs it's actually the
*weaker* tool for (it emits unstable numbers — e.g. MU `margin_of_safety` 53.3 → 31.5 on rerun).
The organizing principle:

> **LLM owns the reasoning/language layer. Measurement (stats/ML) owns the
> numeric/prediction layer. Knowledge, language, and explanation → LLM. Any number that must be
> stable and reproducible → measurement.**

### Tool selection map

| Task | Tool | Why |
|---|---|---|
| World knowledge ("MU is memory-cyclical") | **LLM** | not in our data |
| Unstructured → structured (transcripts→KPIs, news→events) | **LLM** | semantic extraction |
| Rationales · bull/bear dialectic · evidence gating | **LLM** | qualitative reasoning + explanation |
| Small-N labeling (archetype, 6 buckets, dozens of names) | **LLM** (grounded) | no training set exists |
| **Peer similarity / closeness weights** (1.2) | **ML — embeddings + return-corr + feature distance** | reproducible *measurement*, not opinion |
| **Archetype *discovery*** (are 6 buckets right?) | **ML — unsupervised clustering** | finds natural groupings vs imposed ones |
| **Cycle-position / "re-rate vs peak?"** | **ML — HMM / change-point / state-space** | quantitative regime inference; LLMs unreliable here |
| **Normalized / mid-cycle earnings** | **Stats — through-cycle regression** | arithmetic, not reasoning |
| **Calibrated probabilities** ("80% ⇒ right 80%") | **ML — GBM / logistic** | LLM "confidence" is not calibrated |
| **Forward-return / surprise prediction** | **ML — supervised (GBM)** | classic quant use; hardest, needs panel |
| Stable, cheap, deterministic scoring at scale | **ML** | no per-call cost, no drift |

### The gating dependency: a point-in-time panel

Every **supervised** ML win (learned weights for 1.4, return/surprise prediction, calibrated
conviction) needs a labeled **point-in-time panel**: features *as they were known then* → forward
outcome. We don't have one yet — building it is the real long-pole, not the modeling. It is
assembled by **Phase 0 (EDGAR point-in-time fundamentals + price history)** + **Phase 3.1 thesis
journal (predictions → graded outcomes)**. Until it exists, supervised ML on ~15 names just
overfits. **#1 failure mode = lookahead bias.**

### What to build, in order (no false starts)

| # | Item | Needs labels? | Effort | Notes |
|---|---|---|---|---|
| M1 | **Business-description embeddings** for peer weights (powers 1.2) | no | S | inference-only (API or local model); the cheapest, earliest ML win |
| M2 | **Unsupervised archetype clustering** — validate/refine the 6 buckets on the quant profile | no | M | sanity-checks 1.1; may reveal sub-types (memory vs logic semis) |
| M3 | **Cycle-state model** — HMM/change-point on revenue/margin/inventory → cycle position | no | M | feeds Phase 2.2 "re-rate vs peak"; through-cycle normalized earnings |
| M4 | **Panel assembly** — point-in-time feature/label store from EDGAR + journal | n/a | L | prerequisite for M5+; build incrementally as the journal accrues |
| M5 | **Supervised ranker** — GBM (XGBoost/LightGBM, **not** deep learning) on tabular features → forward peer-relative return / calibrated conviction | **yes (M4)** | L | walk-forward / **purged** time-series CV, time-based OOS, scored on rank-IC + Brier (never accuracy, never random split) |
| M6 | **Learned weight profiles** — replace/blend the hand-authored 1.4 priors with M5-derived weights, per archetype | **yes (M4)** | M | only after M5 generalizes out-of-sample |

**Modeling stance:** start with the unsupervised/measurement wins (M1–M3) that need *no* labels
and pay off now; GBMs over deep learning for tabular financial data at this scale (interpretable,
calibrated, data-efficient); embeddings are the one DL tool worth using early (inference only).
DL sequence models only if GBMs plateau with abundant data — likely never for a personal watchlist.
Be honest: supervised return prediction is what quant funds spend fortunes on and still find hard;
the near-term ML value is the *measurement* layer, not alpha prediction.

### Service architecture — ML as independent microservices

**Decision (2026-05-30):** the ML/measurement work is built as **separate services** so the main
app (FastAPI + ingestion + agents + UI) runs and ships independently of any model. Boundaries:

```
main-app (FastAPI)  ──HTTP/gRPC──▶  measurement-svc   (peer weights, normalization stats,
   │  owns: ingestion, agents,                          cycle-state, embeddings — M1–M3)
   │  scoring orchestration, UI,                ──▶  ml-svc           (panel, GBM ranker,
   │  Postgres                                          calibration — M4–M6; heavy deps:
   └─ degrades gracefully if a                          numpy/scikit/xgboost, model registry)
      measurement/ml call is down ──────────────▶  (shared) Postgres / feature store
```

Principles:
- **Contract, not coupling** — services expose a thin HTTP/JSON (or gRPC) API
  (`/peer-weights/{ticker}`, `/normalize`, `/cycle-state/{ticker}`, `/rank`). The main app holds
  no `sklearn`/`xgboost`/embedding deps; those stay in the ML images.
- **Graceful degradation** — if `measurement-svc`/`ml-svc` is unavailable or returns low
  confidence, the main app **falls back** to today's absolute normalization + hand-priors and
  surfaces a coverage warning (same pattern as the IR-bootstrap amber banner). The app must never
  hard-depend on a model being up.
- **Independent lifecycle** — models retrain/redeploy on their own cadence (batch jobs writing
  results + version into Postgres); the app reads the latest published version. Versioned outputs
  so a bad model can be rolled back without touching the app.
- **Async/cacheable** — peer weights, archetype, cycle-state are slow-moving: compute in batch,
  cache in Postgres, read cheaply at request time. Only embeddings/ranking might be on-demand.
- **Start in-process, split at the seam** — implement M1–M3 first as a `measurement/` package
  behind an interface; promote to a deployed service when the dependency weight or retrain cadence
  justifies it. The *interface* is the commitment; the process boundary is an operational detail.

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

**Resolved decisions:**
- **LLM vs ML split (2026-05-30):** measurement numbers (peer weights, normalization, cycle-state,
  calibration, learned weights) are stats/ML; knowledge/language/explanation is LLM. See §4a.
- **Service architecture (2026-05-30):** ML/measurement built as **independent microservices**;
  the main app degrades gracefully without them. Start in-process behind an interface, split at the
  seam when dep-weight/retrain cadence justifies it. See §4a.
- **Archetype labeling (2026-05-30):** *grounded* LLM (computed cyclicality features + name → label
  + rationale), not a trained classifier (no labels at N≈15); unsupervised clustering (M2)
  *validates* the buckets later.

**Open decisions (need user input):**
1. **EDGAR scope:** source-of-truth for `financials` (replace yfinance there) vs verification/backfill alongside. *(Leaning: replace for fundamentals; yfinance keeps prices+multiples+consensus.)*
2. **Build order:** harden data foundation fully first (Phase 0) vs start the thesis-journal loop (3.1) in parallel now so calibration data accumulates earlier. *(Leaning: Phase 0 as main thread; stand up 3.1 journaling early in parallel.)*
3. **Dialectic cost:** bull+bear+judge multiplies token cost per run — acceptable for a ~15-name watchlist on a manual cadence?
4. **Archetype granularity:** are 6 archetypes enough, or do we need sub-types (e.g., memory vs logic semis)? *(M2 unsupervised clustering will inform this empirically.)*
5. **ML service stack:** language/runtime for `measurement-svc`/`ml-svc` (Python/FastAPI to share models with the app stack, vs a separate runtime) and where the feature store lives (Postgres tables vs a dedicated store). *(Leaning: Python/FastAPI services, Postgres-backed feature store, to start.)*

---

## 8. Recommended Sequencing (critical path)

1. **Phase 0.1–0.4** (EDGAR spine + provenance + yfinance consensus) — unblocks verifiability,
   depth, and the consensus anchor that would have caught the MU over-bullishness. **[DONE]**
2. **3.1 thesis journal** in parallel — start accruing calibration data immediately (this is also
   half of the §4a panel that supervised ML later depends on — start early so it accrues).
3. **Phase 0.5** (IR KPI extraction) — fills the cyclical-metric blind spots. **[DONE]**
4. **Phase 1** (peer-relative + archetype) — fixes the "one ruler" problem. Build **M1 (embeddings
   for peer weights)** and **M3 (cycle-state)** from §4a alongside it — they're the measurement
   primitives 1.2/1.3 consume; **M2 (clustering)** validates 1.1's buckets.
5. **Phase 2** (dialectic + regime + evidence-gate) — the actual analyst reasoning.
6. **Phase 3.2–3.4** (grading, calibration, sizing) — closes the trust loop.
7. **§4a M4–M6** (panel → GBM ranker → learned weights) — the long-term learned layer; only once
   the journal panel is deep enough to validate out-of-sample. Replaces hand-priors in 1.4.

> First concrete deliverables to implement (after this plan is approved): **0.1+0.2 EDGAR
> ingester + tag map** (proven on MU vs DB) and **0.4 yfinance consensus pull**. Both bounded,
> both free, both directly attack the bias diagnosed this session.
