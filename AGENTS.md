# AGENTS.md

This project's canonical documentation for AI coding agents lives in **[`CLAUDE.md`](./CLAUDE.md)**
(architecture, how to run, project structure, data flow, conventions) and
**[`ANALYST_ROADMAP.md`](./ANALYST_ROADMAP.md)** (current direction + dated progress log).

Read those instead of a second copy here — a previous standalone copy of the docs in this file
had drifted out of date, so it was replaced with this pointer to keep a single source of truth.

## LLM surface (as of 2026-06-03)

**8 orchestrated research agents** (`BaseAgent` subclasses in `app/agents/`, run per ticker via
`orchestrator.run_all_agents`): `news, earnings, industry, valuation` (analytical) → `bull, bear,
judge` (dialectic, roadmap 2.1) → `validation` (last). **5 LLM utilities** (call Claude but aren't
orchestrated agents, mostly once-per-ticker-cached): `ingestion/archetype` (business-model label),
`ingestion/bootstrap` (KPI defs + IR discovery), `ingestion/kpi_extractor`, `agents/transcript_summarizer`,
`ingestion/ir/repair`. → **13 distinct LLM tasks.**

**Architecture rule (§4a):** the LLM assigns knowledge-laden *labels once* (e.g. `stocks.archetype`,
cached on the row); all downstream numbers (normalization basis, peer weights, scoring, the
normalized-earnings `basis`) are **deterministic code keyed off those labels** — no LLM per
calculation. Keep new measurement logic on the deterministic side; reserve the LLM for
language/knowledge/judgment.

## Known limitations (logged — measurement audit 2026-06-03)

Descriptive measurements (`compute_quant_profile`, `computed_metrics`, peer similarity) are
correctly universal. But the quant **SCREEN** still applies *universal rulers that are peak-biased
for cyclicals* — a cyclical at its cycle top scores maximally bullish:
- `quant/normalizer.py` — fixed growth/profitability/momentum bounds (MU's 196% YoY, 74% GM, 684%
  12m momentum all clamp to 1.0). **High.**
- `measurement/peer_normalize.py` — valuation percentiles use **spot** multiples (a cyclical's
  peak-earnings P/E looks cheap). **Medium.**
- `decision/risk_flags.py` — flags fire on the downside only; there is **no peak-cycle/blow-off
  flag**, so a cyclical at the top trips nothing. **Medium.**

Root cause is shared; the fix is one feature: feed `cycle_position` (already computed in
`measurement/normalized_earnings.py`) into all three (= roadmap **ML M3**). The valuation *reasoning*
and the *binding decision* are already cycle-aware (normalized earnings + judge gate); only the
*screen* lags. Not urgent — the decision overrides the screen — but tracked.
