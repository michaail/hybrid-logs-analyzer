# Inspect HDFS analysis results Implementation Plan

## Overview

Make completed HDFS analysis runs genuinely inspectable by giving Operators a typed,
project-scoped, paginated result API and a richer results dialog. The change exposes the
block-level evidence already persisted by S-04—without changing HDFS scoring, model loading,
or result production.

## Current State Analysis

S-04 already persists one anomaly row per detected HDFS block with its score, threshold,
level, and at most 20 capped raw source lines. It separately stores aggregate counts for
anomalous and normal blocks. The current `GET .../results` endpoint simply returns every
anomaly as an untyped dictionary; the React dialog displays only the generic record reference,
score, and threshold.

The API already protects results by authorized project membership and returns `404` for foreign
projects. An invalid upload is rejected at dataset admission with `422` and creates neither a
dataset nor an analysis run, so it cannot become a historical result row. S-06, not this
change, owns the unresolved finalized-versus-provisional HDFS block policy.

## Desired End State

An authorized Operator opens a completed run and sees its full run identity, model identifier
and exact version, block-level anomaly scores/thresholds, and expandable bounded source-log
evidence. The Operator can filter by block-ID prefix or minimum score, choose score-descending
or block-ID ordering, and navigate stable pages of results without downloading the entire run.

The result response is explicitly typed in OpenAPI and TypeScript. Its aggregate summary applies
to the entire run, not the current filter/page. It retains normal, rejected, and invalid counts
but does not imply that invalid upload attempts were analysis runs. Access remains strictly
project-scoped, and raw log text is always rendered as escaped text.

### Key Discoveries:

- Frozen inference emits a result for each HDFS `block_id`, classifies with strict
  `score > threshold`, and stores capped source evidence
  (`src/modules/hdfs_inference.py:221-247`, `src/inference_service/runner.py:266-290`).
- The current result endpoint returns an unbounded `list[dict[str, Any]]`, while the repository
  query only orders by score (`src/api/schemas.py:223-227`, `src/api/main.py:599-626`,
  `src/api/storage.py:1030-1038`).
- The existing dialog does not render stored `context.source_lines` or model identity
  (`frontend/src/App.tsx:1489-1563`).
- Runs are already protected by project authorization; the API has regression coverage for
  cross-project result reads (`src/api/main.py:599-626`, `tests/test_api.py:632-651`).
- Dataset rejection occurs at multipart admission before a run exists
  (`src/api/main.py:644-680`, `tests/test_api.py:797-808`).

## What We're NOT Doing

- Altering frozen inference, the decision threshold, anomaly scoring, raw-log admission, model
  package handling, result writers, or notebook-parity behavior.
- Persisting normal, rejected, invalid, or provisional blocks as individual result rows.
- Adding a lifecycle-completeness heuristic, provisional result category/count, or provisional UI;
  S-06 owns FR-012 and US-03.
- Recording historical upload-rejection attempts as analysis outcomes.
- Adding a public result writer, a worker, per-step progress, live streaming, another log source,
  another frontend test runner, or a new model/dataset API.

## Implementation Approach

Extend the existing read-only result route and durable result records. Add a forward-only
migration with portable composite indexes for the two supported keyset orders. The storage
repository owns whitelisted filters, deterministic ordering, and opaque-cursor decoding; the
API owns typed query validation and project-scoped trace composition.

Keep `anomalies` as a list for compatibility, but make each element a closed HDFS result model
with both `block_id` and the compatibility alias `record_reference`. Add only pagination metadata
(`next_cursor` and accepted query details) alongside the existing `run` and whole-run `summary`.
The frontend uses this contract to refetch a page whenever an Operator changes an allowed filter
or order.

## Critical Implementation Details

**Query determinism.** The cursor must bind to the selected sort and filters and contain the
full ordering tuple, including a stable result-row ID. Score order must consistently place legacy
null scores after scored results; a minimum-score filter excludes null scores. Never interpolate
the requested sort or filter values into SQL.

**Evidence display.** Source lines are stored in scoring-sequence (timestamp) order, not source
file order. Show original `line_number` values beside each line and label the stored subset as
such—for example, “showing 20 of 37 scored log lines”—rather than suggesting that all source
lines are present.

**Outcome semantics.** Summary counts are run-wide even when the displayed anomalies are
filtered. For successful S-04 runs, rejected/invalid values remain zero because malformed uploads
fail before a run exists. The UI must make that distinction explicit and must not fabricate
historical rejection totals.

## Phase 1: Establish the typed, paginated result contract

### Overview

Make the existing read path explicit, safe, and bounded while preserving result storage and
project authorization. Normalize the change identifier to the roadmap's S-05 ID as part of this
phase's change-management work.

### Changes Required:

#### 1. Canonical change and roadmap identity

**Files**: `context/changes/cinspect-hdfs-analysis-results/` (remove),
`context/changes/inspect-hdfs-analysis-results/`, `context/foundation/roadmap.md`

**Intent**: Correct the accidental leading `c` in the unplanned change ID so the plan and
roadmap describe one traceable S-05 slice.

**Contract**: Retain a single change folder whose `change_id` is
`inspect-hdfs-analysis-results`; set its status to `planned`. Mark the exact S-05 roadmap row
and body status as `planning` without changing any other roadmap item.

#### 2. Closed result and query schemas

**File**: `src/api/schemas.py`

**Intent**: Replace generic result dictionaries with documented HDFS result, source-context,
summary, traceability, filter, and cursor-page contracts.

**Contract**: Keep the existing `AnalysisResultsResponse.run` and `summary` concepts, but type
the summary's four non-negative run-wide counts; add a trace record with model identifier,
exact version, model-version UUID, pipeline-run ID, dataset checksum, artifact checksum, and
preprocessing-bundle identity when present. Define anomaly records with `block_id` equal to
the retained `record_reference` alias, nullable legacy score/level/threshold fields, and typed
bounded source context. Define only these query parameters: `limit` (default 50, maximum 100),
`sort` (`score_desc` default or `block_id_asc`), `block_id_prefix`, finite `min_score`, and an
opaque `cursor`; reject unknown or malformed values with FastAPI/Pydantic validation.

#### 3. Keyset repository query and supporting migration

**Files**: `src/api/storage.py`, `src/api/migrations.py`

**Intent**: Return one deterministic page of anomaly rows without materializing an entire
potentially large result set.

**Contract**: Add a repository result-page operation that always scopes by `analysis_run_id`,
applies only parameterized prefix and score filters, fetches `limit + 1` rows, and returns a
validated next cursor only when another row exists. Use `score_desc` ordering of
`(score-is-null, score descending, record_reference ascending, id ascending)` and
`block_id_asc` ordering of `(record_reference ascending, id ascending)`. Add an idempotent,
forward-only `006_result_inspection_indexes` migration with composite indexes supporting those
orders. It must apply on both SQLite and PostgreSQL and must not rewrite prior result data.

#### 4. Project-scoped typed results route

**File**: `src/api/main.py`

**Intent**: Compose the stored run, its same-project model trace, whole-run summary, and one
anomaly page into the public result response.

**Contract**: Extend only
`GET /projects/{project_id}/analysis-runs/{analysis_run_id}/results`; preserve its existing
Operator authorization and foreign-run `404`. Project recognized fields from stored
`context_json` into the safe typed context rather than returning arbitrary JSON. A missing or
legacy context remains readable as empty evidence, while S-04 source context retains its
stored count and source lines. Do not add POST, PATCH, or internal result routes.

### Success Criteria:

#### Automated Verification:

- The `006_result_inspection_indexes` migration is idempotent on SQLite and PostgreSQL, and
  leaves prior run/result records readable.
- Repository tests prove deterministic cursor traversal across equal scores, block-ID ordering,
  null legacy scores, prefix/minimum-score filters, result limits, and malformed or
  query-mismatched cursors.
- API tests prove the closed OpenAPI response/query contract, whole-run summaries with filtered
  anomaly pages, valid same-project reads, `401` unauthenticated reads, and `404` cross-project
  reads.
- `ruff check src/api tests/test_api.py tests/test_migrations.py
  tests/test_shared_state_repository.py`, `mypy`, and the focused pytest files pass.

#### Manual Verification:

- Retrieve consecutive filtered result pages through `/docs` or an authenticated API client and
  verify that equal-score rows neither repeat nor disappear and that result provenance belongs
  to the selected project.

**Implementation Note**: After automated verification passes, pause for confirmation that the
two-page API inspection has succeeded before starting the browser presentation work.

---

## Phase 2: Build the Operator result-inspection experience

### Overview

Use the typed paginated API to turn the existing basic `ResultsDialog` into an effective,
bounded investigation surface without widening the result contract or changing inference.

### Changes Required:

#### 1. Typed client result API

**File**: `frontend/src/api.ts`

**Intent**: Mirror the closed backend result models and expose the allowed query parameters to
the React application.

**Contract**: Replace generic anomaly context with typed HDFS block and source-line records.
Represent model/bundle provenance and result-page metadata explicitly. Change
`getAnalysisResults` to serialize only the supported limit, sort, block-prefix, minimum-score,
and cursor query values; preserve the project/run route and bearer-token handling.

#### 2. Paginated results dialog

**File**: `frontend/src/App.tsx`

**Intent**: Let Operators find and inspect detected HDFS block anomalies while maintaining a
clear distinction between run totals and the current page.

**Contract**: In the dialog, display the full run UUID, model identifier/version, and
model-version UUID by default. Provide expandable provenance for pipeline run, dataset checksum,
model artifact checksum, and preprocessing bundle identifier/version/digest. Add controls for
score-descending or block-ID ordering, block-ID prefix, and minimum score; reset the cursor and
replace the page whenever a filter/order changes. Render previous/next navigation only from
locally held cursor history and `next_cursor`. Label block rows as HDFS blocks, display score
and threshold (or an explicit unavailable value for legacy rows), and use an expandable evidence
section showing escaped raw lines in stored scoring order with their original line numbers.
Show meaningful empty, queued/running, completed-with-no-anomalies, and failed states.

#### 3. Accessible responsive evidence and provenance styling

**File**: `frontend/src/styles.css`

**Intent**: Ensure dense evidence, controls, and technical trace information remain legible in
the existing modal layout on desktop and narrow screens.

**Contract**: Extend the existing dialog and form styles for page controls, filter fields,
details/summary disclosure, long checksums/UUIDs, wrapped raw-log `<pre>` text, and mobile
single-column layouts. Preserve visible keyboard focus and do not rely on color alone to
communicate result/run state.

### Success Criteria:

#### Automated Verification:

- `npm run lint`, `npm run typecheck`, and `npm run build` pass in `frontend/`.
- The frontend compiles against the closed result contract without `Record<string, unknown>`
  result-context access or unsafe raw-HTML rendering.

#### Manual Verification:

- As an Operator, open a completed run with multiple anomalies; verify full run/model identity,
  expandable provenance, scored-order source context, original line numbers, and the stored-line
  count label.
- Change each filter and ordering option, navigate forward/backward, then reset filters; verify
  totals remain run-wide and rows do not repeat or vanish across page boundaries.
- Confirm completed zero-anomaly, in-progress, failed, and narrow-screen dialog states remain
  understandable; confirm upload rejection is still shown at dataset admission rather than as a
  fabricated result row.

**Implementation Note**: After automated verification passes, pause for human confirmation of
the completed-run and edge-state UI checks before finalizing documentation and CI coverage.

---

## Phase 3: Lock in behavior and operating guidance

### Overview

Turn the accepted API and UI behavior into durable regression coverage, include all affected
backend tests in the existing verification job, and document the intended result semantics for
Operators and maintainers.

### Changes Required:

#### 1. Result-contract regression coverage

**Files**: `tests/test_api.py`, `tests/test_shared_state_repository.py`,
`tests/test_migrations.py`

**Intent**: Cover the result-read behavior with seeded durable rows, independent of the
ML-marked inference runtime.

**Contract**: Seed completed same-project runs and anomaly rows through `ApiDatabase`; verify
the exact typed source context, `block_id`/`record_reference` equality, model trace, summary,
cursor/filter semantics, empty states, and authorization boundaries. Retain the S-04 golden
inference tests as the proof that production scoring produces the stored source evidence; do not
duplicate ML scoring in API tests.

#### 2. Existing CI inclusion

**File**: `.github/workflows/verify.yml`

**Intent**: Ensure the migration and repository tests that protect result paging run in the
existing API verification job.

**Contract**: Extend the existing Python test command to include the relevant non-ML migration
and shared-state repository test files. Do not add a new CI provider, test runner, or inference
workload to the API job.

#### 3. Result-inspection operating documentation

**File**: `README.md`

**Intent**: Describe what Operators can inspect and preserve the established boundaries between
accepted runs, upload-time rejection, and later provisional results.

**Contract**: Document HDFS-block result fields, bounded stored context, score/block-ID query
controls, whole-run summary semantics, project isolation, and the separate S-06 completeness
work. State that result paging does not re-score or expose model artifacts and that rejected
uploads return a validation report before an analysis run exists.

### Success Criteria:

#### Automated Verification:

- Focused API, migration, and repository tests cover result traces, safe context projection,
  keyset cursor error paths, equal-score stability, null-score ordering, filter boundaries, and
  project isolation.
- The existing API CI job runs every affected non-ML result, migration, and repository test;
  the frontend build job remains green.
- `python -m pytest` and `ruff check src tests scripts run_ablation.py` pass in a normal local
  terminal; `mypy` passes with the configured Pydantic plugin.

#### Manual Verification:

- Review the README and live result dialog against a known completed HDFS run; confirm it
  describes only finalized anomaly inspection and does not imply that every uploaded block is
  lifecycle-complete.
- Confirm a user authorized only for another project cannot view the run, page cursors, context,
  or provenance of this project's results.

**Implementation Note**: After all automated checks pass, pause for final human confirmation of
the documentation, project-isolation behavior, and manual UI checks before archiving the change.

## Testing Strategy

### Unit Tests:

- Cursor encode/decode validation, tie-break ordering, filter/cursor binding, null-score ordering,
  and `limit + 1` next-page detection in the storage layer.
- Pydantic response/query validation, including finite minimum scores and bounded page sizes.
- Safe conversion of stored context to `matched_line_count` and capped source-line models.

### Integration Tests:

- A seeded completed run returns model/version traceability, run-wide summary, typed HDFS
  anomalies, and one bounded page through the public API.
- Prefix and minimum-score filters preserve the full summary while selecting only matching rows.
- Unauthorized and cross-project reads, including attempts to reuse a valid cursor, do not reveal
  another project's result data.
- Migration application remains idempotent on SQLite and the optional PostgreSQL harness.

### Manual Testing Steps:

1. Start the existing API and React client with a completed HDFS run containing enough anomalies
   to span two pages.
2. Open **View outcome** and verify full identity, model trace, block labels, and expandable
   source evidence against known stored lines.
3. Filter by a known block prefix and a score boundary; change ordering; move through pages; then
   reset controls and verify the original first page returns.
4. Check a no-anomaly completed run, an in-progress run, and a failed run; submit an invalid log
   and verify its `422` admission report is still separate from analysis results.
5. Repeat the results URL/API call as a user from another project and verify it remains `404`.

## Performance Considerations

The existing limit of 25,000 scored blocks means an unpaged anomaly response could include up to
250 million raw characters before JSON overhead. The 50-row default bounds a worst-case context
page to roughly 500,000 raw characters; the hard limit of 100 bounds it to roughly one million.

Keyset pages avoid progressively scanning all prior rows. The forward composite indexes support
the two intentionally small sort choices. Do not add normal-result storage or client-side
filtering of an unbounded response.

## Migration Notes

Add migration `006_result_inspection_indexes` after `005_preprocessing_bundles`. It creates
indexes only, is recorded through the existing migration mechanism, and never updates or deletes
rows. Apply it forward on SQLite and PostgreSQL; do not attempt destructive rollback. Existing
rows with null score/context fields remain readable under the typed projection and deterministic
legacy-order rule.

## References

- Product requirements: `context/foundation/prd.md` — US-02, FR-007, FR-008
- Roadmap slice: `context/foundation/roadmap.md` — S-05
- S-04 storage boundary: `context/archive/2026-09-11-run-parity-hdfs-analysis/plan.md:30-38`
- HDFS result construction: `src/inference_service/runner.py:242-290`
- Result endpoint and response mapping: `src/api/main.py:599-626`, `src/api/main.py:891-898`
- Current API schema and storage query: `src/api/schemas.py:204-227`,
  `src/api/storage.py:950-1038`
- Current result dialog and styling: `frontend/src/App.tsx:1489-1563`,
  `frontend/src/styles.css:900-1096`
- Existing isolation and queued-result tests: `tests/test_api.py:480-651`,
  `tests/test_api.py:1388-1440`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `.cursor/skills/10x-plan/references/progress-format.md`.

### Phase 1: Establish the typed, paginated result contract

#### Automated

- [ ] 1.1 Apply and verify the forward-only result-inspection index migration
- [ ] 1.2 Cover deterministic repository paging, filtering, and cursor validation
- [ ] 1.3 Cover typed result API contracts, summaries, and authorization
- [ ] 1.4 Run focused Python linting, type checking, and tests

#### Manual

- [ ] 1.5 Inspect consecutive filtered API result pages and project-scoped provenance

### Phase 2: Build the Operator result-inspection experience

#### Automated

- [ ] 2.1 Pass frontend linting, TypeScript checking, and production build
- [ ] 2.2 Compile the dialog against typed result context without unsafe raw HTML

#### Manual

- [ ] 2.3 Verify completed-run identity, provenance, scored context, and source-line labels
- [ ] 2.4 Verify filters, ordering, pagination, empty, in-progress, failed, and responsive states

### Phase 3: Lock in behavior and operating guidance

#### Automated

- [ ] 3.1 Cover result traces, safe context, paging edge cases, migration, and isolation
- [ ] 3.2 Include affected non-ML result tests in the existing CI verification job
- [ ] 3.3 Pass the full local Python verification suite, Ruff, and mypy

#### Manual

- [ ] 3.4 Review result-inspection documentation against a completed HDFS run
- [ ] 3.5 Confirm project isolation for results, cursors, context, and provenance
