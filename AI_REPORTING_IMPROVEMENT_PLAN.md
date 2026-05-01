# AI Reporting Improvement Plan

This document captures the next architecture improvements for making the equity
research system more accurate, auditable, and useful. The guiding principle is:

> Code owns facts. AI owns interpretation. Validation owns the boundary.

The current system already ingests market and financial data, computes hard
features, runs specialist AI agents, calculates composite scores, and produces
decision signals. The main gap is that agents still receive mostly formatted
text and can produce numeric claims that are hard to trace back to exact data
rows or calculations.

## Current Biggest Gaps

1. Raw rows do not consistently store provenance.
   - `financials`, `daily_prices`, and `valuations` imply their source through
     ingestion code, but the rows themselves do not store `source`,
     `source_url`, `fetched_at`, or `as_of_date`.

2. Computed facts are not first-class objects.
   - Growth, margins, FCF conversion, operating leverage, and momentum are
     calculated in `backend/app/ingestion/computed_metrics.py`.
   - They are passed to agents and scoring, but they are not stored as
     addressable fact records with stable IDs.

3. Freshness is not explicit enough.
   - Running ingestion does not guarantee the latest data is actually present.
   - "Latest" depends on the data type: daily price, quarterly financials,
     valuation snapshot, news, transcript, and analyst estimates all have
     different clocks.

4. Agent outputs are not evidence-linked.
   - Agents can cite numbers and conclusions, but the schema does not require
     `fact_ids` or `evidence_ids` for important claims.

5. Validation is still too AI-centered.
   - The validation agent currently asks an LLM to check claims against DB data.
   - Numeric/date/source validation should be deterministic code first, with AI
     reserved for softer semantic checks.

6. There is no final validated report compiler.
   - Raw agent reports are useful for debugging, but the final user-facing memo
     should be compiled from approved facts, validated claims, scoring, and risk
     flags.

## Target Pipeline

```text
Ingestion
  -> Raw source tables with provenance
  -> Fact snapshot builder
  -> Data freshness report
  -> Agent evidence packages
  -> Specialist agents
  -> Claim normalization
  -> Deterministic validation
  -> Semantic validation
  -> Scoring + decision engine
  -> Final investment memo compiler
```

## Phase 1: Make Raw Data Auditable

### Goal

Every stored raw data row should be able to answer:

- Where did this come from?
- When did we fetch it?
- What date or period does it represent?
- Can we inspect the original payload if needed?

### Implementation

Add provenance fields to key raw data tables:

- `source`: example `yfinance`, `fmp`, `sec`, `computed`
- `source_url`: nullable string
- `fetched_at`: timezone-aware datetime
- `as_of_date`: date represented by the source value
- `source_payload`: optional JSONB for debugging source responses

Start with:

- `daily_prices`
- `financials`
- `valuations`
- `documents`
- `earnings_events`
- `analyst_estimates`
- `earnings_transcripts`

### Done When

- New Alembic migration exists.
- Ingestion writes provenance fields.
- API/debug views can show source and fetch time.
- Existing ingestion remains idempotent.

## Phase 2: Create A First-Class Fact Layer

### Goal

Turn computed metrics into stored, addressable, auditable facts.

Today:

```text
raw yfinance rows
  -> Python calculates revenue_yoy, gross_margin, momentum_3m
  -> agents/scoring receive temporary values
  -> values disappear
```

Target:

```text
raw yfinance rows
  -> Python calculates revenue_yoy, gross_margin, momentum_3m
  -> each calculated value is stored as a fact with a stable fact_id
  -> agents, scoring, validation, and reports reference the same facts
```

### Proposed Tables

`fact_snapshots`

```text
id
ticker
snapshot_date
created_at
data_freshness JSONB
metadata JSONB
```

`facts`

```text
id
snapshot_id
fact_id
ticker
category
name
value
unit
period
as_of_date
source
input_refs JSONB
metadata JSONB
created_at
```

### Example Facts

```json
{
  "fact_id": "META:financial:2026Q1:revenue_yoy",
  "ticker": "META",
  "category": "growth",
  "name": "Revenue YoY Growth",
  "value": 0.238,
  "unit": "percent",
  "period": "Q1 2026",
  "as_of_date": "2026-03-31",
  "source": "computed",
  "input_refs": [
    "financials:META:2026-03-31:revenue",
    "financials:META:2025-03-31:revenue"
  ],
  "metadata": {
    "formula": "(current - prior_year) / abs(prior_year)"
  }
}
```

Other useful fact IDs:

- `META:price:latest_close`
- `META:price:momentum_1m`
- `META:price:momentum_3m`
- `META:price:momentum_12m`
- `META:financial:2026Q1:revenue`
- `META:financial:2026Q1:gross_margin`
- `META:financial:2026Q1:operating_margin`
- `META:financial:2026Q1:fcf_conversion`
- `META:valuation:forward_pe`
- `META:valuation:price_to_sales`

### Implementation

Create a fact builder, for example:

```text
backend/app/facts/builder.py
backend/app/facts/models.py
backend/app/facts/service.py
```

It should reuse the existing calculations in:

```text
backend/app/ingestion/computed_metrics.py
```

Then scoring should gradually move from reading `ComputedSnapshot` directly to
reading the latest `fact_snapshot`.

### Done When

- Running a pipeline creates a fact snapshot for the ticker.
- Growth, profitability, valuation, and momentum facts are stored with IDs.
- Facts include formulas and input references where applicable.
- Existing scoring can be reproduced from stored facts.

## Phase 3: Add Data Freshness Checks

### Goal

After ingestion, deterministically decide whether each data category is fresh,
stale, missing, or unknown.

This phase is not about fetching data. It is about inspecting what ingestion
actually stored and preventing agents from pretending stale data is current.

### Why This Exists

"Latest" is contextual:

- Yesterday's price is acceptable before today's market close, but stale after
  today's completed daily bar should exist.
- Revenue growth from the latest earnings report is fresh until a newer quarter
  is reported.
- Valuation snapshots should generally align with the latest price date.
- News and transcripts have different acceptable delays.

### Proposed Module

```text
backend/app/data_freshness.py
```

Public function:

```python
async def build_freshness_report(db: AsyncSession, ticker: str) -> FreshnessReport:
    ...
```

Initial checks:

- `price`
- `financials`
- `valuation`
- `news`
- `transcripts`
- `analyst_estimates`

### Freshness Rules V1

Daily price:

- Fresh if the latest stored price date is the latest expected completed trading
  day.
- V1 can handle weekends manually.
- Later replace with a real exchange calendar.

Financials:

- Fresh if the latest financial period is within a conservative quarterly window,
  for example 140 days.
- Later improve with earnings calendar/report-date checks.

Valuation:

- Fresh if the valuation snapshot date is at least as recent as the latest
  available price date.

News:

- Fresh if ingestion succeeded and recent items exist in the configured lookback
  window.
- Unknown if no recent news exists but no fetch error occurred.

Transcripts:

- Fresh if the latest transcript matches the latest known earnings call.
- Unknown if no transcript source is configured.

Analyst estimates:

- Fresh if future-period estimates exist and were fetched recently.

### Example Report

```json
{
  "ticker": "META",
  "run_date": "2026-04-30",
  "price": {
    "latest_date": "2026-04-30",
    "expected_date": "2026-04-30",
    "status": "fresh"
  },
  "financials": {
    "latest_period": "Q1 2026",
    "period_end_date": "2026-03-31",
    "status": "fresh"
  },
  "valuation": {
    "latest_date": "2026-04-30",
    "status": "fresh"
  },
  "warnings": []
}
```

### Done When

- Pipeline produces a freshness report after ingestion.
- Freshness warnings are prepended to agent contexts.
- UI can display warnings after "Run Full Pipeline".
- Agents are instructed not to call stale data current.

## Phase 4: Replace Text Context With Evidence Packages

### Goal

Agents should receive structured facts and evidence, not just formatted prose.

### Implementation

Create agent-specific evidence packages:

```json
{
  "ticker": "META",
  "freshness": {},
  "facts": [
    {
      "fact_id": "META:financial:2026Q1:revenue_yoy",
      "name": "Revenue YoY Growth",
      "value": 0.238,
      "unit": "percent",
      "period": "Q1 2026"
    }
  ],
  "evidence": [
    {
      "evidence_id": "META:transcript:2026Q1:guidance:001",
      "type": "transcript_excerpt",
      "text": "..."
    }
  ]
}
```

Different agents receive different subsets:

- News agent: recent documents and source metadata.
- Earnings agent: financial facts, transcript excerpts, earnings surprises.
- Valuation agent: valuation facts, estimates, price facts, guidance excerpts.
- Industry agent: business facts, competitive transcript excerpts, relevant news.

### Done When

- Each agent context includes structured JSON evidence.
- Numeric facts are supplied as facts, not left for the LLM to calculate.
- Old prose context can remain as a readability helper, but not as the source of
  truth.

## Phase 5: Require Evidence-Linked Agent Claims

### Goal

Every important agent claim should cite the exact facts or evidence that support
it.

### Example Schema

```json
{
  "claim": "Revenue growth accelerated YoY",
  "claim_type": "interpretation",
  "supporting_fact_ids": [
    "META:financial:2026Q1:revenue_yoy",
    "META:financial:2025Q4:revenue_yoy"
  ],
  "supporting_evidence_ids": [],
  "confidence": 0.86,
  "reasoning": "Q1 revenue growth exceeded the prior quarter's YoY rate."
}
```

Rules:

- Numeric claims must cite fact IDs.
- Qualitative claims should cite evidence IDs when possible.
- Unsupported claims must be marked `unsupported`.
- The final report compiler should avoid unsupported material.

### Done When

- Agent schemas include `claims`.
- Claims contain `supporting_fact_ids` or `supporting_evidence_ids`.
- Agents that cannot support a claim say so explicitly.

## Phase 6: Split Validation Into Deterministic And Semantic Validation

### Goal

Validation should stop relying on an LLM for arithmetic and date checks.

### Deterministic Validator

Implemented in Python.

Checks:

- Numeric claims match cited fact values.
- Dates match fact `as_of_date` or source periods.
- Required fact IDs are present.
- Cited fact IDs exist in the latest snapshot.
- Data freshness warnings are respected.
- Unverifiable claims are penalized.

### Semantic Validation Agent

Uses AI only for softer judgments:

- Is the management tone interpretation fair?
- Are risks overstated or understated?
- Is valuation reasoning internally consistent?
- Does the news impact framing match the actual article?
- Are conclusions too strong given the evidence?

### Done When

- Numeric/date/source validation is mostly deterministic.
- AI validation is limited to semantic interpretation.
- `agent_reliability` is based on deterministic checks plus semantic flags.

## Phase 7: Add Final Investment Memo Compiler

### Goal

Raw agent reports should not be the primary artifact the user reads. The final
memo should be compiled from facts, validated claims, scores, and risk flags.

### Inputs

- Latest fact snapshot.
- Data freshness report.
- Validated agent claims.
- Scoring output.
- Decision engine output.
- Risk flags.

### Output Sections

- Snapshot
- What changed
- Earnings quality
- Valuation
- Sentiment and news
- Industry and competitive position
- Key risks
- Decision rationale
- Data freshness and caveats

### Done When

- User-facing memo avoids unsupported claims.
- Memo cites fact IDs or source labels internally.
- Raw agent JSON remains available for debugging.

## Phase 8: Add Evals And Regression Tests

### Goal

Prevent future hallucination and freshness regressions.

### Test Cases

- Latest price row is yesterday after market close.
- Latest price row is Friday on a weekend.
- Agent claims YoY growth when no year-ago quarter exists.
- Agent cites wrong numeric value for a known fact.
- Validation date is hallucinated by model output.
- Report has many unverifiable claims.
- New earnings event exists but financials are old.
- Valuation snapshot is older than latest price.
- Agent outputs claim without fact IDs.

### Done When

- Tests run locally and in CI.
- Deterministic validator has focused unit tests.
- Freshness rules have date-specific tests.
- Report compiler has golden-output style tests for key scenarios.

## Recommended Next Three Builds

1. Add provenance fields and ingestion writes.
   - This makes raw data auditable.

2. Add `fact_snapshots` and `facts`.
   - This makes computed metrics addressable and reusable.

3. Add deterministic freshness reporting.
   - This prevents agents from silently treating stale or missing data as latest.

After those three are in place, update the agent schemas to produce
evidence-linked claims and split validation into deterministic and semantic
checks.

## Design Rules For Future Agents

- Do not let AI originate financial numbers.
- Do not ask AI to calculate ratios that Python can calculate.
- Do not call data current unless freshness checks say it is current.
- Require fact IDs for numeric claims.
- Treat unverifiable claims as a report quality problem, not a harmless detail.
- Keep raw agent outputs for debugging, but make the final memo validated and
  source-aware.
