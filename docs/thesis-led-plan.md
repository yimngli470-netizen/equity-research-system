# Thesis-led research plan — equity-research-system scope

> **Scoped snapshot, 2026-10-07.** The canonical, complete plan (with review packets and
> the dated review log) is `/Users/yiming/Desktop/stock-knowledge-pipeline/plan.md`, with machine-readable state in
> `/Users/yiming/Desktop/stock-knowledge-pipeline/research/thesis-led/state.json`. If they disagree, the canonical plan wins. Refresh
> this snapshot at each phase gate. Sections that govern work in this repository are
> copied verbatim apart from absolute paths; Phase 1–2 history is condensed.

**Status:** Phase 2 is complete, independently reviewed and committed (`b07555e`).
It is **not yet deployed or migrated** in the running app. **Phase 3 is not authorized**;
each phase needs an explicit user instruction after its review.

## Objective

Test whether an AI-assisted research process can identify useful industry changes,
form falsifiable company theses, recognize contradictory evidence, value the
resulting cash flows and make better investment decisions over time. Evaluate
Jev as a low-cost evidence evaluator and an experimental probability forecaster.
Do not presume that either model has a financial forecasting edge.

The user's direction is to understand technology, adoption, supply chains,
competition, management execution and value capture before earnings validate or
invalidate the thesis. Earnings, guidance and transcripts remain important new
evidence. A correct industry forecast, a correct company forecast and a profitable
investment at the entry valuation are three different achievements.

## Scope in this repository

- Extend this application rather than duplicating it: reuse financial ingestion, dated
  research, the forecast compiler, the valuation calculator and the UI.
- First study: **AI infrastructure**, with **NVDA, MU and AVGO** as research subjects
  spanning compute, memory and networking/custom silicon. This is a research scope, not
  stock recommendations or a portfolio. Horizon **12–24 months**, with observable
  next-quarter and six-month milestones on real issuer fiscal periods and publication dates.
- Keep Jev experiments separate from the live application until evaluated.
- Do not run the full application pipeline merely to inspect it: it may spend model
  usage or modify live records. No real brokerage orders, account funding or credit redemption.
- Planning and audit records stay in the planning project under
  `/Users/yiming/Desktop/stock-knowledge-pipeline/research/thesis-led/`. The technical Paper Pilot 008 is independent and unaffected.

## Phase gates

1. Complete only the current approved phase and its acceptance checks.
2. Save artifacts, results, costs and material limitations; update the canonical plan
   (and refresh this snapshot) and
   `/Users/yiming/Desktop/stock-knowledge-pipeline/research/thesis-led/state.json`.
3. End the turn with a review packet and **stop before the next phase**. This pause
   is explicitly requested by the user, not an inferred approval requirement.
4. A user instruction to continue after that review releases **one next phase**.
   Do not treat completion, elapsed time, a heartbeat, a subtask or earlier general
   agreement as approval to cross another gate.
5. Fix failures within the current scope. If scope, budget or scientific choices
   materially change, show the concrete proposed revision at the review gate.
6. No automatic rerolls of evaluation answers. Preserve failures and ambiguous
   labels. A later engineering test must be labeled separately.

### Subscription usage coordination

Before launching each approved model phase, record its provider, subscription route,
physical calls and reported input/output usage in a weekly workstream ledger. Do not
assume all projects share one provider quota: the equity application's checked-in
development route is `claude_code`, while Paper008 uses saved subscription
`gpt-6-astra`; cohort-exploration-009 is complete and has no continuing call allocation.
Record the actual route again before execution, without reading or copying secrets.

Proposed administrative envelope during overlapping entry-review weeks:
**1,050,000 reported input tokens per Monday–Sunday Pacific week** across these
analyst workstreams: preserve Paper008's existing maximum **750,000** (five reviews
at its unchanged 150,000 daily cap), and at most **300,000** for the thesis project.
Every smaller phase, daily and call cap still applies, including Phase 7's 150,000
weekly thesis cap. Cached input counts toward these reported totals. Keep separate
provider ledgers and a separate Jev API spend ledger; do not equate these tokens
with guaranteed provider quota or dollar cost. Coordinating-chat overhead remains
additional and unmetered. Completed engineering/cohort runs stay separately labeled.

Paper008 has scheduling priority; avoid overlapping research inference with its
pre-open review window. If capacity is unavailable, defer thesis research rather
than displace a scheduled paper assessment or switch to paid APIs. Do not recycle
unused allocations into extra calls. This planning ceiling neither changes the
frozen pilot nor activates later research budgets; those require their phase gates.

## Phase overview

| Phase | Outcome | Status |
|---|---|---|
| 1 | Bounded scope, reuse audit and measurement contract | Complete; reviewed |
| 2 | Trustworthy prediction storage and grading | Complete; reviewed; committed `b07555e`; not deployed |
| 3 | External evidence pipeline and first competing theses | Not started |
| 4 | Real-evidence Jev evaluation | Not started |
| 5 | Prospective probability study | Not started |
| 6 | Long-horizon paper research portfolio | Not started |
| 7 | Bounded monitoring and outcome review | Not started |

## Phases 1–2 in this repository (condensed)

The Phase 1 audit of this codebase found the defects that Phase 2 repaired:

| Finding | Observed behavior | Resolution |
|---|---|---|
| F01 | Fiscal-quarter labels mapped to calendar quarter ends without issuer context | Phase 2: exact fiscal identities |
| F02 | EPS actuals matched a nearby date without publication/vintage eligibility | Phase 2: explicit period and resolution rules |
| F03 | Fundamental grading saw later stock prices and loosely bounded later financials | Phase 2: event-specific resolving packets |
| F04 | Same-day thesis and forecast runs could overwrite original predictions | Phase 2: immutable revisions |
| F05 | Generic conviction was reused as probability for different outcomes | Phase 2: event-specific probabilities; legacy labels |
| F06 | Undetermined outcomes could be skipped permanently or close a thesis | Phase 2: unresolved-state lifecycle |
| F07 | Returned grader IDs and labels lacked validation against requested events | Phase 2: strict response validation |
| F08 | Industry context/cache lacks direct external technology/customer/supplier evidence | Phase 3: external evidence context |

Phase 2 (`app/accountability`, migration `f6a2c9e01844`; details in `CLAUDE.md`,
"Accountability v2") delivered append-only thesis/forecast revisions, explicit event
contracts with exact period/basis/vintage resolution, proper event-probability scores,
and visibly frozen legacy grading. Stock-versus-SPY price marks continue separately and
are labelled as diagnostics, not fundamental evidence. An independent review found six
defects (including forecasts accepted after a result's release window opened, and
duplicate thesis rows on every run); all were fixed with regression tests. 153 backend
tests pass. Review records: `/Users/yiming/Desktop/stock-knowledge-pipeline/research/thesis-led/phase-2/`.

**Deployment** (not yet done): back up the production database, apply the commit,
run `alembic upgrade head`, then restart the backend. Pulling into the bind-mounted
checkout is itself a deployment. Do not use research/LLM pipeline runs as a smoke test.
Between deployment and Phase 3 event registration, price marks update but no new
fundamental grades are produced. Before Phase 7 adds concurrent workers, review the
per-issuer lock held during qualitative inference.

## Phase 3 — External evidence and the first industry study

### Steps

1. Add a small source registry and immutable captures for technical/product
   documentation, customer spending/deployment, supplier capacity/lead times,
   competition, filings and management promises. Reuse existing collection where
   suitable. Record publication time, observation time, source type and coverage.
2. Preserve full authorized source material where available and exact cited spans.
   Label previews and missing material honestly. Deduplicate syndicated stories
   and multiple claims from one underlying announcement.
3. Extend the industry context and cache fingerprint to react to external evidence
   changes. Keep data refresh and substantive model analysis separately budgeted.
4. Build one dated AI-infrastructure map from technology through customer economics
   to company cash generation. Start with three competing explanations: durable
   demand; growth with profits shifting across suppliers; and overbuilding or
   weaker customer returns. They are hypotheses, not established conclusions or
   an automatically exhaustive probability partition.
5. Create NVDA/MU/AVGO thesis cards with assumptions, strongest contrary evidence,
   management delivery history, measurable milestones, falsifiers and valuation
   sensitivities. Separate facts, derived numbers and judgments.

### Bounds and review

Start with **at most 24 primary documents**, expanding only at review if essential
coverage is missing. Research analyst subprocess budget: **8 calls / 300,000
reported input tokens total**, using the established subscription route without
paid-provider fallback. Exact model/runtime and admission limits are recorded
before execution. Coordinating work is additional and cannot be perfectly metered.
Stop with an explicit coverage report rather than collecting indefinitely.

**Gate:** review evidence quality, competing theses, missing sources and thesis
cards. No paper positions or claims of forecast accuracy are created in this phase.

## Phase 4 — Evaluate Jev on real financial evidence

### Steps

1. Define **150 claim/excerpt pairs**: 50 development and 100 held out by whole
   document/event, with issuer separation where practical. Include external
   customer/supplier evidence, not only earnings. Include support, contradiction,
   insufficient information, guidance-versus-actual and accounting-basis traps.
2. Establish source-based labels and adjudicate disagreements independently of
   the tested model. Model-generated labels alone are not ground truth. Ambiguous
   cases remain separately reported under a predeclared rubric.
3. Tune wording only on development. Freeze labels, prompts, splits, model IDs,
   thresholds and metric definitions before revealing held-out answers. The same
   evaluator must not read held-out labels while constructing its predictions.
4. Compare Jev with deterministic checks where applicable and a subscription
   reasoning-model baseline on identical evidence. Keep answer-order probes paired;
   they do not increase the independent sample count.
5. Measure material-contradiction recall, false support, macro F1, proper probability
   scores, errors versus coverage, latency and usage. Show event/document clustering
   and uncertainty; 100 cases cannot establish universal financial calibration.
6. Recommend evidence-triage integration, further limited diagnosis, or no Jev use.
   Jev failing this gate does not block the underlying thesis research process.

### Bounds and review

Maximum **300 Jev calls / 500,000 reported input tokens**, no retries. Verify the
current published rate, model version and request-admission bound before calls;
review again if projected API spend exceeds **$0.05**. This is a bounded Jev-only
API exception, not permission for other paid models. The frontier baseline is
limited to **4 subscription calls / 150,000 input tokens**; batch isolated cases
without giving the model gold labels. If these bounds cannot fit the planned
comparison, revise the design at review rather than silently dropping cases.

**Gate:** inspect held-out errors and costs; decide whether Jev merits a role and
approve the precise next experiment. No automatic trade authority follows accuracy.

## Phase 5 — Register forward probability forecasts

1. Define approximately **20 resolvable future events**, principally next-quarter
   company/industry milestones, with exact observation and adjudication rules.
   Include downside outcomes. Avoid vague questions such as “will this be the
   next winning stock?” or arbitrary three-year price-target bins.
2. Have Jev and the main reasoning model assess the same frozen evidence
   independently, without seeing one another's probabilities or conclusions.
   Capture persistence/guidance/consensus baselines where actually available;
   unavailable baselines remain missing, not invented.
3. Timestamp original predictions and all subsequent revisions. Freeze the primary
   forecast used for each score. Never count correlated events, multiple horizons
   or updated forecasts as independent replications.
4. Plan paired Brier/log-loss comparisons and event-cluster uncertainty. Assess
   narrative/wording sensitivity separately. Do not infer probability calibration
   from confidence fields or multiply correlated event probabilities.

### Predeclared decision criteria for review before Phase 5

The first approximately 20 events test registration, evidence collection and
resolution operations. They cannot justify model superiority or investment-return
claims. Before collecting these forecasts, freeze the eventual comparison rule,
cluster definitions, missingness treatment and evaluation dates. Proposed defaults:

- No comparative forecasting claim before **100 resolved primary events across at
  least two quarters and five distinct issuer/event clusters**. Shared demand and
  supplier/customer announcements remain linked even across issuers; overlapping
  horizons and revisions are not additional samples. These are minimum coverage
  gates, not a power calculation or a guarantee of independent evidence. A small
  number of effective clusters can still make the answer inconclusive.
- Define the useful effect as **0.02 lower mean Brier score** against one primary
  persistence/guidance/consensus baseline selected before outcomes. A claim requires
  that effect plus a 95% cluster-aware paired interval entirely on the improvement
  side of zero. Predeclare handling of multiple model comparisons and secondary
  log-loss analysis. If no defensible baseline or uncertainty estimate is available,
  report descriptive results and no superiority claim.
- Apply the same forecasting gate to Jev and the main analyst. Jev's low cost may
  justify evidence triage after Phase 4, but not using its probabilities for capital
  allocation. A proposed cheaper-forecaster use additionally requires the upper
  95% bound on **Jev minus main-model Brier loss** to be below **0.01**, alongside
  the approved error/coverage criteria; this is distinct from superiority. Failure
  or inconclusive evidence means no forecasting promotion, not a fresh tuned rerun.
- For the main analyst, failing forecasting gates does not prevent clearly labeled
  source synthesis and thesis research. Neither model's forecasting score alone
  establishes a portfolio edge or authorizes real money.

Reaching 100 events would require separately reviewed scope, time and budget beyond
this 20-event phase. Do not expand automatically. At the Phase 5 gate, justify or
revise these numerical defaults using an outcome-blind precision/power analysis and
the proposed cluster structure, then freeze them before prospective outcomes.

Budget: **40 Jev calls / 100,000 input tokens** and **4 subscription analyst calls /
150,000 input tokens**. Recheck API pricing and scope before starting. No rerolls.

**Gate:** review the event register, predictions, sources and cost. Completion means
forecasts are registered; it does not mean their future outcomes have resolved or
that Jev is trustworthy. Later phase work need not wait a quarter for those results.

## Phase 6 — Prepare and activate a separate long-horizon paper portfolio

1. Translate reviewed theses into explicit watch/start/add/hold/reduce/exit criteria.
   Combine thesis strength, valuation, disconfirming evidence and portfolio risk.
   A positive industry story or a high model probability alone does not force a buy.
2. Specify execution timing, corporate actions, liquidity, fees, slippage and cash
   interest. Use observations available before the commitment; no same-bar hindsight.
3. Proposed first configuration: hypothetical **$100,000**, long-only, no leverage
   or options; 5% initial positions, additions in 5-percentage-point steps, maximum
   15% per company and 45% across the initial three companies. These are proposed
   risk limits to review, not statistically optimized or activated allocations.
   Treat NVDA/MU/AVGO as one shared AI-semiconductor exposure cluster, not three
   independent bets. The 45% limit is a concentration allowance, not diversification.
4. Compare with a fixed initial same-stock basket, **SMH as the primary sector
   comparator and SOXX as a declared sensitivity**, plus SPY and an observable
   cash-yield control. Qualify all comparator data before activation; do not choose
   the more favorable benchmark after outcomes. Match initial capital and execution
   clocks, report actual exposure and turnover, and distinguish total return from
   risk-adjusted or incremental performance.
5. Test the ledger offline and prepare a concrete registration and initial research
   recommendations. Use a new ledger; never reset, merge with or reinterpret Paper008.
6. Limit conclusions from this first study to its shared industry exposure. Before
   drawing general portfolio-return conclusions, separately register and evaluate
   theses in unrelated industries; doing so requires a later scope/budget review.

**Gate:** present policy, starting evidence, hypothetical allocations and verified
accounting. **Activation and any new recurring automation require this review's
approval.** Phase 6 may finish with a ready-but-inactive system; subsequent activation
is a recorded action, not a backdated start. No real-money deployment is authorized.

## Phase 7 — Finite monitoring, resolution and portfolio evaluation

- On approval, start one **four-week operational observation block**. Define dates
  at activation. Event-driven reviews and a weekly digest replace full daily scans.
- Budget: maximum **8 subscription analyst calls / 150,000 input tokens per week**,
  at most two calls per material event; Jev maximum **200 calls / 250,000 input
  tokens per week**, subject to the approved API spend limit. Freeze policy/model
  versions for the block and log missing assessments without backfilling them.
- Review new customer/supplier/product evidence and earnings against saved theses.
  Never rewrite the original thesis to make it look prescient. Keep significant
  conflicting evidence visible even when the automated triage score is low; audit
  a declared sample of suppressed documents.
- At four weeks, report operations, data coverage, usage, decisions and paper P&L.
  Grade only events that have resolved under the approved resolution policy.
  Report forecasts still pending and incomplete evidence separately.
- **Pause for review before another observation block.** Meaningful long-horizon
  return evidence may require multiple quarters and broader independent exposure;
  a short positive paper result does not establish alpha or authorize real money.

## Reporting and stop rules

Every phase report states what changed, its supporting evidence, checks performed,
calls/tokens/estimated costs, unresolved issues and the exact next phase awaiting
review. Failed tests, model errors and missing sources remain in the denominator.
Model/prompt/code changes receive explicit versions; do not reset performance after
a disappointing outcome. Freeze comparison definitions before measuring outcomes.

If reliable evidence, affordable execution or meaningful grading is unavailable,
finish the bounded phase with that limitation and a concrete recommendation.
Do not expand into another strategy search simply to manufacture a positive result.

## Records in the planning project

- Canonical plan: `/Users/yiming/Desktop/stock-knowledge-pipeline/plan.md`
- Thesis-led direction: `/Users/yiming/Desktop/stock-knowledge-pipeline/research/thesis-led-direction-2026-10-03.json`
- Jev diagnostic and proposed evaluation: `/Users/yiming/Desktop/stock-knowledge-pipeline/research/jev-evaluation-2026-10-04.json`
- Phase 1 audit and contract: `/Users/yiming/Desktop/stock-knowledge-pipeline/research/thesis-led/phase-1/`
- Phase 2 review, follow-up and verification: `/Users/yiming/Desktop/stock-knowledge-pipeline/research/thesis-led/phase-2/`
