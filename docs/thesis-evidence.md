# Dated industry evidence — Phase 3

**November 23: reviewed code and its prerequisite schema are now deployed.**
See [deployment verification](deployment-2026-11-23.md). The dated implementation
notes below retain their original scope; the research pack was not imported into
the live DB. Phase 4 remains paused.

Implemented in the isolated Phase 3 worktree on top of published Phase 2 (`e79cfae`).
Not deployed to the bind-mounted application. The canonical phase review packet is
`/Users/yiming/Desktop/stock-knowledge-pipeline/research/thesis-led/phase-3/`.
Read its `industry-study.md`, `thesis-{NVDA,MU,AVGO}.json` and `review.json`.
Phase 4 (Jev evaluation) needs the user's next review approval.

## Data and analysis are separate actions

`app.research_evidence` supplies typed source policies, documents, captures, exact
spans and sequential evidence-pack revisions. Each pack holds at most 24 documents.
The collector issues one bounded HTTPS attempt per declared document, validates each
redirect against that source's exact allowed hosts, retains raw HTML/text and failures,
and refuses to overwrite an existing collection directory. It never calls a model or
imports into the application database. A failed request remains a failure; an operator
may separately retain a web-retrieved section, labeled as incomplete with its own clock
and bytes. It cannot masquerade as complete original HTML.

Publication dates require matching complete date literals. They are date precision,
not fabricated release timestamps. Observation time is recorded separately. Source
age is an administrative freshness policy, not proof of present validity. This API is
for current research; its `today` argument controls freshness and is not a historical
availability filter. Do not use current captures to claim a historical backtest.

Typical commands, from `backend` with its Python dependencies:

```sh
python -m app.research_evidence.collect manifest.json /new/capture-directory
python -m app.research_evidence.cli verify /capture-directory evidence-pack.json
python -m app.research_evidence.cli show /capture-directory CAPTURE_SHA256
```

Review chronology, issuer period/basis, coverage, selected spans, contradictions and
shared announcement clusters before producing a pack. Metadata review is a human or
agent research judgment, not authenticated truth from a hash. Unknown dates stay unknown.
The first study's raw originals and six transport failures are retained alongside its
reviewed captures. Exact quotations are short locators; `show` retrieves full available
text when the context excerpt is insufficient. The ordinary industry inference gets
selected spans, not an automatic full-document retrieval loop.

Import is explicit and atomic, not a scheduler side effect:

```sh
python -m app.research_evidence.cli import /capture-directory evidence-pack.json \
  --database-url "$REVIEWED_DATABASE_URL"
```

Do not point this at production until the coordinated Phase 2 deployment/migration is
approved. No schema change beyond Phase 2 is required: sources, documents, pack revisions
and response receipts use its immutable `research_evidence` table. A per-study lock
serializes imports, sequential revisions determine the current pack, identical imports
are idempotent and changed selections require a new revision/key. There is no implicit
creation of events, forecasts, grades, positions or orders.

## Industry-agent behavior

Both ordinary and smart caches include the current evidence fingerprint. A same-text
capture with a new observation clock reuses the previous report and its old valid citations.
Content, interpretation, coverage/gap or freshness-state changes invalidate the cache.
Exact duplicate texts appear once with aliases. Shared announcement clusters are visible;
semantic syndication and supply-chain dependence still require review. Site boilerplate
changes can conservatively invalidate the cache; no semantic deduplication model is run.

The prompt distinguishes results, management forecasts, vendor claims and inference;
it asks for contradictory evidence, customer economics and observable discriminators.
External claims must cite an exact span supplied to that run. A response/context receipt
retains the original answer before validation. Without supplied documents the optional
assessment is discarded. Invalid external citations discard that assessment and expose
an explicit invalid status, while preserving the core report and its cache behavior.
The core narrative is not independently fact-checked by this fallback. Citation validation
checks reference integrity, not whether the quote proves the interpretation or whether
every uncited claim was detected. Context building clears any previous packet first.
New evidence arriving during inference cannot silently replace the saved packet identity.
An oversized packet fails before inference rather than being silently truncated.

The existing application BaseAgent has a legacy retry policy for ordinary analysis.
The original Phase 3 did not invoke it. The November 21 follow-up exercises the actual
IndustryAgent through a recorded single-attempt subscription transport, with the ordinary
retry policy disabled. Its receipts, input scope and failures live in the follow-up packet.
This feature itself is not an evaluation harness. Future bounded
Jev/forecast experiments must use their own admitted no-reroll transport and budgets;
do not treat a routine application report as a registered prospective assessment.

## Verification and limits

Phase 3 adds 18 focused tests. The complete backend suite passes 171 tests; 80 focused
accountability, evidence and end-to-end tests also pass on an actual migrated disposable
DB. The real 18-document pack imported idempotently there, built three industry contexts,
and the database rejected mutation of its immutable record. No real industry-agent or
Jev subprocess was called. Synthesis used coordinating subscription reasoning; that
usage/search overhead is additional and unmetered. No production DB, app or paper changes.

The current evidence includes twelve direct full-page captures and six limited web
retrievals. It lacks independent utilization, full customer project economics, a broad
management track record, current entry prices and reconciled owner-cash-flow valuations.
The 162 arithmetic cases are declared EPS sensitivities, not price targets, fitted
forecasts or evidence that the system can beat a benchmark.

## November 21 review follow-up

The append-only `phase-3/claude-followup-001` packet addresses Claude's C1 and R1–R4,
and records a timing response to T1. Four added regression cases bring the full backend
suite to 175 passing tests; 84 focused tests pass on an actual migrated disposable DB.
The revised cards retain their original knowledge cutoff and coordinating-chat provenance.
New November facts are separate. Six primary releases bring the pack to its 24-document
cap; independent observed memory pricing and customer project returns remain gaps.
The 216 reverse EPS cases use dated observations and are conditional diagnostics, not
investment recommendations. The recorded analyst calls are process evaluations, not
scored forecasts. See the follow-up verification and response for actual usage/results.
No production deployment, Phase 4 benchmark or Phase 5 event activation is implied.
