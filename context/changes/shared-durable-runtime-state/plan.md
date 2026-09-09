# Shared durable runtime state Implementation Plan

## Overview

Give deployed model, dataset, run, and result records a shared PostgreSQL-ready
ownership and version contract so later publication, intake, inference, and inspection
slices can coordinate without a local workspace filesystem. This foundation adds the
schema, repository, and additive HTTP reads; it does not upload bytes, attach Railway
Bucket credentials, or run inference.

## Current State Analysis

The FastAPI control plane already persists project-scoped `model_versions` and
`analysis_runs` through `ApiDatabase`, which speaks SQLite locally and PostgreSQL on
Railway. Identity work in S-01 already occupies `001_initial_schema`. Those product
rows still point at trusted-workspace path strings, there is no `datasets` table,
`anomaly_results` is never written, and GET `/results` computes an ephemeral summary
from an empty list.

Valid analysis requests still terminate as `not_supported`. `queued` exists on the
enum but is never stored. Model register, publish, and run create commit the domain
row, then open a second transaction for audit — unlike S-01 account mutations.
Tests exercise SQLite only. No Bucket/S3 adapter exists, which matches the walking
skeleton: Railway Bucket credentials stay unattached until a later slice.

## Desired End State

A migrated SQLite or PostgreSQL database stores HDFS model versions, datasets, analysis
runs, anomaly rows, and result summaries with project ownership, kinded byte pointers
(`workspace` | `object`), and checksums required only for `object` kind. Analysis runs
accept the expanded status vocabulary, but the public HTTP API still writes only
`rejected` and `not_supported`. Dataset identity is `(project_id, storage_kind,
object_reference)`. Operators can list and get datasets in a project. GET results
returns the stored summary. Repository methods persist audit events atomically and
apply compare-and-swap status transitions. There is no public HTTP writer for results
or non-terminal statuses. A dataset is an accepted reusable source: rejected
pre-validation or malformed-input attempts retain their validation run with
`dataset_id = null`, and never appear in dataset reads. A local Docker PostgreSQL
harness exists for dialect tests.

### Key Discoveries:

- Dual-dialect persistence and Railway `DATABASE_URL` already exist:
  `src/api/storage.py:46-102`, `.railway/railway.ts:8-18`.
- Model uniqueness and project isolation already hold:
  `src/api/migrations.py:40-56`, `src/api/main.py:435-437`.
- Pointers are workspace paths, not object keys or checksums:
  `src/api/migrations.py:48,65`, `src/api/validation.py:61-69`.
- `anomaly_results` is schema-only (`src/api/storage.py:552-560`); summaries are
  computed in `src/api/main.py:601-612`.
- SQLite cannot ALTER a CHECK constraint, so expanding `analysis_runs.status` requires
  a table rebuild in `002`, not an in-place CHECK edit.
- S-01 forbids rewriting identity columns in `001`; F-01 must be additive:
  `context/changes/provision-project-accounts/plan.md` migration notes.
- Deploy-plan still defers Bucket credentials:
  `context/deployment/deploy-plan.md:23-26,56-63`.

## What We're NOT Doing

- Railway Bucket client, presigned URLs, boto/S3 SDK, or attaching Bucket credentials
  to `web`.
- Browser or API multipart upload of models or logs (S-02 / S-03).
- F-02 non-executable package contract, `torch.load`, or isolated inference.
- Writing `queued` / `running` / `completed` / `failed` from public HTTP in this slice.
- Public POST/PATCH for anomaly rows or run status.
- Hashing LogHub-scale HDFS logs at analyze time.
- Absorbing notebook `ArtifactStore` caches, ablation outputs, or Drive/rclone.
- BGL or any non-HDFS product path.
- SQLAlchemy/Alembic, long-lived connection pools, WebSockets, or dual-write of
  research artifacts.
- Account deletion, dataset/model/run deletion endpoints, or cascading wipes.
- Changing `requirements-macos-intel.lock.txt`.

## Implementation Approach

Add versioned migration `002_shared_durable_runtime_state` beside S-01's initial
schema. Keep `ApiDatabase` as the dual-dialect repository: short-lived connections,
`?`/`%s` translation, and one `session()` per atomic mutation.

Introduce a project-owned `datasets` table and kinded pointer columns on models.
Rebuild `analysis_runs` so the status CHECK can include the S-04 vocabulary while
preserving row ids. Store `results_summary_json` on the run and write
`anomaly_results` only through repository methods. Public HTTP stays additive:
keep `log_reference` / `artifact_reference`, add `dataset_id`, `storage_kind`, and
nullable `checksum`, and add Operator GET list/get dataset routes. Current analyze
upserts a workspace-kind dataset from today's path string.

Prove SQLite in the default suite. Provide a Docker PostgreSQL database under
`tests/postgres/` and `@pytest.mark.postgres` tests gated on `TEST_DATABASE_URL`.
CI's existing `pytest tests/test_api.py tests/test_artifacts.py` stays SQLite-only.

## Critical Implementation Details

### Timing & lifecycle

SQLite cannot change the `analysis_runs.status` CHECK in place. Implement `002` as a
callable, dialect-aware migration rather than only another static statement tuple.
Its SQLite branch opens a dedicated connection, disables foreign keys before
`BEGIN IMMEDIATE`, and restores enforcement only after `PRAGMA foreign_key_check`
passes. It creates `datasets`, makes a Python UUID mapping for the unique legacy
valid `(project_id, workspace, log_reference)` tuples, then creates replacement
`analysis_runs_002` and `anomaly_results_002` tables, copies all rows while
preserving analysis-run and anomaly-result ids, keeps legacy rejected attempts
without a dataset id, drops the old child then parent, renames replacements, and
recreates the two affected indexes. Commit or roll back the rebuild explicitly; do
not rely on SQLite's implicit DDL transaction behavior.

The PostgreSQL branch performs the same logical upgrade atomically: create and
backfill datasets, rebuild or alter the run/result relationship without depending on
an implicitly named CHECK constraint, preserve all primary/foreign-key ids, and
recreate indexes. It runs while the existing advisory migration lock is held. The
migration dispatcher records `002` only after its dialect branch succeeds.

### State sequencing

Every model, dataset-insert, run, result, and summary mutation must write its audit
event in the same `session()` as the domain change, matching S-01. Status changes
other than the initial insert use compare-and-swap (`UPDATE … WHERE id = ? AND
status = ?`); `rowcount != 1` is a conflict, not a silent overwrite. Result rows and
`results_summary_json` for a completed run are written in that same CAS transaction.

### Performance constraints

Do not SHA-256 Operator HDFS logs during `POST /analysis-runs`. Workspace-kind
dataset checksums stay null until S-03. Object-kind rows require a checksum at
insert time in the repository (no Bucket writer in this slice; tests supply the
value).

## Phase 1: Additive schema and PostgreSQL test harness

### Overview

Land migration `002` and a local Postgres container so later phases can persist
ownership columns on both dialects without touching S-01 identity tables.

### Changes Required:

#### 1. Versioned shared-state migration

**File**: `src/api/migrations.py`

**Intent**: Add `002_shared_durable_runtime_state` that creates datasets, widens
model pointers, rebuilds analysis runs for the expanded status CHECK, and adds a
durable results summary column — without altering `users` / `memberships` shape.

**Contract**: Add `002_shared_durable_runtime_state` through a callable migration
registered beside `001`; it owns its transaction semantics per dialect and records
its migration version only after every DDL and data-copy step succeeds. `datasets`
has `id`, `project_id` FK, `storage_kind` CHECK
`('workspace','object')`, `object_reference` TEXT NOT NULL, nullable `checksum`,
`source_compatibility` CHECK `= 'hdfs'`, `created_at`, and UNIQUE
`(project_id, storage_kind, object_reference)`. Object kind requires a non-empty
checksum at the SQL CHECK. `model_versions` gains `storage_kind` default
`workspace` and nullable `checksum`; keep `artifact_reference` as the opaque
pointer. The migration creates distinct replacement run/result tables, copies every
legacy run and anomaly result using Python-generated/deduplicated dataset ids only
for accepted legacy references, then recreates them under their canonical names and
indexes. Rebuilt `analysis_runs` keeps existing columns, adds nullable `dataset_id`
FK, `results_summary_json` TEXT NULL, and status CHECK
`('queued','running','completed','failed','rejected','not_supported')`.
It also has a CHECK that `dataset_id` is null exactly when `status = 'rejected'`;
all other statuses require a project-owned dataset. `schema_migrations` records
`002` exactly once; re-applying `001`+`002` is a no-op.
Existing `anomaly_results` rows, if any, keep the same `analysis_run_id` values.

#### 2. Local PostgreSQL harness

**Files**: `tests/postgres/compose.yaml`, `pyproject.toml`, `.env.example`

**Intent**: Give operators a disposable Postgres for dialect-sensitive migration and
CAS tests without making Docker a default `pytest` dependency.

**Contract**: Compose runs official Postgres on a local port with a documented
`TEST_DATABASE_URL`. Register pytest marker `postgres` (skip unless
`TEST_DATABASE_URL` is set). Comment `TEST_DATABASE_URL` in `.env.example`. Do not
add Postgres to `.github/workflows/verify.yml` in this phase.

#### 3. Fresh-schema migration tests

**File**: `tests/test_api.py` (and a focused postgres module if the SQLite file
would mix concerns)

**Intent**: Prove `002` on SQLite always, and on Postgres when the URL is present.

**Contract**: After `apply_migrations` twice, datasets exist, model pointer columns
exist, analysis_runs accepts the six statuses at the schema layer, and
`schema_migrations` contains `001_initial_schema` and
`002_shared_durable_runtime_state`. Seed a `001`-only store with model versions,
valid and rejected runs, and an anomaly row; after `002`, assert all legacy ids,
references, and result rows remain readable; accepted runs have their mapped
dataset and rejected runs have `dataset_id = null`. Postgres-marked tests use a
unique database name or schema per session and do not point at Railway.

### Success Criteria:

#### Automated Verification:

- Focused migration tests prove `001`+`002` are idempotent on SQLite and create the
  datasets table, kinded pointer columns, expanded run statuses, and
  `results_summary_json`.
- Seeded upgrade tests prove a populated `001` database preserves model, run, and
  anomaly-result ids and references across the `002` replacement-table migration,
  while keeping rejected attempts outside the datasets registry.
- `@pytest.mark.postgres` tests skip when `TEST_DATABASE_URL` is unset and, when
  set, apply `002` and pass `healthcheck`.
- `ruff check src/api tests` and `mypy` pass.

#### Manual Verification:

- `docker compose -f tests/postgres/compose.yaml up -d`, set `TEST_DATABASE_URL`,
  run `python -m src.api.migrations` against that URL, and confirm
  `schema_migrations` lists `002`.
- Remove the disposable local SQLite file at `.api/analyzer.db` if present, rerun
  migrations, and confirm the API still bootstraps.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that the local Postgres and SQLite migration
checks succeeded before proceeding.

---

## Phase 2: Repository ownership, audit, and status CAS

### Overview

Make dataset upsert, kinded pointers, atomic audit, result/summary persistence, and
legal status transitions the only way shared state is written.

### Changes Required:

#### 1. Dataset and pointer repository methods

**File**: `src/api/storage.py`

**Intent**: Persist project-owned datasets and kinded model pointers so later slices
can switch `storage_kind` without renaming identity.

**Contract**: Get-or-create dataset by
`(project_id, storage_kind, object_reference)`; reuse on match; insert+audit only
on first create. Workspace checksum may be null; object kind without checksum
raises before insert. `create_model_version` stores `storage_kind` (default
`workspace`), nullable `checksum`, and existing `artifact_reference`. List/get
datasets are project-scoped. Do not infer a dataset from the newest row.

#### 2. Atomic audit for model, dataset, run, and results

**File**: `src/api/storage.py`

**Intent**: Close the two-phase audit gap on publication and analysis writes so a
failed audit cannot leave an untraceable ownership change.

**Contract**: `create_model_version`, `publish_model_version`, dataset insert,
`create_analysis_run`, result/summary writes, and CAS status updates insert their
audit event in the same `session()`. Forced audit failure rolls back the domain
row. New dataset inserts use a distinct action (for example `dataset.registered`);
dataset reuse is silent. Keep existing action names for model register/publish and
analysis rejected/not_supported.

#### 3. Status CAS and durable results

**File**: `src/api/storage.py`

**Intent**: Let a future inference process share PostgreSQL without a forgeable
public writer and without last-write-wins on run status.

**Contract**: Initial insert may set `rejected` or `not_supported` (this slice's
HTTP) or `queued` (repository/tests only). Legal CAS: `queued → running`,
`running → completed`, `running → failed`. Terminal statuses (`rejected`,
`not_supported`, `completed`, `failed`) reject further transitions. Illegal CAS
raises a typed conflict. `replace_anomaly_results` plus `results_summary_json`
commit with the transition to `completed` in one session. `list_anomaly_results`
remains the read path. No HTTP route calls these writers yet.

### Success Criteria:

#### Automated Verification:

- Repository tests prove dataset reuse vs insert, object-kind checksum rejection,
  workspace-kind null checksum, audit rollback for model/dataset/run/result
  writes, legal CAS, illegal CAS, and stored summary+rows after a completed
  transition.
- Postgres-marked tests, when `TEST_DATABASE_URL` is set, cover unique dataset
  identity, object-kind checksum CHECK, and CAS conflict.
- `ruff check src/api tests` and `mypy` pass.

#### Manual Verification:

- Against local SQLite, use a short Python snippet or tests to insert a
  workspace dataset twice and confirm a single row; confirm an object-kind insert
  without checksum fails.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that repository invariants look right before
wiring HTTP.

---

## Phase 3: Additive HTTP reads and analyze upsert

### Overview

Expose the ownership contract on existing HDFS routes without breaking workspace-path
clients, and without adding public result/status writers.

### Changes Required:

#### 1. Response schemas and dataset routes

**Files**: `src/api/schemas.py`, `src/api/main.py`

**Intent**: Make dataset ownership and kinded pointers visible to authorized
Operators while keeping `log_reference` / `artifact_reference` and the current
analyze request body.

**Contract**: `AnalysisRunStatus` includes `queued`, `running`, `completed`,
`failed`, `rejected`, `not_supported`. Model and run responses add `storage_kind`,
nullable `checksum`, and run responses add `dataset_id`. Add
`GET /projects/{project_id}/datasets` and
`GET /projects/{project_id}/datasets/{dataset_id}` requiring Operator (Publisher
inherits). Missing or cross-project dataset/run/model remains `404` with the
existing generic detail. No POST/PATCH for datasets, results, or run status.
OpenAPI must not expose a public result-write operation.

#### 2. Analyze upsert and stored result reads

**File**: `src/api/main.py`

**Intent**: Every analysis run points at a project-owned dataset; GET results reads
what was stored, not a computed empty summary.

**Contract**: `POST /analysis-runs` still accepts `log_reference`, validates HDFS
as today. On successful validation, it upserts a workspace-kind dataset for the
canonical relative path and inserts the `not_supported` run with `dataset_id`.
On an unreadable, outside-workspace, or malformed input, it inserts only the
`rejected` validation run with `dataset_id = null`; it must not register the
canonical path or `<invalid-reference>` as a dataset. Both terminal outcomes
persist `results_summary_json` (rejected counts from the validation report;
`not_supported` has zero anomalies). GET results returns that stored summary and
`list_anomaly_results` (empty for this slice's HTTP). Register/publish remain
workspace-kind with null checksum. Audit for register, publish, and analysis stays
atomic via the Phase 2 methods.

#### 3. HTTP isolation and lifecycle coverage

**File**: `tests/test_api.py`

**Intent**: Extend the existing fixture style so publication and analysis still
behave, now with dataset ownership and stored summaries.

**Contract**: Existing 201/202/403/404/409 cases remain. Same `log_reference` in
one project yields one dataset and two runs. Cross-project dataset GET is 404.
GET datasets is empty-or-scoped to the authorized project. GET results for
rejected runs uses stored `rejected_records`, has `dataset_id = null`, and does
not make the rejected input appear in GET datasets. Unauthenticated and
Operator-denied administration behavior is unchanged. Assert OpenAPI has dataset
GET routes and lacks result-write routes.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py` passes, including dataset upsert identity,
  isolation, stored summaries, expanded status enum on responses, and unchanged
  `not_supported` / `rejected` HTTP writes with null dataset ids only for rejected
  inputs.
- Generated OpenAPI lists the dataset GET routes, includes the six run statuses,
  and has no public result or run-status write operation.
- `ruff check src/api tests` and `mypy` pass.

#### Manual Verification:

- As Publisher/Operator in `/docs`, register and publish a workspace model, analyze
  a valid and invalid log, list datasets, and confirm GET results summaries match
  the run outcomes without any result POST.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that the HTTP contract is additive before
updating the React client.

---

## Phase 4: Client types, dataset visibility, and documentation

### Overview

Keep the thin React client type-correct, show stored datasets as read-only project
state, and document the shared-state contract without claiming Bucket uploads or
inference.

### Changes Required:

#### 1. Typed dataset and pointer client

**File**: `frontend/src/api.ts`

**Intent**: Mirror the additive API fields and dataset GET methods without local
authorization logic.

**Contract**: `AnalysisRunStatus` includes the six statuses. `ModelVersion` and
`AnalysisRun` include `storage_kind`, nullable `checksum`, and `dataset_id` on
runs. Add `Dataset` and `listDatasets` / `getDataset`. Continue to start analysis
with `log_reference`. Surface server errors via existing `ApiError`.

#### 2. Read-only dataset visibility

**Files**: `frontend/src/App.tsx`, `frontend/src/styles.css`

**Intent**: Operators can see project-owned datasets and run `dataset_id` in the
existing Analysis view; they still start analysis with a workspace path.

**Contract**: Refresh loads datasets with other project data. Analysis view lists
datasets (reference, storage kind, optional checksum) without upload controls.
Run cards show `dataset_id` in addition to `log_reference`. Status badges/styles
cover `running`, `completed`, and `failed`. Existing queued auto-refresh also
polls `running` (still unused by HTTP). No new write forms.

#### 3. Operator documentation

**Files**: `README.md`, `context/deployment/deploy-plan.md`

**Intent**: Describe kinded pointers, dataset GET, stored summaries, the Docker
Postgres test harness, and the still-deferred Bucket/inference gates.

**Contract**: README FastAPI section documents dataset ownership, additive fields,
`TEST_DATABASE_URL` / compose for postgres-marked tests, and that valid analysis
remains `not_supported`. Deploy-plan still forbids Bucket credentials on `web` and
does not claim object-kind production storage. Do not present workspace hashing of
HDFS logs as required.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py tests/test_artifacts.py` passes.
- `ruff check src tests scripts run_ablation.py` and `mypy` pass.
- `cd frontend && npm ci && npm run build` passes.

#### Manual Verification:

- Sign in as Operator: see datasets for the selected project, start analysis with a
  workspace log reference, and see `dataset_id` plus stored result summaries.
- Confirm docs and OpenAPI still have no upload, Bucket, or inference-completion
  path, and that `not_supported` remains the valid-HDFS HTTP outcome.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that the manual UI and docs checks succeeded
before declaring the change ready to archive.

## Testing Strategy

### Unit Tests:

- `001`+`002` idempotence and required columns/CHECKs on SQLite.
- Dataset get-or-create identity; object-kind checksum rejection.
- Audit rollback for model, dataset, run, and result writes.
- Legal and illegal status CAS; completed transition writes summary+rows atomically.

### Integration Tests:

- HTTP register/publish/analyze lifecycle still returns `not_supported` / `rejected`.
- Same path in one project → one dataset, many runs; cross-project GET → 404.
- GET results reads stored summary; OpenAPI has no public result writer.
- Postgres-marked dialect tests when `TEST_DATABASE_URL` is set.

### Manual Testing Steps:

1. Reset local SQLite, migrate, bootstrap, provision Publisher/Operator.
2. Start local Postgres compose and run `pytest -m postgres` with `TEST_DATABASE_URL`.
3. Register a workspace model, publish, analyze valid and invalid logs, list
   datasets, and inspect stored summaries in UI and `/docs`; confirm only the
   valid log is a reusable dataset.
4. Confirm there is no UI or API to POST anomalies or mark a run completed.

## Performance Considerations

MVP scale remains one active analysis and LogHub-sized HDFS files. Dataset upsert is
a unique-key lookup, not a content hash. Do not hash large workspace logs. Keep
short-lived `session()` connections so Railway Serverless can still sleep. Do not
add pagination, caching, or a connection pool in this slice. Frontend polling stays
bounded to in-progress statuses while the Analysis view is open.

## Migration Notes

`002` is additive on top of S-01's `001_initial_schema`. Wipe disposable local
SQLite (`.api/analyzer.db`) after pulling this change so the rebuilt
`analysis_runs` table is created cleanly; then rerun `python -m src.api.migrations`.
If a Railway staging database already applied only `001`, apply `002` forward — do
not rewrite `001`, drop identity tables, or run destructive SQL during an incident.
The copy/backfill in `002` must preserve analysis run ids and leave rejected legacy
attempts with null dataset ids. No notebook or workspace file migration. Object-kind
rows are test-only until S-02/S-03.

## References

- Product requirements: `context/foundation/prd.md` (FR-006, FR-008)
- Roadmap foundation: `context/foundation/roadmap.md` (F-01)
- Stack contract: `context/foundation/tech-stack.md` (PostgreSQL + Bucket pointers)
- Deploy gates: `context/deployment/deploy-plan.md`
- Current schema: `src/api/migrations.py`
- Current repository: `src/api/storage.py`
- Current HTTP lifecycle: `src/api/main.py`
- S-01 atomic-audit pattern: `context/changes/provision-project-accounts/plan.md`
- API tests: `tests/test_api.py`
- Thin client: `frontend/src/api.ts`, `frontend/src/App.tsx`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Additive schema and PostgreSQL test harness

#### Automated

- [x] 1.1 Focused migration tests prove `001`+`002` are idempotent on SQLite and create the datasets table, kinded pointer columns, expanded run statuses, and `results_summary_json` — 292ac2a
- [x] 1.2 `@pytest.mark.postgres` tests skip when `TEST_DATABASE_URL` is unset and, when set, apply `002` and pass `healthcheck` — 292ac2a
- [x] 1.3 `ruff check src/api tests` and `mypy` pass — 292ac2a

#### Manual

- [x] 1.4 `docker compose -f tests/postgres/compose.yaml up -d`, set `TEST_DATABASE_URL`, run `python -m src.api.migrations` against that URL, and confirm `schema_migrations` lists `002` — 292ac2a
- [x] 1.5 Remove the disposable local SQLite file at `.api/analyzer.db` if present, rerun migrations, and confirm the API still bootstraps — 292ac2a

### Phase 2: Repository ownership, audit, and status CAS

#### Automated

- [x] 2.1 Repository tests prove dataset reuse vs insert, object-kind checksum rejection, workspace-kind null checksum, audit rollback for model/dataset/run/result writes, legal CAS, illegal CAS, and stored summary+rows after a completed transition — 9f37579
- [x] 2.2 Postgres-marked tests, when `TEST_DATABASE_URL` is set, cover unique dataset identity, object-kind checksum CHECK, and CAS conflict — 9f37579
- [x] 2.3 `ruff check src/api tests` and `mypy` pass — 9f37579

#### Manual

- [x] 2.4 Against local SQLite, insert a workspace dataset twice and confirm a single row; confirm an object-kind insert without checksum fails — 9f37579

### Phase 3: Additive HTTP reads and analyze upsert

#### Automated

- [x] 3.1 `python -m pytest tests/test_api.py` passes, including dataset upsert identity, isolation, stored summaries, expanded status enum on responses, and unchanged `not_supported` / `rejected` HTTP writes — 067691b
- [x] 3.2 Generated OpenAPI lists the dataset GET routes, includes the six run statuses, and has no public result or run-status write operation — 067691b
- [x] 3.3 `ruff check src/api tests` and `mypy` pass — 067691b

#### Manual

- [x] 3.4 As Publisher/Operator in `/docs`, register and publish a workspace model, analyze a valid and invalid log, list datasets, and confirm GET results summaries match the run outcomes without any result POST — 067691b

### Phase 4: Client types, dataset visibility, and documentation

#### Automated

- [x] 4.1 `python -m pytest tests/test_api.py tests/test_artifacts.py` passes — f3eedb4
- [x] 4.2 `ruff check src tests scripts run_ablation.py` and `mypy` pass — f3eedb4
- [x] 4.3 `cd frontend && npm ci && npm run build` passes — f3eedb4

#### Manual

- [x] 4.4 Sign in as Operator: see datasets for the selected project, start analysis with a workspace log reference, and see `dataset_id` plus stored result summaries — f3eedb4
- [x] 4.5 Confirm docs and OpenAPI still have no upload, Bucket, or inference-completion path, and that `not_supported` remains the valid-HDFS HTTP outcome — f3eedb4
