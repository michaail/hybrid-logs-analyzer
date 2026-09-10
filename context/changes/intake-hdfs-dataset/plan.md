# Intake HDFS Dataset Implementation Plan

## Overview

Give an Operator a same-origin HDFS log upload that ends in a structured 422 or
an accepted project-owned dataset, then let them start analysis by selecting that
`dataset_id`. Drain3 is not admitted here: S-04 will load a static parser
snapshot with `configs/drain.ini` and skip enrichment.

## Current State Analysis

Roadmap S-03 (US-02, FR-005, FR-008): an Operator can upload or select an HDFS
dataset and receive a clear whole-dataset acceptance or rejection. F-01 already
created the `datasets` table; S-02 already proved multipart admit → validate →
object put → insert.

What exists:

- `POST /projects/{project_id}/analysis-runs` still requires JSON
  `log_reference`, regex-validates a trusted-workspace file, and upserts a
  `workspace` dataset only when the run is not rejected
  (`src/api/main.py:505-592`, `src/api/storage.py:601-629`).
- `validate_hdfs_log` already enforces UTF-8 and whole-file `_HDFS_LINE` matching;
  `valid = (total_records > 0) and (invalid_records == 0)`
  (`src/api/validation.py:34-36`, `239-273`).
- GET `/projects/{project_id}/datasets` is Operator-scoped and omits rejected
  inputs. There is no POST (`src/api/main.py:640-668`;
  `tests/test_api.py:1031-1034` asserts `post` is absent).
- Object store can put/delete prefixes but only has model key helpers
  (`src/api/object_store.py:45-60`). Dataset object-kind rows require a checksum
  (`src/api/migrations.py:115-129`).
- The React Analysis view lists datasets as read-only and tells the Operator
  that browser upload is unavailable (`frontend/src/App.tsx:683-687`,
  `1341-1358`). `startAnalysis` still sends `log_reference`
  (`frontend/src/api.ts:197-201`).
- Drain3 `DrainParser.load` exists and is unused by the API
  (`src/modules/parser/drain_parser.py:238-252`). The published GAE package is
  only `manifest.json` + `.pt` + `evidence.json`
  (`src/modules/model_package.py`). Production `run_ablation.py` still *fits*
  Drain on cache miss; notebooks document freeze/reuse.

Parser is out of this slice because re-fitting Drain on upload would retokenize
`cluster_id`s and break FR-011 alignment with a published GAE. Enrichment is
already optional in the pipeline and is not needed when the frozen template set
covers the tested HDFS dataset.

## Desired End State

An authenticated Operator (Publisher inherits Operator) uploads a UTF-8 HDFS
log from the browser (multipart, 32 MiB cap). Invalid, empty, oversize, or
non-UTF-8 payloads return 422 with a validation report, persist no object, and
insert no row. A valid file becomes a new `storage_kind=object` dataset with a
SHA-256 checksum. The datasets panel shows the accepted row. The analyze dialog
selects from that list and `POST /analysis-runs` takes `dataset_id` only.
Analysis still ends `not_supported` (`INFERENCE_CONTRACT_UNAVAILABLE`). Invalid
logs never become analysis runs.

S-04 will load a frozen Drain3 snapshot with `configs/drain.ini`, call
`annotate_file` only, and skip LLM enrichment. Unmatched-line policy is S-04.

### Key Discoveries:

- Whole-dataset regex rejection already exists; it is bound to analyze +
  workspace paths (`src/api/validation.py:239-273`).
- S-02 admission order is the pattern: validate temp bytes → put → insert;
  409/unique conflict deletes the prefix (`src/api/validation.py:94-182`,
  `src/api/main.py:376-440`).
- Frontend 422 Banner only joins `detail.issues[].reason`
  (`frontend/src/api.ts:312-337`). A report-only 422 would render as
  `Request failed (422)`.
- `analysis_runs` CHECK: `dataset_id` is null iff `status = 'rejected'`
  (`src/api/migrations.py:149-152`). Intake 422 must not fight that CHECK.
- Dataset identity is `(project_id, storage_kind, object_reference)`, not
  content hash. A new UUID per upload keeps uniqueness without checksum-dedupe.
- CSP `connect-src 'self'` still rules out cross-origin presigned PUT.

## What We're NOT Doing

- Uploading, fitting, or loading Drain3; parser-config Bucket objects; extending
  the GAE package with `.bin` or `drain.ini`.
- LLM enrichment at intake or analysis time.
- Full LogHub-scale (~GB) browser upload or presigned PUT.
- Public workspace `log_reference` on `POST /analysis-runs`.
- Dataset delete, rename, or BGL.
- Isolated inference, changing `not_supported`, or executing GAE (S-04).
- Checksum-deduping uploads (every successful upload is a new row).
- Creating `analysis.rejected` runs from invalid uploads.
- Regenerating `requirements-macos-intel.lock.txt`.
- Importing Drain3 or Torch on the public API path.

## Implementation Approach

Mirror S-02, with a raw log instead of a ZIP:

1. Multipart `log` to FastAPI (32 MiB cap, independent of the model ZIP constant).
2. Validate UTF-8 and whole-file HDFS regex in process (reuse `_HDFS_LINE`).
3. On success, put one object at
   `projects/<project-id>/datasets/<dataset-id>/<sanitized-name>`.
4. Insert `datasets` with `storage_kind=object` and checksum = SHA-256 of the
   raw bytes. Audit `dataset.registered` on insert (existing upsert helper).
5. `POST /analysis-runs` requires a same-project `dataset_id` and a published
   model. It does not re-scan the log. It copies `object_reference` into the
   existing `log_reference` column and still finishes `not_supported`.

## Critical Implementation Details

**Timing & lifecycle.** Validate the payload first. Put the object next. Insert
the row last. If insert hits the unique
`(project_id, storage_kind, object_reference)` conflict, delete the just-written
prefix so a 409 leaves no orphan objects. Never insert a row that points at
missing bytes.

**422 shape.** `detail` must include both the existing HDFS report fields
(`valid`, `total_records`, `invalid_records`, `examples`) and `issues[].reason`
so `frontend/src/api.ts` `responseMessage` can fill the Banner.

**Analyze ack.** Do not re-read the stored object to regex-validate again.
Existence + same-project membership + published model is enough for the
two-second analysis ack. Missing/foreign dataset is 404.

**Repository create_analysis_run.** Non-rejected runs take an existing
`dataset_id` instead of upserting a workspace pointer from `log_reference`.
Rejected-run inserts used to prove the CHECK constraint stay
`dataset_id is None`. Repository helpers that currently create queued /
`not_supported` runs from a path must `upsert_dataset` first and pass that id.

## Phase 1: Dataset object admission helper

### Overview

Add dataset object keys and an in-process admit helper that validates HDFS bytes
and persists one object only when the whole file is valid. No HTTP change yet.

### Changes Required:

#### 1. Dataset object key helpers

**File**: `src/api/object_store.py`

**Intent**: Give dataset admission the same POSIX key protocol models already
use, without sharing the model prefix.

**Contract**: Builders for
`projects/<project-id>/datasets/<dataset-id>` and
`projects/<project-id>/datasets/<dataset-id>/<relative>`. Reuse
`_require_relative_posix`. No Torch import.

#### 2. HDFS byte admission

**File**: `src/api/validation.py`

**Intent**: Validate uploaded log bytes without a trusted-workspace path, and
persist only after the whole file is accepted.

**Contract**: `MAX_HDFS_UPLOAD_BYTES = 32 * 1024 * 1024` (do not reuse
`MAX_ZIP_COMPRESSED_BYTES` by name). `admit_uploaded_hdfs_log(payload, *,
object_store, project_id, original_filename)` returns
`(report, AdmittedHdfsDataset | None)`. Oversize (`len > 32 MiB`), empty,
non-UTF-8, or any non-matching line → `valid=false`, put nothing. Valid →
SHA-256 of the raw bytes, last path segment is a sanitized original filename or
`hdfs.log`. Reuse `_HDFS_LINE` and the 20-example cap. FastAPI still reads at
most cap+1 bytes at the HTTP boundary in phase 2.

#### 3. Tests for the helper and filesystem adapter

**File**: `tests/test_object_store.py` and a focused admit test module (or
`tests/test_api.py` helpers if they stay HTTP-free)

**Intent**: Prove accept, oversize, empty, one bad line, and UTF-8 failure
without FastAPI, and that failure leaves the object root empty.

**Contract**: Non-ML tests against `FilesystemObjectStore`. Include a key-builder
assertion matching the model-key test style in `tests/test_object_store.py`.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_object_store.py` plus the admit-helper tests pass
  for accept, 32 MiB+1, empty, one bad line, and UTF-8 failure; object root is
  empty on every failure.
- `ruff check src/api/object_store.py src/api/validation.py` and `mypy` pass on
  those modules.

#### Manual Verification:

- Inspect one successful filesystem prefix: a single log object, no extras.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase. Phase
blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items
live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Operator HTTP

### Overview

Expose `POST /projects/{project_id}/datasets` and switch analyze to
`dataset_id` only. Invert workspace-path HTTP tests. Keep repository rejected-run
CHECK tests.

### Changes Required:

#### 1. Dataset upload route

**File**: `src/api/main.py`

**Intent**: Let an Operator admit a log without choosing a model or starting a
run.

**Contract**: `POST /projects/{project_id}/datasets` with `UploadFile` field
`log`. Operator role (Publisher inherits). Read at most
`MAX_HDFS_UPLOAD_BYTES + 1`. 201 `DatasetResponse`. 422 `detail` is the report
plus `issues`. No insert and no leftover objects on 422. On unique conflict
after persist, delete prefix and return 409. Audit `dataset.registered` via
the existing insert path.

#### 2. Analyze by dataset_id

**File**: `src/api/schemas.py`, `src/api/main.py`, `src/api/storage.py`

**Intent**: Selecting a stored dataset is the only public way to start analysis.

**Contract**: `AnalysisRunCreate` replaces `log_reference` with `dataset_id`.
Missing/foreign dataset → 404. Unpublished model still 409. Non-rejected
`create_analysis_run` attaches the given `dataset_id` and copies
`object_reference` into `log_reference`; it does not upsert a workspace dataset.
Repeat analyze with the same `dataset_id` creates a new run pointing at the same
dataset. Status remains `not_supported` /
`INFERENCE_CONTRACT_UNAVAILABLE` for valid datasets.

#### 3. Invert HTTP tests; keep repository CHECK tests

**File**: `tests/test_api.py`, `tests/test_shared_state_repository.py`

**Intent**: Lock upload 201/422 and `dataset_id` analyze without dropping
rejected-run CHECK coverage.

**Contract**: Add an `_upload_log` helper (multipart `log`). Valid upload →
object dataset + checksum; analyze with that id → `not_supported` and
`storage_kind=object`. Invalid upload → 422, empty dataset list, empty object
root, no analysis run. Isolation tests upload then GET 404 across projects.
OpenAPI: `post` exists on `/projects/{project_id}/datasets`; analyze schema
uses `dataset_id`. Unpublished-model 409 still creates no run.
`create_analysis_run(..., status="rejected")` remains `dataset_id is None`.
Helpers that create queued/`not_supported` runs must pass a real `dataset_id`.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py tests/test_shared_state_repository.py`
  passes, including 201 persist, 422-without-row, analyze-by-dataset_id,
  isolation, and rejected-run CHECK.
- `ruff check src/api/main.py src/api/schemas.py src/api/storage.py tests/test_api.py`
  and `mypy` pass on those paths.

#### Manual Verification:

- `GET /openapi.json` shows POST datasets and analyze `dataset_id`; no public
  `log_reference` on create.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Operator UI and S-04 Drain3 handoff docs

### Overview

Put upload on the datasets panel and dataset select in the analyze dialog.
Replace workspace-log documentation and record the S-04 static Drain3 contract.

### Changes Required:

#### 1. Client API

**File**: `frontend/src/api.ts`

**Intent**: Match S-02 multipart (do not force JSON Content-Type) and send
`dataset_id` when starting analysis.

**Contract**: `uploadDataset(projectId, File)` appends field `log`.
`startAnalysis(projectId, modelVersionId, datasetId)` JSON body is
`{ model_version_id, dataset_id }`. 422 still uses existing `issues` joining.

#### 2. Datasets panel and analyze dialog

**File**: `frontend/src/App.tsx`

**Intent**: Intake is its own Operator action; analyze only selects an accepted
dataset.

**Contract**: Datasets panel: file picker, submit upload, Banner on 422, list
refresh on 201. Remove “no upload control in this view”. Analyze dialog: required
`<select>` of listed datasets; drop the workspace path field and the
upload-unavailable warning. Disable start when the list is empty. After start,
existing `not_supported` notice remains.

#### 3. Docs and S-04 handoff

**File**: `README.md`, `context/deployment/deploy-plan.md`

**Intent**: Operators no longer need a trusted-workspace log path. S-04
implementers inherit a frozen parser contract instead of inventing parser
upload.

**Contract**: README and deploy-plan replace “workspace `log_reference` until
S-03” with object-kind dataset upload and analyze-by-`dataset_id`. Document:
S-04 loads a frozen Drain3 FilePersistence snapshot with `configs/drain.ini`
via `DrainParser.load`, then `annotate_file` only; do not fit; do not
re-enrich; do not put parser files in the GAE package; unmatched-line handling
is S-04. `API_TRUSTED_WORKSPACE_ROOT` is no longer the Operator log intake path.

### Success Criteria:

#### Automated Verification:

- `npx tsc --noEmit` in `frontend/` passes.

#### Manual Verification:

- Upload a valid sample: list shows a new object-kind row.
- Upload an invalid sample: Banner from `issues`, list unchanged.
- Start analysis by selecting the accepted dataset: run is `not_supported`.
- Datasets panel and analyze dialog remain usable at a desktop width and a
  narrow viewport.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful.

---

## Testing Strategy

### Unit Tests:

- Dataset key builders reject `..` and absolute paths the same way model keys do.
- `admit_uploaded_hdfs_log`: valid one-line HDFS; empty; 32 MiB+1; one bad line
  among valid lines; non-UTF-8 bytes; sanitized filename vs fallback `hdfs.log`.
- Failure paths put zero objects.

### Integration Tests:

- Operator 201 + `dataset.registered`; second upload of the same bytes is a new
  row (no checksum reuse).
- 422 invalid log: no row, no objects, no analysis run.
- Analyze with `dataset_id`: 202 `not_supported`, same dataset on repeat.
- Foreign project dataset_id / missing id: 404.
- Unpublished model: 409, no run.
- OpenAPI POST datasets present; create-run property is `dataset_id`.

### Manual Testing Steps:

1. Sign in as Operator, upload a one-line valid HDFS file, confirm the list row.
2. Upload `not an HDFS record`, confirm Banner and no new row.
3. Publish a model, select the accepted dataset, start analysis, confirm
   `not_supported`.
4. Confirm a Publisher can also upload (inherits Operator) and an
   unauthenticated request is 401.

## Performance Considerations

The 32 MiB cap keeps the S-02 in-memory `read(cap + 1)` pattern safe. Do not
SHA-256 or regex-scan the object again on analyze. Full LogHub files are out of
scope for browser upload.

## Migration Notes

No schema migration. `datasets` already allows object kind with checksum.
`analysis_runs.log_reference` stays NOT NULL and stores the object key. Existing
workspace-kind rows from earlier walking-skeleton analyzes remain listable; new
HTTP admits are object-kind only. Local `.api/analyzer.db` does not need a reset
for this slice.

## References

- Approved planning decisions: Cursor plan `intake_hdfs_dataset_8d25227c`
- Similar admission: `context/archive/2026-09-10-publish-hdfs-model-package/plan.md`
- Dataset table: `src/api/migrations.py` (`002` datasets)
- Drain load API: `src/modules/parser/drain_parser.py`
- Parser config: `configs/drain.ini`
- PRD: `context/foundation/prd.md` FR-005, US-02, FR-008, FR-011

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Dataset object admission helper

#### Automated

- [x] 1.1 python -m pytest tests/test_object_store.py plus the admit-helper tests pass for accept, 32 MiB+1, empty, one bad line, and UTF-8 failure; object root is empty on every failure — eac04fc
- [x] 1.2 ruff check src/api/object_store.py src/api/validation.py and mypy pass on those modules — eac04fc

#### Manual

- [x] 1.3 Inspect one successful filesystem prefix: a single log object, no extras — eac04fc

### Phase 2: Operator HTTP

#### Automated

- [x] 2.1 python -m pytest tests/test_api.py tests/test_shared_state_repository.py passes, including 201 persist, 422-without-row, analyze-by-dataset_id, isolation, and rejected-run CHECK
- [x] 2.2 ruff check src/api/main.py src/api/schemas.py src/api/storage.py tests/test_api.py and mypy pass on those paths

#### Manual

- [x] 2.3 GET /openapi.json shows POST datasets and analyze dataset_id; no public log_reference on create

### Phase 3: Operator UI and S-04 Drain3 handoff docs

#### Automated

- [ ] 3.1 npx tsc --noEmit in frontend/ passes

#### Manual

- [ ] 3.2 Upload a valid sample: list shows a new object-kind row
- [ ] 3.3 Upload an invalid sample: Banner from issues, list unchanged
- [ ] 3.4 Start analysis by selecting the accepted dataset: run is not_supported
- [ ] 3.5 Datasets panel and analyze dialog remain usable at a desktop width and a narrow viewport
