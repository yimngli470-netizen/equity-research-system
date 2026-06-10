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
| **P1** | **Absolute, not peer-relative, normalization** — one fixed ruler (`forward_pe 10→60`) for cyclicals and platforms alike. P/E 7 is meaningless in absolute terms. (`quant/normalizer.py` fixed `(low,high)` bounds) | Critical | ✅ **Done** — valuation path peer-relative (1.2+1.3); peak-earnings denominator fixed in the valuation agent (2.2, normalized earnings). Residual: growth/profitability/event still absolute & peak-biased in the SCREEN (follow-up, ML M3) |
| **P2** | **Systematic over-bullish bias on cyclicals** — skepticism quarantined in the 10%-weight risk bucket + the *excluded* validation channel; scored verdicts anchor on momentum + management guidance. (valuation agent said $1100 "significantly undervalued"; validation reliability 0.38 ignored) | Critical | ✅ **Done** (2.1 + 2.4): first-class bear + judge that must engage every bear point, now WIRED into the decision — MU's 0.852 STRONG_BUY screen becomes a **BUY decision at moderate confidence**, capped by the judge's 0.45 conviction. Skepticism moves the recommendation, not just a sidecar |
| **P3** | **Data starvation & shallowness** — 6 quarters (one empty), segment + cycle KPIs come back "not disclosed", no analyst consensus fed in. | Critical | ✅ **Largely resolved** (Phase 0) — EDGAR 21–67 quarters, consensus fed, KPI extraction proven (AMD 4/5); residual = blocked-ticker IR coverage |
| **P4** | **No verifiability / provenance** — agents cite numbers not present in their source; no `source`/`as_of` on stored data. (validation flagged 5/8 segment claims UNVERIFIABLE) | Critical | ✅ **Done** — provenance substrate (Phase 0) + evidence **gate** (2.4): low validation reliability / high contradiction rate caps a buy to HOLD at low confidence. Follow-up: per-claim source-citation in the validation prompt |
| **P5** | **No regime / archetype awareness** — cannot distinguish cyclical-commodity vs platform vs compounder; can't reason "is this a re-rate or a peak?" | High | 🟨 **Scoring layer done** (1.1 archetypes + 1.4 archetype-conditioned weights + 1.3 peer-relative). The "re-rate vs peak?" *reasoning* + cycle-position signal still open → P2.2 + ML M3 |
| **P6** | **Single-point verdicts; no dialectic, no calibrated uncertainty, no falsifiable theses** (valuation agent emits one bullish verdict + self-rated 0.85) | High | ✅ **Done** (2.1 + 2.5): bull/bear/judge with leaning + calibrated conviction + ≥2 **dated, falsifiable kill-criteria** (watch_metric + by_date + would_confirm) ready for Phase 3 grading |
| **P7** | **No track record / calibration loop** — no way to know whether to trust any output (nothing journaled or graded) | High | ✅ **Done** (Phase 3): every verdict is journaled (3.1), its dated predictions graded on the next pipeline run after they come due (3.2), and the graded history rolls up into a Brier score + per-archetype reliability curve + `overconfidence_gap` (3.3) — which then *shrinks position size* (3.4). The trust loop is closed; ML M4 (learned calibration) is the long-term upgrade |
| **P8** | **Prompt output-contract bugs** — `margin_of_safety` emitted as percent (53.3, unstable 31.5 on rerun) vs normalizer expecting a fraction; free `number` fields have undefined units; **self-rated `conviction` clusters at generic round numbers (judge 0.55 for *every* stock, bull/bear both 0.75) — an unanchored 0–1 self-rating is LLM vibes, not a calibrated probability.** | Medium | 🟨 **margin_of_safety fixed** (2.6) + **conviction rubric-anchored** (2026-06-09): the judge must count `unresolved_bear_points` first, then pick conviction from an explicit band (0.80–0.95 all rebutted … 0.20–0.35 core point conceded); bull/bear anchored to an evidence-strength band. Result: AVGO/META, once *identical* at 0.55, now diverge to 0.45 (4/6 bears stand → neutral → HOLD, 0% size) vs 0.52 (3/6 → bull → half-size BUY). **+ `avg_surprise_pct` fixed** (2026-06-09): the earnings LLM emitted it as a percent number (META 11.45) but the normalizer reads a fraction (±0.10 → pinned to max) and the UI ×100 (→ "+1145%"). Now computed deterministically from `earnings_events` as a fraction (`quant/earnings_surprise.py`, applied in `EarningsAgent.run`) → META +11.7%, NVDA +4.6%. Broader free-number audit across all agents still remains |
| **P9** | **Composite-as-oracle framing** — UI + decision flow treat the weighted average as the recommendation (dashboard signal badge) | Medium | ✅ **Done** (1.5): composite reframed as a peer-rank screen (`/api/scoring/screen` + `ScreenRankBar`), "not a recommendation" copy, real archetype weights shown |

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

> **Status: PHASE 1 COMPLETE (2026-05-31).** All items 1.1–1.5 shipped (see git history / code for
> per-item detail). New `app/measurement/` package is the seam: archetype classification (1.1),
> measured peer-closeness weights (1.2), peer-relative valuation (1.3), archetype-conditioned weight
> profiles (1.4), composite reframed as a peer-rank screen (1.5). **Resolves P1 + P5 (structural) and
> P9 (framing).** Residual follow-ups: M1 embeddings for peer weights (open decision #5); extend
> peer-relative to growth/profitability; expand the peer universe beyond the watchlist.
>
> **Key finding that motivates Phase 2:** after all of Phase 1, MU still scores **0.852 STRONG_BUY** —
> at a cycle peak every category reads bullish (growth/momentum=1.0, event=0.99), so no ruler or
> weighting produces caution. **Phase 1 cannot fix MU by construction;** that needs normalized/mid-cycle
> earnings (2.2), a cycle-position signal making peak-momentum a NEGATIVE (ML M3), and un-quarantined
> skepticism (2.1/2.4).

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

> **Status: 2.1 DONE (2026-06-02) — Bull/Bear/Judge dialectic.** New `agents/bull_agent.py`,
> `bear_agent.py`, `judge_agent.py` + `agents/synthesis.py` (shared evidence pack). Registered in the
> orchestrator after the analytical agents (bull → bear → judge), bear is first-class. The judge MUST
> address every bear point (concede/rebut/partial) and its conviction must reflect unresolved bear
> risk. Rendered in the UI (case-point lists + judge leaning/conviction/addressed-points). **Verified
> live on MU:** quant screen says 0.852 STRONG_BUY, but the judge returns **leaning=bull, conviction
> 0.45**, verdict "modest position sized for the significant risks" — having *conceded* "momentum
> exhaustion after 684% gain" and the peak-margin/normalized-earnings bear points. Skepticism is no
> longer quarantined (P2). **Note:** the dialectic is a parallel analyst verdict; it does NOT yet
> feed the composite/decision — wiring judge→conviction is the 2.4 bridge.

> **Status: 2.4 DONE (2026-06-02) — judge + evidence gate bind the decision.** `decision/engine.py`
> now reads the latest judge report and caps the final signal/confidence by its leaning + conviction
> (bear/neutral → cap at HOLD/REDUCE; conviction <0.5 → no STRONG_BUY; <0.35 → HOLD), and an evidence
> gate caps a buy to HOLD when validation reliability <0.4 or >40% of claims are contradicted (reads
> RAW values from the validation report — the normalized `contradiction_rate` feature is inverted).
> Gates only ever LOWER the signal. `judge_leaning`/`judge_conviction` persisted (migration
> `d7b3e9c4a210`), surfaced in the decision API + `DecisionPanel` (shows "quant screen X → adjusted"
> + judge leaning/conviction). **Verified on MU: composite screen 0.852 STRONG_BUY → decision BUY at
> moderate confidence**, capped by the judge's 0.45 conviction (evidence gate correctly did not fire).
> e2e extended with a decision stage (bear judge caps BUY→HOLD). **Follow-up:** validation prompt to
> require a source citation per quantitative claim.

> **Status: 2.2 + 2.6 DONE (2026-06-02) — regime-aware valuation on normalized earnings.** New
> `app/measurement/normalized_earnings.py` (median through-cycle margin → normalized net income +
> cycle-position z-score; pure stats). **Archetype-aware (refined 2026-06-03):** mid-cycle
> normalization only applies to true cyclicals — a `basis` flag (cyclical / stable / inflection)
> prevents mislabeling stable compounders "peak" (AAPL z-noise) and refuses to normalize loss→profit
> turnarounds with a negative historical median margin (UBER). MU still normalizes (0.39x); others
> read "stable" / "inflection". Fed into `valuation_agent.build_context` (REGIME block:
> archetype, current vs mid-cycle margin, spot vs normalized P/E). Prompt rewritten: branch on
> archetype, value cyclicals on NORMALIZED earnings, output a `regime` block + "re-rate vs peak?".
> **2.6:** `margin_of_safety` documented as a FRACTION + `postprocess_report` coerces stray percents
> and clamps (kills the 53.3/31.5 instability). **THE FOUNDING BUG, REVERSED — verified on MU:** the
> agent that once said "significantly_undervalued, ~$1100, MoS 53" now says **moderately_overvalued,
> MoS −0.23**, computing normalized P/E 114x vs spot 44.7x ("the low spot P/E is a peak-earnings
> illusion"). MU's AI-valuation sub-score 0.78 → 0.52. **Residual:** the composite SCREEN is still
> 0.82 STRONG_BUY because growth/momentum/event remain peak-biased — fully de-biasing the screen
> needs cycle-normalized growth/momentum features (ML M3 territory); the binding decision is already
> BUY (judge-capped).

> **Status: 2.5 DONE (2026-06-03) — dated, falsifiable kill-criteria.** The judge now emits
> structured `kill_criteria` (≥2): each a falsifiable prediction + `watch_metric` + `by_date` +
> `would_confirm` (bull/bear), with conviction calibrated against them. Stored in the judge report
> JSONB (Phase 3.2 will grade them at their date). Rendered in the UI as a dated checklist.
> **Verified on MU:** e.g. "Data Center revenue declines QoQ for two consecutive quarters by Q4
> FY2026" (watch: DC segment revenue → bear), "MU guides Q4 FY2026 revenue below $30B by 2026-07-15".
> Closes P6.

> **Status: 2.3 DONE (2026-06-03) — PHASE 2 COMPLETE.** Valuation agent now TRIANGULATES: it states
> its own base fair value, the street mean target, the % divergence (recomputed deterministically in
> `postprocess_report`), and MUST justify any gap >20% — an unexplained gap is flagged "UNJUSTIFIED".
> **Verified on MU — the founding failure, reversed:** the agent that once said $1100 (above the $674
> street, unexplained) now says **fair value $520, −23% vs the $674 street, justified** ("street
> anchors on peak earnings momentum; I normalize for the commodity cycle"). $520 ≈ the user's
> original chat-Claude read (~$500). Satisfies acceptance gate #3 (triangulation). Rendered in the
> valuation card (Your FV / Street target / vs Street + reconciliation note).
>
> **PHASE 2 SHIPPED (2.1–2.6).** Resolves P2 ✅, P4 ✅, P6 ✅, P8 🟨, and finishes P1 ✅. The reasoning
> layer is live end-to-end on MU: regime-aware valuation ($520, overvalued) → dialectic (judge bull,
> conviction ~0.5, engages every bear point) → judge+evidence gate caps the decision to BUY → dated
> kill-criteria for accountability. **Next major arc: Phase 3 (thesis journal + outcome grading +
> calibration) — and the ML/measurement track (M1 embeddings, M3 cycle-position into the screen).**

| # | Action | Effort | Output | Done when |
|---|--------|--------|--------|-----------|
| 2.1 | **Bull / Bear / Judge dialectic** — new `agents/bull_agent.py`, `bear_agent.py`, `judge_agent.py`; orchestrator runs adversarial pass; bear is first-class (cannot be down-weighted) | L | three agents + orchestrator wiring | every report has explicit bull case, bear case, and a judged synthesis with a leaning |
| 2.2 | **Regime-aware valuation** — rewrite `valuation_agent` system prompt: archetype branch; for cyclicals require normalized/mid-cycle earnings; permit domain knowledge; output bull/base/bear + explicit "re-rate vs peak?" section | M | new valuation prompt + schema | MU report contains a memory-cycle regime call + normalized-earnings valuation |
| 2.3 | **Valuation triangulation** — agent must compare its fair value to (a) management guidance and (b) street consensus, and justify any divergence beyond a threshold | M | triangulation block in report | a >X% gap above the $674 consensus must carry an explicit defensible argument |
| 2.4 | **Evidence-gating** — `validation_agent` becomes a publish *gate*: require source citation per quantitative claim; CONTRADICTED/UNVERIFIABLE above threshold blocks or down-confidences the report. Wire `agent_reliability` into conviction in `decision/engine.py` (today it's excluded). | M | validation-as-gate + conviction wiring | a 0.38-reliability report cannot ship as high-confidence STRONG_BUY |
| 2.5 | **Calibrated confidence + kill criteria** — every thesis emits a confidence and ≥2 falsifiable predictions with dates | S–M | schema fields | MU thesis lists e.g. "wrong if HBM ASPs roll over 2 quarters / if all 3 add wafer capacity" |
| 2.6 | **Prompt output-contract fixes** — define units for `margin_of_safety` (fraction) and audit every free `number` field; add post-parse validation | S | fixed schemas + validators | `margin_of_safety` stable + correctly normalized; no undefined-unit fields |

### Phase 3 — Accountability & Decisions (resolves P7, P9)

> **Status: 3.1 DONE (2026-06-03) — thesis journal.** `stock_theses` table (migration
> `e8c1d2f5a730`) + `app/thesis/journal.py::snapshot_thesis`, wired as the last step of
> `run_decision` (run-once-on-pipeline, NOT a scheduler). Each run writes one immutable snapshot per
> ticker/day: archetype, judge leaning + conviction + verdict, valuation fair_value, price_at,
> composite, screen signal, binding decision, and the dated `kill_criteria`. **Verified on MU:** fair
> value $520 vs price $751 captured with 3 dated predictions → a gradable bet on the record. Covered
> by the e2e.

> **Status: 3.2 DONE (2026-06-03) — outcome grading on pipeline run (no scheduler).**
> `app/thesis/grading.py::grade_due_theses`, wired into `run_decision` after the snapshot: finds open
> theses whose kill-criteria `by_date` has passed (ISO or fiscal-quarter parsing) and grades each
> due, ungraded prediction hit/miss/partial/undetermined via one LLM pass over the post-thesis data,
> plus deterministic `realized_return` + `fair_value_gap`. Incremental (grades predictions as they
> come due; flips `status`→graded when all done); cheap no-op when nothing is due. **Verified live on
> a synthetic past-due MU thesis:** "gross margin falls below 30% by 2026-03-31" → **MISS** (cited
> "Q2 FY2026 GM 74.4%"); a not-yet-due fiscal-quarter prediction correctly left open.

> **Status: 3.3 DONE (2026-06-06) — calibration (closes P7).** `app/thesis/calibration.py` turns the
> graded thesis history into a Brier-style score + reliability curve, overall and **per archetype**,
> over two outcome views: the judge's prediction hit-rate and directional (did-the-call-pay) success.
> `overconfidence_gap = mean(conviction) − mean(realized)` answers "is the analyst's stated conviction
> earned?" Exposed at `GET /api/decision/calibration`; pure deterministic stats (one query), degrades
> to a clean no-op until there's graded history. Verified: Brier/bucket/directional math checks out on
> synthetic rows; `calibration_shrink()` feeds 3.4. **This is the trust loop P7 asked for.**

> **Status: 3.4 DONE (2026-06-06) — position sizing.** `app/decision/sizing.py::compute_position_size`
> makes the recommendation a *how much*: a signal-keyed base weight × a transparent multiplier stack —
> **conviction** (judge probability) × data **confidence** × **risk** (critical→0, each major ×0.8) ×
> **concentration** (a correlation-with-book proxy: same-sector watchlist names) × the **calibration**
> shrink from 3.3 — capped at a 10% single-name budget. Deterministic + fully auditable (every factor
> in the rationale); a HOLD/REDUCE/SELL sizes to 0 (trim/exit, not add). Wired into `run_decision`
> (persisted as `stock_decisions.position_sizing` JSONB, migration `f3a9b1c8d240`), surfaced in the
> API + `DecisionPanel`. **Verified on the e2e:** MU's bear-judge-capped HOLD → 0% target, action
> "hold". **Phase 3 COMPLETE.**

| # | Action | Effort | Output | Done when |
|---|--------|--------|--------|-----------|
| 3.1 | **Thesis journal** — `stock_theses` table: thesis, bull/bear, predictions[], confidence, price_at, archetype, links to score/decision | M | persisted theses | each analyst run writes an immutable thesis snapshot |
| 3.2 | **Outcome grading** — **on each Run-Full-Pipeline** (NOT a background scheduler, per user), grade any open thesis whose kill-criteria `by_date` has passed: score each prediction hit/miss/partial against the freshly-ingested data + price vs fair value | M | graded outcomes | due predictions scored on the next pipeline run after their date |
| 3.3 | ✅ **Calibration metrics** — Brier-style score + reliability curve, segmented by archetype | M | `GET /api/decision/calibration` | "when it says 80%, it's right ~X%" answerable, per archetype |
| 3.4 | ✅ **Position-sizing / portfolio context** — recommendation includes size guidance conditioned on conviction + concentration + correlation with existing book | L | `position_sizing` block | recommendation is "how much," not just direction |

### Cross-cutting
- **Industry agent archetype-conditioned (2026-06-09)** — user-spotted over-correction: after the MU
  fixes, the industry prompt forced EVERY stock into a cycle label (META: "mid-cycle internet
  services" — filler). Same disease as the 2.2 normalized-earnings bug, on the reasoning side: one
  ruler for all archetypes. Fix: the agent now receives the archetype, must judge `demand_cyclicality`
  (structural | moderately_cyclical | highly_cyclical) FIRST, and only applies a cycle clock where
  demand is genuinely cyclical — `cycle_position: structural_growth` (scored 0.7) otherwise. Verified
  both directions: META → moderately_cyclical demand (ad spend is GDP-sensitive — a specific claim)
  but structural_growth platform; MU → highly_cyclical / late_cycle with quantified peak evidence.
- **LLM-cost trim (2026-06-09).** Per-pipeline LLM calls **8 → 6** (5 Opus + 1 Sonnet). Two changes,
  both behaviour-preserving (e2e golden composite unchanged): (1) **validation is deterministic-only**
  — the Sonnet semantic pass confirmed ~95% of claims and almost never moved the evidence gate, so it
  was dropped; the pure-Python `deterministic_validator` (which catches the real risk — hallucinated
  numbers — for free) stays and still feeds the gate + AI features. (2) **bull+bear from one Opus call**
  (`agents/debate.py::DebateAgent`) — same evidence pack, so one dual-advocate call writes both `bull`
  and `bear` rows; judge/UI/features/e2e read two rows unchanged. Deeper cuts available if wanted
  (drop news; downgrade earnings/industry to Sonnet) but they trade away analysis depth — not taken.
- **Measurement audit — logged limitation (2026-06-03).** Descriptive measurements (`compute_quant_profile`,
  `computed_metrics`, peer similarity) are correctly universal, but the quant **SCREEN** still applies
  universal rulers that are **peak-biased for cyclicals** (a cyclical at its top scores maximally bullish):
  `quant/normalizer.py` fixed growth/margin/momentum bounds (High), `measurement/peer_normalize.py`
  spot-multiple percentiles (Med), `decision/risk_flags.py` has no peak-cycle flag (Med). Shared fix =
  feed `cycle_position` (already in `measurement/normalized_earnings.py`) into all three → this is **ML
  M3**. The valuation *reasoning* + the *binding decision* are already cycle-aware; only the screen lags,
  and the decision overrides the screen, so not urgent — tracked for M3.
- **Observability & cost** — log every agent's prompt/raw output/tokens (the dry-run harness we built); budget guardrails.
- **Schema/versioning** — version report schemas; migrations for all new tables.
- **Backfill** — re-run EDGAR + IR extraction historically so the calibration loop has data to learn from sooner.
- **Testing & CI — STARTED (2026-05-31).** A single **end-to-end test**
  (`backend/tests/test_pipeline_e2e.py`) drives the whole backend workflow: `ingest_ticker` (real
  EDGAR XBRL parse of a canned payload → 12 quarters + grounded archetype) → `run_all_agents` (5
  agents, LLM mocked) → `calculate_score` (archetype-weighted composite) → `/api/scoring/screen`.
  Only external edges faked (SEC HTTP, Anthropic, yfinance/scraper sub-ingests). DB via
  **testcontainers** (CI) or a `TEST_DATABASE_URL` throwaway DB (fast local). `.github/workflows/
  test.yml` runs it + frontend `tsc` on push/PR. **Follow-ups as Phase 2 lands:** assert the
  dialectic/regime agent outputs + evidence-gate in the same e2e; add a decision-engine stage; cover
  the calibration loop. Treat this as the regression net before each phase.

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
