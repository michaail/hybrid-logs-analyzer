# Separate Provisional HDFS Results Implementation Plan

## Overview

Separate HDFS block histories that are not included in a pinned F-03 evaluation-data
reference catalog from results that the model can score. The public result semantics will be
explicitly heuristic: catalog membership makes a block **heuristically final**, not proven
lifecycle-complete. All other block histories are stored and displayed as provisional, with
bounded source context and a stable explanation, and never contribute to anomaly or normal
counts.

## Current State Analysis

The frozen inference path annotates a complete admitted log, groups every line that has a
`block_id`, builds a graph for every grouped block, and classifies every score as anomaly or
normal. The private runner persists only anomaly rows; normal counts are derived from the
number of all scored blocks. Matched lines with no `block_id` are silently dropped by the
HDFS sequencer.

F-03 produces a checksum-bound, ignored workspace artifact containing an evaluation
`manifest.json` and `selected-block-ids.txt`. It proves that selected lines were retained
within a source corpus, but it does not prove that arbitrary uploaded block lifecycles ended.
The chosen product policy deliberately uses its selected-ID membership only as a heuristic.

## Desired End State

For each completed HDFS run, the private service loads the explicitly configured and
checksum-pinned F-03 catalog revision. A block whose identifier appears in that catalog is
scored and contributes to the existing anomaly or normal count; the response and UI label
those outcomes **heuristically final**. A block absent from the catalog is stored as
provisional with `not_in_reference_catalog`, has no model score or threshold, and is
retrievable through a separately paginated project-scoped endpoint. Parser-matched lines
without a block identifier are visible as an unassigned-context count rather than being
silently discarded.

### Key Discoveries

- `src/modules/hdfs_inference.py:104-248` annotates, sequences, graphs, and scores every
  block in one function; selecting eligible blocks must happen before `build_pyg_dataset` to
  honor the no-score rule for provisional histories.
- `src/modules/sequencer.py:115-126` drops rows with no `block_id`, so the pipeline already
  has the raw information needed to report an unassigned count before sequencing.
- `src/modules/hdfs_evaluation_data.py:76-100, 400-450` defines the checksum-bearing F-03
  manifest and publishes it atomically in the ignored workspace; it is the catalog source,
  not a runtime search target.
- `src/api/storage.py:940-1009` commits the completed run and replaces anomaly rows in the
  same transaction. Provisional row replacement must join that transaction.
- `src/api/storage.py:1066-1104` and `src/api/main.py:606-649` establish the existing
  project-scoped, keyset-paginated result pattern.
- `frontend/src/App.tsx:1493-1854` already has a result dialog, server paging state, a
  provenance disclosure, and an outcome summary to extend.

## What We're NOT Doing

- Claiming that block-ID catalog membership proves an HDFS lifecycle completed, or retaining
  the unqualified `finalized` label for such results.
- Selecting the newest evaluation artifact, discovering artifacts from notebook state, or
  accepting an Operator-supplied completion declaration at runtime.
- Using lifecycle-event detection, inactivity watermarks, backfilling missing events, or
  scoring provisional histories.
- Reclassifying completed historical runs; their new provisional and unassigned counts remain
  zero and their existing anomaly rows remain untouched.
- Adding another log source, model-training workflow, catalog-management UI, or public route
  that mutates analysis results.

## Implementation Approach

Use F-03's `selected-block-ids.txt` as a deployment-provisioned reference set, not as evidence
of HDFS lifecycle termination. The inference service receives the absolute manifest path and
an expected SHA-256 together, validates the manifest and its sibling selected-ID file at run
time, records the resolved policy version and catalog digest on the completed run, then
splits HDFS sequences before graph creation. The existing anomaly table/API remains
anomaly-only. A new provisional table and endpoint use bounded block-ID keyset pagination,
while the existing result summary gains aggregate provisional and unassigned-context counts.

## Critical Implementation Details

The configured catalog must be treated as an immutable deployment input. The service verifies
its configured manifest SHA-256 and the selected-ID checksum already declared in that manifest
for every run; it must not cache by a mutable “latest” alias or expose the filesystem path to
Operators.

Classify after strict Drain annotation but before graph construction. This preserves current
whole-run failures for unmatched templates and missing embeddings in the scored subset while
preventing PyTorch work and score persistence for provisional blocks.

## Phase 1: Establish the Honest Heuristic and Pinned Catalog Contract

### Overview

Amend the product/documentation language from deterministic lifecycle completeness to a
traceable reference-membership heuristic, then add a typed loader for the F-03 catalog and
its required inference-service configuration.

### Changes Required

#### 1. Product, roadmap, and operational documentation

**Files**: `context/foundation/prd.md`, `context/foundation/roadmap.md`, `README.md`,
`.env.example`

**Intent**: Replace the unresolved completeness-evidence requirement with the explicitly
chosen `heuristically final` versus `provisional` contract. Document that selected-ID
membership is useful triage evidence but not proof of an HDFS lifecycle boundary, and show how
an operator/deployer pins the generated F-03 manifest without committing it.

**Contract**:

- Amend US-03 and FR-012 so a documented deterministic *reference-membership heuristic*
  controls result separation; anomaly and normal outcomes are labelled “heuristically final.”
- Resolve PRD question 5 and roadmap question 6 with this policy, update S-06's outcome/risk
  wording, and leave F-03's own within-corpus guarantee intact.
- Add `INFERENCE_HDFS_COMPLETENESS_MANIFEST` and
  `INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256` as an all-or-nothing private-service pair.
  The documented path is the ignored F-03 artifact `manifest.json`; its SHA-256 is calculated
  during deployment and is not stored in Git.
- Preserve the existing rule that a missing or mismatched catalog is a failed inference run,
  not an all-provisional run.

#### 2. Reusable reference-catalog contract

**Files**: `src/modules/hdfs_completeness.py`, `src/modules/hdfs_evaluation_data.py`,
`tests/test_hdfs_completeness.py`

**Intent**: Keep catalog parsing and validation in reusable non-web code, reusing F-03's closed
Pydantic manifest and selected-ID validation instead of duplicating an ad hoc file format in
the service.

**Contract**:

- Define a typed, immutable reference-catalog record with a policy identifier
  `hdfs_reference_membership_v1`, the manifest digest, its corpus/selected-ID provenance, and
  a `frozenset[str]` of selected block IDs.
- Load an exact manifest path; require it to be a regular readable file; compare its SHA-256
  with the configured expected digest; validate it as `EvaluationDataManifest`; require the
  sibling `selected-block-ids.txt`; and verify both its content digest and ordered-ID digest
  against the manifest before returning the set.
- Reject empty, duplicate, malformed, missing, or checksum-mismatched catalog artifacts with
  a typed error that contains no host path or object-store credential in its public message.
- Add dependency-light tests for valid loading, changed manifest bytes, changed selected-ID
  bytes, duplicate IDs, and a missing sibling file.

#### 3. Inference settings and safe terminal error

**Files**: `src/inference_service/settings.py`, `src/inference_service/errors.py`,
`tests/test_inference_service.py`

**Intent**: Make the catalog a mandatory, explicit inference input and turn a bad deployment
catalog into a recognizable terminal failure without leaking its location.

**Contract**:

- Extend `InferenceSettings` and `from_environment()` to require and validate the two catalog
  settings together. Test constructors supply a temporary catalog explicitly.
- Add a stable `COMPLETENESS_CATALOG_UNAVAILABLE` safe error message, mapping all catalog
  validation/load failures to it while retaining only a private cause in service logs.
- Do not add these settings to the public API process, the frontend build, or model packages.

### Success Criteria

#### Automated Verification

- The catalog loader accepts a valid F-03 manifest/ID pair and rejects each integrity failure.
- Inference settings reject a missing half of the required configuration pair.
- `ruff check src tests scripts run_ablation.py` passes.
- `mypy` passes.

#### Manual Verification

- A deployer can build an F-03 artifact, calculate the manifest SHA-256, configure the two
  private-service variables, and confirm no generated artifact is tracked by Git.
- Documentation makes clear that “heuristically final” is not lifecycle-completeness proof.

**Implementation Note**: Pause after automated verification for human confirmation that the
documentation accurately communicates the heuristic before modifying runtime outcomes.

---

## Phase 2: Persist Provisional Histories and Run-Level Classification Provenance

### Overview

Add an additive database migration and repository methods that store provisional context
separately, keep result writes atomic, and expose all run-wide classification metadata without
breaking existing completed-run JSON.

### Changes Required

#### 1. Additive migration and schema checks

**Files**: `src/api/migrations.py`, `tests/test_migrations.py`

**Intent**: Create the durable outcome boundary without rebuilding existing result tables or
altering historical rows.

**Contract**:

- Add migration `008_provisional_hdfs_results` after the result-inspection migrations for both
  SQLite and PostgreSQL.
- Create `provisional_results` with a UUID primary key, `analysis_run_id` foreign key,
  `record_reference`, stable `reason_code`, and `context_json`; enforce one row per
  `(analysis_run_id, record_reference)`.
- Add a bounded block-ID keyset index
  `(analysis_run_id, record_reference, id)` for provisional paging.
- Add `provisional_count`, `unassigned_context_line_count`, `classification_policy`, and
  `classification_catalog_sha256` columns to `analysis_runs`. Counts default to zero and are
  non-negative; policy/catalog fields are nullable so historical runs remain readable.
- Preserve `results_summary_json` as the existing four finalized counts. This permits an
  older server to read a new completed run during a code rollback instead of failing on an
  unexpected JSON field.
- Prove fresh install, repeated application, SQLite upgrade, and PostgreSQL-marked application
  keep existing run/anomaly records and add the new table, columns, constraints, and index.

#### 2. Atomic storage methods and independent provisional pagination

**Files**: `src/api/storage.py`, `tests/test_migrations.py`, `tests/test_api.py`

**Intent**: Extend the completed-run transaction so no state can expose a completed result
summary without its matching anomaly/provisional rows, and reuse safe keyset mechanics without
allowing cursor types to cross.

**Contract**:

- Extend the completed transition payload with provisional rows, the two counts, and policy
  provenance. Delete/replace anomaly and provisional rows only inside the successful
  `running → completed` transaction.
- Add a typed provisional page query/result with `limit` (1–100), literal `block_id_prefix`,
  `cursor`, and only `block_id_asc` ordering; omit score and minimum-score controls.
- Encode a result-kind discriminator in provisional cursors (or use a distinct strict cursor
  schema) so anomaly cursors, different-run cursors, filters, malformed IDs, and foreign
  project access all fail rather than returning a shifted page.
- Persist only server-generated `not_in_reference_catalog` reason text/code and bounded
  source evidence. Never persist a provisional score, threshold, or client-controlled
  explanation.

#### 3. Typed public models

**Files**: `src/api/schemas.py`

**Intent**: Make the distinction unambiguous in OpenAPI and prevent presentation layers from
mistaking a provisional record for a scored anomaly.

**Contract**:

- Add `provisional_count` and `unassigned_context_line_count` to
  `AnalysisResultSummary`; queued, failed, rejected, and historical runs serialize both as
  zero.
- Extend `AnalysisResultTrace` with nullable classification policy and catalog SHA-256.
- Define distinct Pydantic models for a provisional record, context, query, and page response.
  A provisional record contains `block_id`, `record_reference`, `reason_code`, safe
  `reason`, and `context`, but no anomaly score, level, or decision threshold.

### Success Criteria

#### Automated Verification

- The new migration is idempotent on SQLite and PostgreSQL and preserves pre-008 results.
- A forced insert/audit failure rolls back the completed run transition and both result tables.
- Provisional paging honors literal prefixes and rejects malformed, mismatched, and
  anomaly-issued cursors.
- Typed schema validation rejects provisional score/threshold fields and invalid negative
  counts.

#### Manual Verification

- Inspect a migrated local database and confirm historical completed runs show zero
  provisional/unassigned counts without recreated rows.
- Confirm a provisional row includes bounded log context and a reason but no score columns.

**Implementation Note**: Pause after applying the migration locally; do not deploy inference
code that writes provisional rows until this migration is available to both service processes.

---

## Phase 3: Split Block Histories Before Graph Scoring

### Overview

Load the pinned catalog within the isolated service, count parser-matched unassigned lines, and
send only heuristic-membership blocks to graph construction and PyTorch scoring.

### Changes Required

#### 1. Frozen HDFS inference composition

**Files**: `src/modules/hdfs_inference.py`, `tests/test_hdfs_inference_parity.py`

**Intent**: Preserve the frozen parser/model composition and existing direct parity behavior
while supporting a caller-supplied set of block IDs that may be scored.

**Contract**:

- Extend the inference result with explicit unscored provisional block snapshots and the count
  of annotated rows whose `block_id` is null. Reuse existing context limits
  (`MAX_CONTEXT_LINES`, `MAX_RAW_CHARS`) for both anomaly and provisional evidence.
- Accept an optional scoring-ID set. `None` preserves the current all-block scoring behavior
  for notebook/parity callers; the private service must always provide the pinned catalog set.
- After strict annotation, calculate unassigned-context count, build all HDFS sequences, split
  them by ID membership, build graphs only for the selected sequences, and never instantiate a
  score/decision/threshold for the other set.
- Preserve existing block identity (first `blk_*` match), existing sequence ordering, parser
  failure behavior, block/source limits, and golden fixture behavior when no set is supplied.
- Add ML-marked coverage for a mixed log: a catalog ID is scored and produces the existing
  decision contract; a noncatalog ID retains context only; a matched line without an ID
  increments the separate count; no graph is built for the provisional history.

#### 2. Private runner integration

**Files**: `src/inference_service/runner.py`, `src/inference_service/errors.py`,
`tests/test_inference_service.py`

**Intent**: Bind the catalog atomically to one run, translate the split result into the two
database collections, and retain completed-run provenance.

**Contract**:

- Materialize and validate the configured catalog before model graph scoring. A catalog failure
  transitions the run to `failed` with `COMPLETENESS_CATALOG_UNAVAILABLE` and leaves both
  result tables empty.
- Pass catalog IDs into frozen inference; construct anomaly rows from only scored positive
  decisions; calculate normal count from scored negative decisions; construct one
  `not_in_reference_catalog` provisional row per unselected sequence; and set the two new
  aggregate counts.
- Save `hdfs_reference_membership_v1` and the catalog manifest SHA-256 as run provenance in
  the same transition that replaces result rows.
- A run with no catalog matches is a successful completed run with zero heuristic anomaly/normal
  outcomes and all grouped blocks provisional. A run containing only matched no-ID lines also
  completes with zero block outcomes and a positive unassigned-context count.

### Success Criteria

#### Automated Verification

- Existing frozen golden parity tests still pass when no scoring-ID set is passed.
- The real ML-marked internal execution path completes a mixed run with mutually exclusive
  anomaly/normal/provisional counts and no persisted scores for provisional rows.
- Missing, altered, or malformed catalog configuration fails before model scoring and persists
  no partial rows.
- Existing unmatched-template and missing-embedding terminal-failure tests still leave both
  result tables empty.

#### Manual Verification

- Execute a mixed fixture through the private service and inspect its database records: only
  catalog IDs have scores, and every other block has a contextual provisional explanation.
- Verify the logged private cause is useful to an operator while the public error reveals no
  catalog filesystem path.

**Implementation Note**: Keep the catalog loader and selection code outside the public API
package; the public process must remain unable to import the private inference runtime.

---

## Phase 4: Expose Project-Scoped Provisional Inspection and the Results Panel

### Overview

Publish a separate authenticated provisional-results read path and make the existing results
dialog distinguish heuristic outcomes, provisional context, and unassigned log context.

### Changes Required

#### 1. Result routes and API contract mapping

**Files**: `src/api/main.py`, `src/api/schemas.py`, `tests/test_api.py`

**Intent**: Preserve the anomaly-only endpoint while adding a focused read-only route for
provisional inspection under exactly the same project/role boundary.

**Contract**:

- Keep `GET .../results` anomaly-only. Its summary now includes provisional/unassigned counts,
  and its trace exposes the recorded heuristic policy/catalog digest after completion.
- Add `GET /projects/{project_id}/analysis-runs/{analysis_run_id}/provisional-results` with
  `operator` authorization, project/run/model existence checks, the provisional page query,
  and a distinct typed response.
- Return 404 for any run/cursor requested outside the caller's authorized project, 401 when
  unauthenticated, 422 for invalid controls/cursors, and an empty page for noncompleted,
  failed, rejected, or historical runs.
- Map `not_in_reference_catalog` to safe server-owned copy such as “This block is not in the
  pinned reference catalog, so its anomaly decision is provisional.” Do not derive a score or
  threshold in the response.
- Update OpenAPI assertions to require the new GET-only path, fields, and no score-filter
  parameter on provisional paging.

#### 2. TypeScript API client and results dialog

**Files**: `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/styles.css`

**Intent**: Give Operators a clear, scalable inspection flow without mixing non-final
histories into the anomaly list or implying their model score exists.

**Contract**:

- Add matching TypeScript types and a client/path helper for the separate provisional route;
  its query is block-ID pagination only.
- Update the summary grid to show **Heuristically final anomalies**, **Heuristically final
  normal**, **Provisional histories**, and **Unassigned context lines**, while retaining
  rejected/invalid admission metrics. On narrow screens, preserve readable grid wrapping.
- Add an always-visible explanation that heuristic-final outcomes are based on membership in
  the pinned reference catalog and are not proof that the source lifecycle ended. Include
  policy/digest in the existing provenance disclosure when present.
- Add a “Review N provisional histories” CTA only when the count is positive. It opens a
  separate panel/tab with independent loading, previous/next cursors, literal block-prefix
  filtering, source evidence disclosure, reason code/copy, and no score or threshold.
- Reset only provisional paging when its own filter changes; keep anomaly paging/filter state
  intact when users switch the panel. Preserve current loading/error/401 handling.

### Success Criteria

#### Automated Verification

- API tests verify mixed summaries, separate provisional pages, no score fields, empty pending
  states, cross-project 404s, and OpenAPI query/response contracts.
- `npm --prefix frontend run lint` passes.
- `npm --prefix frontend run typecheck` passes.
- `npm --prefix frontend run build` passes.

#### Manual Verification

- An Operator opens a mixed completed run, sees provisional count separate from anomaly/normal
  totals, opens the provisional panel, pages it, and sees no score displayed.
- An all-provisional run is communicated as completed rather than failed; an all-unassigned
  run visibly reports its unassigned-context count.
- A project member from another project cannot retrieve either page by changing IDs or reusing
  a cursor.

**Implementation Note**: Do not fold provisional records into the existing `anomalies` array
or apply score controls to the provisional panel; their distinct type is the guard against
accidentally treating a heuristic as a model decision.

---

## Phase 5: Prove Regression Safety and Document Deployment/Rollback

### Overview

Exercise the feature at the real private-service boundary, preserve model-parity guarantees,
and provide an operationally safe rollout sequence for the additive schema.

### Changes Required

#### 1. Cross-boundary integration and regression coverage

**Files**: `tests/test_inference_service.py`, `tests/test_api.py`,
`tests/test_hdfs_inference_parity.py`, `README.md`

**Intent**: Ensure this change is validated through the process that actually starts the
private inference service, rather than only through mocked API/runner calls.

**Contract**:

- Add an `@pytest.mark.ml` integration test that launches `python -m src.inference_service`
  in an isolated temporary environment with a free port, shared disposable database/object
  store, internal token, and pinned catalog variables; wait for `/health`, execute a queued
  mixed run over HTTP, then assert durable split results. Ensure robust process termination and
  capture output on failure.
- Keep the existing direct service tests as fast contract coverage, but treat the subprocess
  test as the wiring proof required for model/inference boundaries.
- Test the smallest counterexamples: an approved-ID truncated history is still labelled only
  heuristically final; a noncatalog block is provisional; a line without an ID has no invented
  owner; same IDs in another project remain inaccessible; a cursor from anomaly results cannot
  enter provisional paging.
- Update README runbook instructions with the pinned catalog preparation, result meanings,
  endpoint behavior, no-score guarantee, and commands that must run outside Cursor's
  restricted native-library sandbox.

#### 2. Rollout and rollback constraints

**Files**: `README.md`, `context/foundation/roadmap.md`

**Intent**: Make deployment ordering explicit and keep the roadmap aligned with the amended
heuristic rather than a claim of solved lifecycle completeness.

**Contract**:

- Roll out in this order: generate/retain the F-03 artifact outside Git and record its SHA-256;
  apply migration 008; configure and deploy the private inference service; deploy API; deploy
  frontend. Verify the catalog before enabling queued work.
- Code rollback never drops the additive table/index/columns. Retain the pinned artifact and
  its digest for every completed run; an old API remains able to read the unchanged four-field
  `results_summary_json`.
- Mark roadmap S-06 planning artifacts with the agreed heuristic language and retain a visible
  residual risk that block-ID membership can falsely classify a truncated known ID; it is a
  consciously accepted product limitation, not a hidden implementation defect.

### Success Criteria

#### Automated Verification

- `python -m pytest` passes in a normal local ML environment.
- `python -m pytest -m ml` passes in a normal local ML environment, including the real
  isolated-service subprocess test.
- `ruff check src tests scripts run_ablation.py` and `mypy` pass.
- `npm --prefix frontend run lint`, `npm --prefix frontend run typecheck`, and
  `npm --prefix frontend run build` pass.

#### Manual Verification

- Follow the documented deployment sequence against a disposable database and confirm an
  existing completed run still opens after migration.
- Verify the pinned catalog digest shown in the UI matches the provisioned artifact and a
  changed catalog file fails a new run rather than changing its classification.
- Run the notebook/parity release check with no scoring-ID selector and confirm metrics remain
  within the agreed one-percentage-point baseline tolerance.

**Implementation Note**: Native NumPy/Torch failures under Cursor's restricted sandbox are
environment failures, not test evidence. Record them separately and complete ML verification in
a normal local terminal.

## Testing Strategy

### Unit Tests

- Catalog integrity: path, manifest digest, selected-ID digest/order, duplicate and empty IDs.
- Result persistence: additive migration, nonnegative counts, atomic replacement, cursor
  discriminator, literal prefix escaping, and historical defaults.
- Inference split: catalog-member scoring, nonmember provisional snapshots, unassigned count,
  and no graph/scoring call for provisional sequences.
- Typed contracts: no provisional score/threshold and safe reason-code mapping.

### Integration Tests

- Private service executes an actual mixed queued run in a subprocess using explicit temporary
  configuration and writes mutually exclusive scored/provisional records.
- Public API exposes separate, project-isolated anomaly and provisional pages with independent
  cursors and complete run-wide summaries.
- Existing golden inference/parity path remains unchanged when the optional scoring-ID
  selection is omitted.

### Manual Testing Steps

1. Build an F-03 artifact in an ignored workspace and pin its manifest SHA-256 in the private
   service configuration.
2. Analyze a log with one selected ID, one unselected ID, and one parser-matched line without
   an ID.
3. Confirm the main outcome shows heuristic anomaly/normal counts separately from provisional
   and unassigned counts, then page the provisional panel and inspect bounded source context.
4. Alter the configured catalog after starting a fresh run and verify the run fails safely
   instead of silently using different reference membership.

## Performance Considerations

The pipeline already caps an admitted run at 100,000 non-empty lines and 25,000 HDFS blocks.
Load the selected-ID catalog as a set and use constant-time membership before graph construction;
this reduces ML work for provisional blocks. Provisional records reuse the bounded source
context and a block-ID index, and their independent page maximum remains 100. Do not add
score-based sorting or server-side full-text search for provisional histories.

## Migration Notes

Migration 008 is additive: it creates `provisional_results` and adds defaulted metadata/count
columns to `analysis_runs`. It must run before a new inference worker writes the split outcome.
No backfill occurs; pre-S-06 runs retain their original finalized counts and expose zero
provisional/unassigned counts. Because finalized count JSON is kept unchanged, a rollback can
leave the additive schema in place without causing pre-S-06 API schemas to reject new summary
keys.

## References

- Product requirement and amended policy target: `context/foundation/prd.md:35-39, 95-105,
  131-134, 169-175, 213-217`
- F-03 catalog artifact: `src/modules/hdfs_evaluation_data.py:76-100, 400-450`
- Current all-block inference: `src/modules/hdfs_inference.py:104-248`
- Current result persistence and paging: `src/api/storage.py:940-1009, 1066-1104`
- Existing result route: `src/api/main.py:606-649`
- Existing frontend dialog: `frontend/src/App.tsx:1493-1854`
- ML subprocess lesson: `context/foundation/lessons.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands.
> Do not rename step titles.

### Phase 1: Establish the Honest Heuristic and Pinned Catalog Contract

#### Automated

- [ ] 1.1 Catalog loader accepts valid F-03 artifacts and rejects integrity failures
- [ ] 1.2 Inference settings reject incomplete catalog configuration
- [ ] 1.3 Ruff and mypy pass

#### Manual

- [ ] 1.4 Pinned catalog artifact is deployed outside Git
- [ ] 1.5 Documentation communicates heuristic limitations

### Phase 2: Persist Provisional Histories and Run-Level Classification Provenance

#### Automated

- [ ] 2.1 Migration preserves existing rows and applies idempotently on supported databases
- [ ] 2.2 Completed-result transaction rolls back both result kinds on failure
- [ ] 2.3 Provisional paging validates prefixes and cursor kind
- [ ] 2.4 Typed schemas reject invalid provisional result fields and counts

#### Manual

- [ ] 2.5 Historical runs expose zero new counts after migration
- [ ] 2.6 Stored provisional rows contain context and no score

### Phase 3: Split Block Histories Before Graph Scoring

#### Automated

- [ ] 3.1 Golden parity remains unchanged without a scoring-ID selector
- [ ] 3.2 Mixed ML execution persists exclusive heuristic and provisional outcomes
- [ ] 3.3 Invalid catalog configuration fails without partial results
- [ ] 3.4 Existing terminal failures leave both result tables empty

#### Manual

- [ ] 3.5 Mixed private-service execution stores only scores for catalog IDs
- [ ] 3.6 Catalog errors preserve a safe public message

### Phase 4: Expose Project-Scoped Provisional Inspection and the Results Panel

#### Automated

- [ ] 4.1 API/OpenAPI tests cover provisional route, summaries, cursor validation, and isolation
- [ ] 4.2 Frontend lint, typecheck, and build pass

#### Manual

- [ ] 4.3 Operator reviews and pages provisional histories without scores
- [ ] 4.4 All-provisional and all-unassigned completed states are clear
- [ ] 4.5 Cross-project access to either result page is denied

### Phase 5: Prove Regression Safety and Document Deployment/Rollback

#### Automated

- [ ] 5.1 Real private-service ML subprocess test passes
- [ ] 5.2 Full Python, ML, Ruff, mypy, and frontend checks pass

#### Manual

- [ ] 5.3 Disposable migration rollout preserves an existing run
- [ ] 5.4 Catalog digest is traceable and altered catalog fails safely
- [ ] 5.5 Notebook/parity release check remains within the agreed tolerance
