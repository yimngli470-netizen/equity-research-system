# Thesis-led investment research and Jev evaluation

Created: 2026-10-06 (America/Los_Angeles)

**Current phase: 3 — external evidence pipeline and industry study.**
**Status: Phase 3 complete, awaiting review. Pause before Phase 4; application changes are not deployed.**

Latest review follow-up: Claude's Phase 3 findings are addressed in the isolated
checkout and append-only [review packet](research/thesis-led/phase-3/claude-followup-001/response.md).
C1 is fixed; 175 backend tests and 84 migrated-schema checks pass. Three recorded
subscription evaluations consumed 51,629 input and 52,066 output tokens in 666.25
seconds: two reports passed citation membership, with substantive semantic errors
recorded; Broadcom's answer failed JSON parsing and was not rerolled. Twenty-four
primary documents and dated reverse-valuation diagnostics are retained. These are
process results, not forecast or trading validation. Phase 4 remains unapproved.
The user separately authorized repairing Paper008 after this review follow-up.

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

## Scope and ownership

- This file is the execution plan for the new thesis-led work, including Jev.
  It does not replace the earlier technical-analysis research archive.
- Extend `/Users/yiming/Desktop/equity-research-system`; reuse its financial
  ingestion, dated research, forecast compiler, valuation calculator and UI.
  Read that project's current instructions before implementing there.
- Keep planning/audit records under `research/thesis-led/` in this repository.
  Keep Jev experiments separate from the live application until evaluated.
- `equity-research-system/docs/thesis-led-plan.md` is a scoped snapshot of this plan
  for that repository. This file stays canonical; refresh the snapshot (and commit it
  there) at each phase gate.
- Working first study: **AI infrastructure**, with **NVDA, MU and AVGO** as three
  research subjects spanning compute, memory and networking/custom silicon.
  These are a proposed research scope, not stock recommendations or a portfolio.
- Working horizon: **12–24 months**, with observable next-quarter and six-month
  milestones. Use real issuer fiscal periods and publication dates.
- Preserve technical Paper Pilot 008/run-v5, its automation, frozen rules, accounts
  and finite schedule. Its existing scheduled work continues independently.
- Keep the historical strategy holdout closed and episode-source review paused.
  Do not restart numerical fundamental screens as the default research direction.
- No real brokerage orders, account funding or credit redemption. Do not invoke
  the existing full application pipeline merely to inspect it: it may spend model
  usage or modify live records.

## Phase gates

1. Complete only the current approved phase and its acceptance checks.
2. Save artifacts, results, costs and material limitations; update this plan and
   `research/thesis-led/state.json`.
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

| Phase | Outcome | Completion evidence | Status |
|---|---|---|---|
| 1 | Bounded scope, reuse audit and measurement contract | Source-linked findings, contract, offline verification | Complete; reviewed |
| 2 | Trustworthy prediction storage and grading | Focused regression tests and reviewed migration plan | Complete; reviewed and published; not deployed |
| 3 | External evidence pipeline and first competing theses | One dated industry evidence pack and three company thesis cards | Complete; awaiting review |
| 4 | Real-evidence Jev evaluation | Fixed held-out results, errors, costs and integration recommendation | Not started |
| 5 | Prospective probability study | Approximately 20 timestamped future-event forecasts and resolution rules | Not started |
| 6 | Long-horizon paper research portfolio | Reviewed policy, tested accounting and initialized separate paper ledger | Not started |
| 7 | Bounded monitoring and outcome review | A finite observation report; subsequent blocks need their own review | Not started |

## Phase 1 — Scope, audit and measurement contract

### Steps

1. Locate existing journal, forecast, grading, calibration, evidence, cache and
   model-transport components; inspect code rather than relying on roadmap claims.
2. Record reusable components, concrete defects, source locations and source hashes.
3. Define the minimum records for sources, thesis versions, forecast events,
   probabilities, resolutions and model-call receipts.
4. Separate three scorecards: evidence interpretation, forecasting and investment
   returns. Define how ambiguity and missing observations are handled.
5. Specify Phase 2 acceptance cases and execution boundaries. Validate the saved
   records offline; make no model calls, trades or application/database changes.

### Deliverables and acceptance

- `research/thesis-led/phase-1/audit.json`: findings traceable to inspected code;
  distinguish confirmed code behavior from untested live consequences.
- `research/thesis-led/phase-1/contract.json`: proposed data/measurement contract,
  explicit defaults and Phase 2 regression cases.
- `research/thesis-led/phase-1/verification.json`: parse, reference, hash and
  focused offline behavior checks; no claim of full application test coverage.
- `research/thesis-led/state.json`: phase state and review gate.
- **Gate:** review study scope, proposed contract and implementation priorities.

### Completed Phase 1 review packet — October 6

The existing application has useful financial provenance, forecast arithmetic,
valuation and subscription transport. We can extend those components. The audit
identified eight issues relevant to this study:

| Finding | Observed behavior | Planned work |
|---|---|---|
| F01 | Fiscal-quarter labels map to calendar quarter ends without issuer context | Phase 2: exact fiscal identities |
| F02 | EPS actuals match a nearby date without publication/vintage eligibility | Phase 2: explicit period and resolution rules |
| F03 | Fundamental grading sees later stock prices and loosely bounded later financials | Phase 2: event-specific resolving packets |
| F04 | Same-day thesis and forecast runs can overwrite original predictions | Phase 2: immutable revisions |
| F05 | Generic conviction is reused as probability for different outcomes | Phase 2: event-specific probabilities and separate legacy labels |
| F06 | Undetermined outcomes can be skipped permanently or close a thesis | Phase 2: unresolved-state lifecycle |
| F07 | Returned grader IDs and labels lack validation against requested events | Phase 2: strict response validation |
| F08 | Industry context/cache lacks direct external technology/customer/supplier evidence | Phase 3: external evidence context |

Verification passed for **10 source snapshots, 20 source references and three
isolated behavior probes**. The probes reproduce the issuer-independent date
mapping, acceptance of a 31-day-away actual, and reuse of one conviction value in
two different scores. They are not full application tests or evidence that every
live historical grade is wrong. Seven proposed record types and twelve future
Phase 2 regression cases are saved in the contract.

- [Audit and source references](research/thesis-led/phase-1/audit.json)
- [Measurement and record contract](research/thesis-led/phase-1/contract.json)
- [Offline verification](research/thesis-led/phase-1/verification.json)
- Reproduce the offline checks: `python3 research/thesis-led/phase-1/verify.py`.

No application/database changes, new research analyst calls or Jev calls occurred.
Paper008's independent schedule remains unchanged. Review the first-study scope
(AI infrastructure; NVDA/MU/AVGO; 12–24 months) and these repair priorities before
authorizing Phase 2. All later model budgets and paper allocations remain proposals
for their respective review gates.

## Phase 2 — Repair accountability before relying on results

### Steps

1. Introduce append-only, timestamped forecast/thesis versions and explicit links
   to immutable evidence snapshots. Do not overwrite same-day predictions or
   retroactively assign probabilities to old narrative convictions.
2. Resolve events by issuer, metric, unit/accounting basis, exact fiscal period,
   deadline and predeclared resolving source. Check when evidence became public
   and when it was observed; approximate quarter proximity cannot prove a match.
3. Grade numerical events with code. Give qualitative resolution only the
   evidence allowed by that event's resolution policy. Keep subsequent prices
   out of fundamental grading; price-return events have their own path.
4. Preserve unresolved, missing and disputed cases. Define their later review or
   expiry; do not turn them into a miss or permanently close them as resolved.
5. Score event-specific probabilities against corresponding outcomes. Keep generic
   conviction and existing legacy metrics separately labeled. Preserve old results
   with their original grading versions; do not silently rewrite their history.
6. Use mocks and a throwaway database for tests. Prepare migration/backward-
   compatibility evidence before applying changes to an existing database.

### Acceptance and review

Regression cases cover non-calendar fiscal years, unavailable/revised actuals,
same-day revisions, accounting-basis mismatch, post-deadline information, irrelevant
price information, unresolved events, duplicate/foreign grader IDs and correct
Brier/log-loss arithmetic. Existing relevant application tests pass. Changes do
not alter Paper008. At review, show the diff, test results, migration implications
and limitations. **Do not start evidence/model experiments yet.**

### Completed Phase 2 review packet — October 6

Implemented in the isolated checkout
`/Users/yiming/Desktop/equity-research-thesis-phase2` on branch
`codex/thesis-accountability`. **Not deployed:** the primary checkout is bind-mounted
into an auto-reloading app, so this phase keeps code and schema changes together for
review before touching that running system. Its existing user edits are preserved.

- Thesis and forecast writers append immutable revisions and hashed input snapshots;
  identical forecast inputs/content reuse the latest record. After review, thesis
  identity uses opinion fields: a changed price/score alone no longer appends a
  thesis. The original price/score snapshot is retained. Changed opinions remain separate.
- Explicit events resolve against exact issuer periods, metric/unit/basis, source,
  publication and observation clocks, and a declared original/restated-vintage policy.
  Fundamental packets exclude stock prices and unrelated quarters. Numerical grades
  and probability arithmetic run in code.
- Missing/disputed evidence remains unscored and may resolve after new evidence.
  Grader IDs, outcomes and exact cited spans must validate as a complete batch.
  Failed/interrupted model requests cannot be automatically rerolled, including
  when other events change the batch membership.
- Probability scores use the first registered submission for each event/forecaster;
  revisions and correlated event clusters remain explicit. Generic conviction is
  labeled as a legacy diagnostic and no longer drives the calibration sizing factor.
- Legacy records/outcomes are preserved. Approximate quarter projections and vague
  narrative criteria receive no new automatic grades without explicit registration.
  Source/calendar qualification and external evidence retrieval remain Phase 3 work.

**Checks passed:** 131 backend tests (92 existing + 39 new); 40 of those also pass
against the actual migrated schema; an independent upgrade/downgrade and history-
preservation rehearsal; and the frontend TypeScript/Vite build. Tests used disposable
PostgreSQL containers with external networking blocked and mocked model boundaries.
The review patch applies cleanly to the existing checkout, and all 277 previously
tracked primary files retain their original hashes. These are engineering checks,
not forecasts or evidence of a trading edge.

- [Review, migration implications and limitations](research/thesis-led/phase-2/review.json)
- [Verification and changed-file hashes](research/thesis-led/phase-2/verification.json)
- [Only this phase's changes](research/thesis-led/phase-2/phase-2.patch)
- [Preserved engineering failures and repairs](research/thesis-led/phase-2/engineering-history.json)

Migration `f6a2c9e01844` adds revision/evidence/event tables and immutability guards.
It preserves old data; downgrade refuses once new history exists. Before deployment,
review the patch, back up production, and coordinate backend downtime with the schema
upgrade. Do not copy the entire isolated checkout over the primary directory: it
also mirrors pre-existing unrelated user changes.

No production database migration, real analyst/Jev inference, external evidence
study, new automation or strategy activation occurred. Paper008 remains independent.
**Pause here for review before Phase 3 or live deployment.**

### Phase 2 review follow-up — October 6

- Restore dated, immutable stock-versus-SPY price diagnostics separately from
  fundamental grading. They are changes in stored close prices, not trade P&L or
  total returns; old quote adjustment basis can be unverified. Show dates and
  limitations in the track record, judge context and newly generated notes.
- Keep legacy EPS and narrative grading **visibly frozen under accountability-v2**.
  Existing outcomes remain intact. Between deployment and event registration,
  market marks may update, but there are no new fundamental grades without
  registered events and qualified observations. No deployment date is invented.
- Enforce forecast cutoff at or before the first eligible release time and reject
  new submissions at the cutoff. Every equality rule declares an absolute tolerance
  in the metric's units, including explicit zero for exact equality.
- Persist numeric resolutions independently of qualitative failures. Preserve each
  admitted call and returned failure. Allow only an explicit, logged operator retry
  when provider evidence confirms no response was produced; generic timeouts,
  invalid replies and interrupted calls do not establish that. This service is not
  wired to a scheduler or a live provider adapter.
- Resolution currently holds a per-issuer transaction lock during qualitative
  inference. Before Phase 7 adds concurrent workers, review lock duration, worker
  ownership and crash recovery without weakening immutable call admission.

The follow-up adds 22 regression cases; **153 backend tests pass**, with the database
and frontend checks recorded in the follow-up verification. No live migration,
model call, deployment, commit or push is part of this review repair.

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

### Completed Phase 3 review packet — October 7

Phase 3 is complete in `/Users/yiming/Desktop/equity-research-thesis-phase3`, based on
Claude's published Phase 2 and plan snapshot (`e79cfae`). The industry agent now receives
reviewed external evidence, source dates/coverage, exact spans, shared-announcement
clusters and gaps. Immutable sources/captures/packs reuse Phase 2's guarded evidence
store. Changed evidence invalidates both cache modes; identical re-observation reuses
an analysis. Invalid external citations become errors with original receipts preserved.

- [Study and competing explanations](research/thesis-led/phase-3/industry-study.md)
- [Review and limitations](research/thesis-led/phase-3/review.json)
- [NVDA](research/thesis-led/phase-3/thesis-NVDA.json),
  [MU](research/thesis-led/phase-3/thesis-MU.json),
  [AVGO](research/thesis-led/phase-3/thesis-AVGO.json)
- [Evidence packet](research/thesis-led/phase-3/evidence-pack.json)
- [Verification](research/thesis-led/phase-3/verification.json)

Eighteen primary documents were retained: twelve direct HTML captures and six limited
web-retrieved sections after preserved direct HTTP failures. No incomplete section is
labeled a complete original filing. One prior guide/result pair per company provides
retrospective delivery diagnostics, not forecasting credit. The 162 declared arithmetic
sensitivities are not price targets or a validated owner-earnings model. Independent
utilization/project returns, longer management history, confirmed future release dates
and entry-price valuation remain gaps for review, not inferred facts.

171 backend tests pass; 80 tests also pass on actual migrated guards. A real-pack import
rehearsal built all three industry contexts, created zero events/submissions, and rejected
evidence mutation. Zero separate analyst/Jev calls; coordinating subscription reasoning
and search overhead are additional and unmetered. No production migration/deployment,
paid fallback, holdout access, new portfolio or Paper008 change. A local phase commit
and the scoped plan snapshot are prepared for review; nothing is pushed automatically.

**Pause for user review before Phase 4.** Deployment of Phase 2 plus Phase 3 remains a
separate coordinated migration/app operation, not implied by this research gate.

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
   Every scored main-model forecast must link to a recorded physical call with the
   actual model ID, hashed prompt, immutable input snapshot, usage receipt and
   admission before the event cutoff. Coordinating-chat research cards are not
   eligible. Already released events remain unscored; missed registration never
   justifies a backdated forecast or crossing an unapproved phase gate.
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

## Background records

- [Thesis-led direction](research/thesis-led-direction-2026-10-03.json)
- [Jev diagnostic and proposed evaluation](research/jev-evaluation-2026-10-04.json)
- [Existing equity-system roadmap](/Users/yiming/Desktop/equity-research-system/ANALYST_ROADMAP.md)
- [Independent ongoing Paper008](research/paper-trading/pilot-008/README.md)

## Review log

- 2026-10-06: user requested `plan.md`, sequential phases and a pause after every
  phase. Phase 1 is authorized in this turn; no later gate has been released.
- 2026-10-06: Phase 1 completed. Source audit, record contract and offline checks
  are saved; work is paused for review. Phase 2 has not begun.

- 2026-10-06: user approved continuing. Phase 2 is authorized; implementation is isolated in
  `/Users/yiming/Desktop/equity-research-thesis-phase2` to avoid live auto-reload.

- 2026-10-06: Phase 2 completed in an isolated checkout. Tests, migration rehearsal and
  review-only patch are saved; paused for review. Phase 3 and live deployment have not begun.

- 2026-10-06: independent review (Claude) did **not** approve commit/push/deploy yet. Fix
  P1 (track record silently freezes), P2 (cutoff may follow release) and P3 (daily duplicate
  thesis rows) with regression tests first; P4–P6 and plan revisions are in
  [the review](research/thesis-led/phase-2/claude-review-2026-10-06.md).

- 2026-10-06: user requested fixes or reasoned pushback on Claude's review. P1–P6 are
  addressed in an isolated follow-up, with a stricter evidence requirement for
  transport retries. Added deployment behavior, proposed statistical gates, sector
  comparators and provider-specific usage coordination. Paused again for Phase 2
  review; Phase 3, deployment and publishing remain unstarted.

- 2026-10-06: Claude re-verified the follow-up (153 backend tests on a disposable database, original
  leak probe now rejected, clean frontend build) and published Phase 2 as commit `b07555e` on
  `equity-research-system` `main`, built from clean `main` plus the Phase 2 delta only. The user's
  unrelated uncommitted frontend/docs edits were not included. **Not deployed or migrated.**
  Phase 3 is not authorized.

- 2026-10-07: at the user's request, the plan's scope for the equity repository was
  snapshotted to `equity-research-system/docs/thesis-led-plan.md` (commit `e79cfae` on
  `main`, with a pointer from its `CLAUDE.md`). This plan remains canonical. Phase 2 is
  still not deployed; Phase 3 is not authorized.

- 2026-10-07: verified Claude published Phase 2 (`b07555e`) and the repository plan snapshot
  (`e79cfae`). User explicitly authorized Phase 3 after clarifying the phase numbering.
  Implementation proceeds in isolated `equity-research-thesis-phase3` from `e79cfae`;
  pause before Phase 4. No live deployment or model-budget expansion is implied.

- 2026-10-24: independent review of Phase 3 (Claude): evidence and arithmetic verified, 171 tests
  pass. Fix C1 (tickers without an evidence pack can lose the whole industry report) before
  deploying; address R1–R3 (claim-specific citations, recorded-model provenance, market-implied
  expectations) before Phase 5 relies on the cards; mind T1 timing. See
  [the review](research/thesis-led/phase-3/claude-review-2026-10-24.md). Phase 4 not authorized.

- 2026-11-21: user authorized Phase 3 review follow-up then Paper008 repair. C1 and
  R1–R3 addressed; R4 broadened within the 24-document cap with remaining pricing/ROI
  gaps explicit. Three single-attempt IndustryAgent calls are retained, including
  one JSON failure and semantic defects in the two citation-valid reports. T1
  calendar checked; no backdated forecasts or early Phase 5 activation. See
  [follow-up](research/thesis-led/phase-3/claude-followup-001/response.md). Pause before
  Phase 4; proceed with the separately authorized paper-runtime repair.
