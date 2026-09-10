# Publish HDFS Model Package Implementation Plan

## Overview

Give a Publisher a same-origin ZIP upload that ends in a structured 422 or an
`eligible` model version, without changing the existing explicit-publish gate.
Bytes are validated in a temp directory by the isolated F-02 probe, then only
declared package files are persisted through an object-kind adapter
(filesystem locally, Railway Bucket when configured).

## Current State Analysis

Frame brief (HIGH confidence): the observation is off-host submit, not publish.
A Publisher cannot get a complete HDFS package from their machine into the
workflow. Eligibility and explicit publish already work for packages that are
already on disk.

Research baseline:

- `POST /projects/{project_id}/models` accepts JSON `{ "package_reference" }`
  only. `trusted_package_directory` rejects files and ZIPs before the validator
  (`src/api/validation.py:48-56`, `src/api/main.py:376-441`).
- Isolated `python -m src.model_validator` probes tensors with
  `weights_only=True` and a scrubbed environment. FastAPI never imports Torch.
- ZIP unpack with byte-written caps already exists in
  `src/modules/model_package.py:630-678` and is **not** an admission-storage
  operation (`330-339`). Extra undeclared files are ignored for eligibility.
- Register writes `storage_kind='workspace'` and null checksum
  (`src/api/storage.py:487-518`). Object-kind columns exist; no Bucket client.
- Railway has no Volume and Bucket credentials are unattached
  (`context/deployment/deploy-plan.md:57-64`). Workspace-path registration
  cannot ship there.
- UI is a path text field with “uploads are intentionally unavailable”
  (`frontend/src/App.tsx:1272-1284`). `frontend/src/api.ts` always JSON-encodes
  bodies.
- Operators get 403 on register/publish; analysis requires a same-project
  published model. Inference stays `not_supported`.
- `tests/test_api.py:878-891` locks HTTP ZIP rejection and must invert.

## Desired End State

A project Publisher uploads one ZIP from the browser (multipart, same origin).
The API unpacks to a temp directory, runs the existing isolated directory
validator, and on success copies **only** `manifest.json` plus the declared
artifact and evidence into immutable object storage. The row is `eligible`,
`storage_kind=object`, with a non-empty checksum. Invalid packages return the
same structured 422 shape as today and insert nothing. Explicit publish,
Operator denial, project isolation, and `not_supported` analysis are unchanged.

Local/dev and pytest use a filesystem object backend. Staging uses a Railway
Bucket when credentials are attached. The public `package_reference` JSON
contract is gone.

### Key Discoveries:

- Frame: plan admission through 422-or-eligible; do not rebuild publish
  (`context/changes/publish-hdfs-model-package/frame.md`).
- ZIP extract already counts bytes written (F-02 F7);
  `src/modules/model_package.py:630-678`.
- Validator CLI is directory-only: `src/model_validator/__main__.py:15-24`.
- Datasets already require object checksums in SQL;
  `model_versions` does not (`src/api/migrations.py:109-123` vs `351-354`).
- CSP `connect-src 'self'` (`src/api/main.py:737-742`) is why multipart wins
  over cross-origin presigned PUT.
- `create_model_version` already accepts `storage_kind` / `checksum` but
  register never passes them (`src/api/main.py:423-435`).

## What We're NOT Doing

- Rebuilding or auto-collapsing explicit publish (`eligible` → `published`).
- Isolated inference, `AttributeAwareGAE` construction, or changing
  `not_supported` / `INFERENCE_CONTRACT_UNAVAILABLE` (S-04).
- Dataset / HDFS log upload (S-03).
- Keeping a public directory `package_reference` admission path.
- Presigned browser PUT to Bucket in this slice.
- Persisting ZIP-member identities (`<zip>#<member>`).
- Copying undeclared extra files from the archive.
- Unwrapping a single top-level folder; `manifest.json` must sit at ZIP root
  (current extractor contract).
- A notebook/pipeline package exporter.
- Hiding Register/Publish from Operators in the UI (API 403 remains the
  control; membership list is Administrator-scoped).
- Passing Bucket, JWT, or database secrets into the validator process.
- Using `src/modules/model.py` `weights_only=False` on uploaded artifacts.
- Regenerating `requirements-macos-intel.lock.txt`.
- Public sign-up, BGL packages, or quality scoring of evidence.

## Implementation Approach

Keep F-02’s directory contract as the eligibility unit. ZIP is transport only:

1. Multipart upload to FastAPI (32 MiB compressed cap, existing ZIP member
   rules).
2. Extract to a process-local temp directory (existing `_extract_zip_archive`).
3. Isolated directory validator (unchanged CLI).
4. On success, copy declared files only through an object-store protocol.
5. Insert `eligible` with `storage_kind=object` and
   `checksum = artifact_sha256`.
6. Existing `POST .../publish` unchanged.

Object keys use a UUID generated before persist:
`projects/<project-id>/models/<model-id>/<version>/`. Stored
`package_reference` is that prefix; `artifact_reference` is the artifact key
under it. Filesystem backend is the default; Bucket backend activates when
object-store settings are present.

## Critical Implementation Details

**Timing & lifecycle.** Validate the temp directory first. Persist declared
files next. Insert the row last. If insert hits the unique
`(project_id, model_identifier, version)` conflict, delete the just-written
prefix so a 409 leaves no orphan objects. Never insert a row that points at
missing bytes.

**SQLite CHECK.** Adding “object kind requires checksum” on `model_versions`
cannot use a simple `ALTER` on SQLite (F-01 already hit this). PostgreSQL can
add a CHECK; SQLite must rebuild `model_versions` in an additive `004`
migration, same pattern as `002_shared_durable_runtime_state`. Python
`_normalized_checksum` stays the request-time guard.

**Validator isolation.** The subprocess still receives one local directory
path. Object-store credentials must not appear in
`allowed_validator_environment`. Do not teach the CLI to read ZIPs or Bucket
keys in this slice.

## Phase 1: Declared-files materialize and filesystem object store

### Overview

Add a reusable copy of only declared package files, plus an object-store
protocol with a filesystem backend. No HTTP change yet.

### Changes Required:

#### 1. Declared-files materialize helper

**File**: `src/modules/model_package.py`

**Intent**: After a directory has passed (or is about to pass) the directory
contract, copy `manifest.json` and the two declared file paths to a
destination prefix. Extra undeclared files must not be copied. Refuse
symlinks and path escape.

**Contract**: A function that takes a package directory and a destination
directory, reads `ModelPackageManifest`, and writes exactly those three
relative paths. Destination layout matches the source relative names. Does
not call Torch and does not unpack ZIPs (unpack stays `_extract_zip_archive`).

#### 2. Object-store protocol and filesystem backend

**File**: new module under `src/api/` (object-store adapter)

**Intent**: Give registration a put/delete-prefix API so HTTP and tests do not
hard-code a filesystem layout. Local/dev writes under a dedicated object root,
not the Publisher-staged workspace tree.

**Contract**: Protocol with put of relative path bytes, delete of a key prefix,
and a key builder
`projects/{project_id}/models/{model_id}/{version}/{relative}`. Filesystem
backend roots at `API_OBJECT_STORE_ROOT` (new setting; default a sibling of
the trusted workspace, e.g. resolved `.api/objects`). Keys stay POSIX and
cannot escape the root.

#### 3. Settings for the filesystem backend

**File**: `src/api/settings.py`

**Intent**: Configure the object root without introducing Bucket credentials
in this phase.

**Contract**: Additive optional `object_store_root` from
`API_OBJECT_STORE_ROOT`. Trusted workspace setting remains for HDFS log
references until S-03.

#### 4. Tests for copy-only and filesystem adapter

**File**: `tests/test_model_package.py` and a focused new test module for the
adapter

**Intent**: Prove extras are dropped, zip-slip destinations are rejected, and
put/delete-prefix works on the filesystem backend.

**Contract**: Non-ML tests; no Torch import. Reuse existing hand-built package
fixtures.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_model_package.py tests/test_object_store.py`
  (or the chosen adapter test path) passes, including declared-files-only copy
  and filesystem prefix delete.
- `ruff check src/modules/model_package.py src/api tests/test_model_package.py`
  and `mypy` pass.

#### Manual Verification:

- Inspect one materialized prefix on disk: only `manifest.json`, declared
  `.pt`, and declared evidence; leftover ZIP members are absent.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase. Phase
blocks use plain bullets — the corresponding `- [ ]` checkboxes for these
items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: HTTP multipart ZIP admission

### Overview

Replace public JSON `package_reference` registration with a Publisher-only
multipart ZIP upload that validate-then-persists into object storage and
inserts `eligible`.

### Changes Required:

#### 1. Registration request and route

**File**: `src/api/schemas.py`, `src/api/main.py`

**Intent**: Accept a ZIP file from an authorized Publisher, never a host path.
Keep structured 422, 409 duplicate identity, 503 validator failure, and 201
eligible. Do not auto-publish.

**Contract**: `POST /projects/{project_id}/models` is `multipart/form-data`
with a file field (e.g. `package`). Reject non-ZIP / oversize with the same
`{ valid, issues[] }` 422 envelope. Operator 403 and non-member 404 stay.
Map publish CAS `ValueError` to 409 while touching this file. Add a focused
test that unpublished eligible models cannot start analysis (logic already at
`src/api/main.py:516-520`).

#### 2. Validate-then-store admission helper

**File**: `src/api/validation.py`

**Intent**: Orchestrate temp extract → isolated directory validator →
declared-files put → identity for insert. Cleanup temp on every exit.

**Contract**: Reuse `run_private_package_validator` and the directory
manifest re-read. Do not call `torch.load` in this process. Do not pass
object-store env into the validator. Generate `model_id` (UUID) before put.
On validator invalid, return the typed report and put nothing.

#### 3. Persist object-kind model rows

**File**: `src/api/storage.py`, `src/api/migrations.py`

**Intent**: Registration writes `storage_kind='object'` and
`checksum=artifact_sha256`. Unique identity conflict still 409. Additive
migration `004` enforces object checksum like `datasets`.

**Contract**: `create_model_version` is called with object kind and non-empty
checksum. `package_reference` stores the object prefix;
`artifact_reference` stores the artifact object key;
`external_evaluation_evidence` stays the relative evidence path from the
manifest. Audit action remains `model.registered` (upload and register are
one request). If insert fails after put, delete the prefix.

#### 4. HTTP tests

**File**: `tests/test_api.py`

**Intent**: Invert direct-ZIP rejection into successful ZIP admission for a
valid package; keep structured 422 for ineligible ZIPs; prove no row on 422;
Operator still 403; directory `package_reference` JSON is no longer accepted.

**Contract**: `_register` sends multipart bytes, not JSON path.
`test_registration_rejects_direct_zip_with_structured_422` is replaced by
tests named for the new contract. Default fixture may keep
`files_only_validator`; `@pytest.mark.ml` still covers dummy/pickle 422 vs
tensor 201. Analysis after publish remains `not_supported`.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py tests/test_model_package.py` passes,
  including ZIP 201 eligible, ineligible ZIP 422 with empty model list,
  Operator 403, duplicate 409, unpublished analysis 409, and retained
  `not_supported` after publish.
- `ruff check src/api tests/test_api.py` and `mypy` pass.

#### Manual Verification:

- In `/docs`, as a Publisher, upload a valid hand-built ZIP and see 201
  `eligible`; upload a truncated ZIP and see 422 issues with no new row.
- Confirm OpenAPI no longer documents JSON `package_reference` registration.

---

## Phase 3: Publisher ZIP dialog

### Overview

Replace the path dialog with a ZIP file picker that posts multipart and shows
the existing structured 422 Banner. Explicit Publish stays on eligible cards.

### Changes Required:

#### 1. API client multipart register

**File**: `frontend/src/api.ts`

**Intent**: Send the ZIP with `FormData` so the browser sets the multipart
boundary. Stop always setting `Content-Type: application/json` for this call.

**Contract**: `registerModel` takes a `File` (or `Blob`) instead of
`{ package_reference }`. `ModelRegistration` is removed or replaced. 422
`issues[].reason` joining in `responseMessage` stays. `publishModel` unchanged.

#### 2. Registration dialog and models copy

**File**: `frontend/src/App.tsx`

**Intent**: Publisher selects a `.zip`. Copy talks about a complete HDFS
package ZIP, not a pre-staged directory or pipeline manifest. Eligible
registration notice and Publish button remain.

**Contract**: File input accepts ZIP only; no path text field. Empty state and
info strip match the new admission. Select-for-analysis stays published-only.
Do not invent client-side role hiding.

#### 3. Styles only if the file field needs them

**File**: `frontend/src/styles.css`

**Intent**: Reuse existing dialog/warning-strip patterns; add layout only if
the file input is unusable.

**Contract**: No new visual system; keep F-02 warning-strip for rejection
context if still accurate (API still never deserializes in-process).

### Success Criteria:

#### Automated Verification:

- `cd frontend && npm run build` completes without TypeScript or production
  build errors.

#### Manual Verification:

- As Publisher: upload a valid ZIP → eligible notice; Publish version still
  works; Select stays disabled until published.
- As Publisher: upload an invalid ZIP → Banner lists issue reasons; model
  list unchanged.
- As Operator: register still fails with the API 403 surfaced in the page
  error (controls may remain visible).
- Confirm no “pipeline manifest” or “pre-staged directory” product copy on
  the Models view.

---

## Phase 4: Bucket backend, Railway IaC, and docs

### Overview

Add the S3-compatible Bucket backend behind the same protocol, attach it in
Railway IaC for staging, and document ZIP admission. Pytest default remains
the filesystem backend.

### Changes Required:

#### 1. Bucket object-store backend

**File**: object-store adapter module, `src/api/settings.py`,
`requirements-api.txt`

**Intent**: When Bucket settings are present, put/delete-prefix uses the
private Railway Bucket. The API process still does not deserialize `.pt`.
Pin any new HTTP/S3 client in `requirements-api.txt` only.

**Contract**: Settings from Railway variable references (endpoint, bucket
name, access keys) — never baked into the React build. Validator env
allowlist continues to drop `AWS_*` and similar. No change to
`requirements-macos-intel.lock.txt`. Filesystem backend remains when Bucket
settings are unset (local and default pytest).

#### 2. Railway IaC and deploy-plan

**File**: `.railway/railway.ts`, `context/deployment/deploy-plan.md`

**Intent**: Provision the private Bucket in the same staging project/region as
`web` and PostgreSQL, and attach credentials to `web` by reference now that
the adapter exists.

**Contract**: Use the current `railway/iac` Bucket helper (do not invent a
legacy `railway.toml`). Non-staging apply still throws. Update deploy-plan:
workspace path registration is replaced for models; do not claim inference;
leave dataset object-kind to S-03 if still unused in production.

#### 3. Docs and PRD current-path note

**File**: `README.md`, `.env.example`, `context/foundation/prd.md`

**Intent**: Registration is ZIP multipart; directory `package_reference` is
not a public API. Object-store env is documented. PRD Open Question 2 no
longer says browser upload is deferred.

**Contract**: README package section matches the hand-built ZIP layout with
`manifest.json` at archive root. `.env.example` drops “API never accepts
artifact bytes.” Do not broaden MVP to BGL or training.

#### 4. Adapter unit tests without live Bucket

**File**: tests beside the adapter

**Intent**: Bucket backend is tested with a fake/S3 stub so CI stays
filesystem-default and does not require MinIO.

**Contract**: Protocol tests cover put and prefix delete. Default `test_api`
fixture still uses filesystem object root under the test workspace.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py tests/test_model_package.py tests/test_artifacts.py`
  and adapter tests pass outside cases that only fail from native sandbox
  limits.
- `ruff check src tests scripts run_ablation.py` and `mypy` pass.
- `cd frontend && npm run build` still passes.
- `git diff -- requirements-macos-intel.lock.txt` is empty.

#### Manual Verification:

- Read README + `/docs` and confirm ZIP upload, 422, eligible, and explicit
  publish are described consistently.
- If staging credentials are available, upload one ZIP and confirm the three
  declared objects exist under
  `projects/<project-id>/models/<id>/<version>/` and the DB row is
  `storage_kind=object` with checksum set. Skip live Bucket if the environment
  is not provisioned; filesystem staging of the adapter is then the recorded
  result.

---

## Testing Strategy

### Unit Tests:

- Declared-files copy ignores extras; refuses symlinks and `..`.
- Filesystem adapter put/delete-prefix and path-escape.
- Bucket backend via stub (no live network in default CI).
- ZIP caps / zip-slip remain in `tests/test_model_package.py`.

### Integration Tests:

- Publisher ZIP → 201 eligible + `model.registered`.
- Ineligible ZIP → 422 + empty list.
- Operator ZIP → 403.
- Duplicate manifest identity → 409 + no orphan prefix.
- Unpublished eligible → analysis 409.
- Published ZIP-admitted model → analysis still `not_supported`.
- `@pytest.mark.ml` dummy/pickle vs tensor ZIP/directory temp probe.

### Manual Testing Steps:

1. Publisher uploads a valid hand-built ZIP; sees eligible; publishes; cannot
   run inference yet.
2. Publisher uploads a ZIP missing evidence or with a pickle `.pt`; sees 422.
3. Operator cannot register; can still list models in-project.
4. Cross-project model id cannot start analysis (404).

## Performance Considerations

ZIP cap remains 32 MiB compressed / 96 MiB uncompressed / 64 members. The API
holds the archive and temp tree only for the 120s validator timeout window.
Object puts are three small files after eligibility.

## Migration Notes

Additive `004` for `model_versions` object-checksum CHECK. Existing workspace
kind rows (null checksum) remain valid. SQLite rebuilds the table; PostgreSQL
adds the constraint. Local `.api/analyzer.db` is still disposable if a
developer prefers reset over migrate. Railway staging that already applied
`003` must apply `004` forward. No backfill of old workspace packages into
object storage.

## References

- Related research: `context/changes/publish-hdfs-model-package/research.md`
- Frame brief: `context/changes/publish-hdfs-model-package/frame.md`
- F-02 contract: `src/modules/model_package.py`
- Current register/publish: `src/api/main.py:376-485`
- Deploy constraints: `context/deployment/deploy-plan.md:57-64`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Declared-files materialize and filesystem object store

#### Automated

- [x] 1.1 `python -m pytest tests/test_model_package.py tests/test_object_store.py` (or the chosen adapter test path) passes, including declared-files-only copy and filesystem prefix delete — 8a6d902
- [x] 1.2 `ruff check src/modules/model_package.py src/api tests/test_model_package.py` and `mypy` pass — 8a6d902

#### Manual

- [x] 1.3 Inspect one materialized prefix on disk: only `manifest.json`, declared `.pt`, and declared evidence; leftover ZIP members are absent — 8a6d902

### Phase 2: HTTP multipart ZIP admission

#### Automated

- [x] 2.1 `python -m pytest tests/test_api.py tests/test_model_package.py` passes, including ZIP 201 eligible, ineligible ZIP 422 with empty model list, Operator 403, duplicate 409, unpublished analysis 409, and retained `not_supported` after publish — 057ae3a
- [x] 2.2 `ruff check src/api tests/test_api.py` and `mypy` pass — 057ae3a

#### Manual

- [x] 2.3 In `/docs`, as a Publisher, upload a valid hand-built ZIP and see 201 `eligible`; upload a truncated ZIP and see 422 issues with no new row — 057ae3a
- [x] 2.4 Confirm OpenAPI no longer documents JSON `package_reference` registration — 057ae3a

### Phase 3: Publisher ZIP dialog

#### Automated

- [x] 3.1 `cd frontend && npm run build` completes without TypeScript or production build errors — 568e532

#### Manual

- [x] 3.2 As Publisher: upload a valid ZIP → eligible notice; Publish version still works; Select stays disabled until published — 568e532
- [x] 3.3 As Publisher: upload an invalid ZIP → Banner lists issue reasons; model list unchanged — 568e532
- [x] 3.4 As Operator: register still fails with the API 403 surfaced in the page error (controls may remain visible) — 568e532
- [x] 3.5 Confirm no “pipeline manifest” or “pre-staged directory” product copy on the Models view — 568e532

### Phase 4: Bucket backend, Railway IaC, and docs

#### Automated

- [x] 4.1 `python -m pytest tests/test_api.py tests/test_model_package.py tests/test_artifacts.py` and adapter tests pass outside cases that only fail from native sandbox limits — 6370900
- [x] 4.2 `ruff check src tests scripts run_ablation.py` and `mypy` pass — 6370900
- [x] 4.3 `cd frontend && npm run build` still passes — 6370900
- [x] 4.4 `git diff -- requirements-macos-intel.lock.txt` is empty — 6370900

#### Manual

- [x] 4.5 Read README + `/docs` and confirm ZIP upload, 422, eligible, and explicit publish are described consistently — 6370900
- [x] 4.6 If staging credentials are available, upload one ZIP and confirm the three declared objects exist under `projects/<project-id>/models/<id>/<version>/` and the DB row is `storage_kind=object` with checksum set. Skip live Bucket if the environment is not provisioned; filesystem staging of the adapter is then the recorded result — 6370900
