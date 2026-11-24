# Phase 2/3 application deployment — November 23, 2026

The user explicitly authorized publishing the reviewed code and deploying it.
Application code through `6987bf3` is pushed to GitHub main and deployed to the
existing laptop Docker Compose application at http://localhost:3000.
This deploy includes Phase 2's prerequisite accountability migration and Phase 3's
external evidence pipeline and reviewed industry-agent fallback.

Validation:
- 175 backend tests pass in an isolated database without model calls or external access.
- The combined frontend, including the existing mobile edits, passes TypeScript and Vite build.
- GitHub backend and frontend CI pass for `6987bf3`.
- A private production database backup was restored into an isolated database and migrated.
- The live migration `c8e4a72f019d` → `f6a2c9e01844` preserves all 30 original data tables
  by normalized row fingerprints, including 64 theses, 64 forecasts and 91 research notes.
- Health, stocks, and all four track-record read endpoints return HTTP 200. The live
  Track Record page shows registered-event scoring and explicitly labeled legacy diagnostics.

All 39 pre-existing local mobile/frontend/document edits are preserved. Two documents
and TrackRecord.tsx were reconciled with incoming changes. Those pre-existing edits
remain local and are not included in the reviewed Phase 3 GitHub commits.
The existing subscription backend remains selected. No analyst call, paid API,
forecast registration, evidence-pack import, brokerage order or new recurring job
was run during deployment. The current research pack remains a separate research
artifact; this operation deploys the code and schema, not an autonomous strategy.

Phase 4 (Jev evaluation) remains paused for the user's next phase approval. The
separate technical Paper008 is already completed and its automation deleted.
Older dated review notes describe their historical undeployed state.

CI: https://github.com/yimngli470-netizen/equity-research-system/actions/runs/45331826329
Local deployment receipts, private-backup metadata and UI proof are in the planning
repository under `research/thesis-led/deployments/2026-11-23/`. Private DB dumps and
credentials are not committed to GitHub.
