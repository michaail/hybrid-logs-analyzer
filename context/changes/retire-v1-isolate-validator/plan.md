# Retire v1 and Isolate Validator Implementation Plan

## Overview

Stop admitting `attribute-aware-gae-v1`, delete leftover v1 (or null-bundle)
model rows through a one-off administrator CLI, and move the Torch
`weights_only=True` probe behind a private HTTP validator service. Compose
provisioning stays a later workstream.

## Current State Analysis

The approved product contract is already v2-only
(`context/foundation/prd.md`, `context/foundation/mvp-alignment-plan.md`).
The running admission path still treats v1 as eligible.

`src/modules/model_package.py` defaults `PACKAGE_FORMAT` to
`attribute-aware-gae-v1` and accepts both format literals. v1 may omit
`preprocessing_bundle`; v2 must declare it. `validate_packaged_release` in
`src/modules/inference_bundle.py` still accepts a v1 package with no companion
bundle.

`src/api/validation.py` `admit_uploaded_zip_package` unpacks the ZIP in the
API process, then runs `python -m src.model_validator <dir> [bundle-dir]`
with a 120s timeout and a scrubbed environment. v1 without a bundle proceeds;
v1 with a bundle is rejected. After a valid report, declared files are put
in the object store and the DB row is created last. A published v1 cannot
start analysis (`409` “not inference-ready”) because
`preprocessing_bundle_id` is null (`src/api/main.py`).

Format lives in `metadata_json.format`, not a column
(`src/api/migrations.py`, `_package_metadata`). `analysis_runs.model_version_id`
references `model_versions(id)` with no `ON DELETE CASCADE`. `audit_events`
has no FK to models.

The validator is still a local CLI (`src/model_validator/__main__.py`). There
is no HTTP app, no `Dockerfile.validator`, and no Railway service.
`requirements-model-validator.txt` pins Torch only. The public `Dockerfile`
is Torch-free. Inference already shows the private-HTTP pattern: Bearer token,
connect/read timeouts, all-or-nothing URL+token in `ApiSettings.from_environment`.

Tests and E2E still seed v1. `tests/fixtures/model_packages/valid_files` is
v1 with no bundle. `scripts/e2e_package.py` copies it. Playwright
`registerPackage` uploads only the package ZIP.
`tests/fixtures/hdfs_inference_release/` already has a v2 package + bundle.
API tests inject `model_validator_command` (files-only helper); one
`@pytest.mark.ml` test invokes the real module.

### Key Discoveries:

- Cleanup can use dialect-agnostic Python over `metadata_json` rather than
  SQLite `json_extract` vs Postgres `->>` (`src/api/storage.py` stores JSON
  text).
- `delete_prefix` exists on both filesystem and Bucket stores and is already
  the failed-admission rollback (`src/api/validation.py`).
- Default `python -m src.model_validator` in the Torch-free API image tends
  to 422 (probe `ImportError` becomes a typed issue), not 503. That is not
  an isolation boundary.
- Lesson: validate before storage writes; create the DB row last; roll back
  prefixes on later failure. Lesson: do not treat stubbed HTTP as proof of
  the Torch probe — keep `@pytest.mark.ml` coverage of the real loader.
- Lesson: do not commit generated binaries; pin checksums if a fixture must
  stay large.

## Desired End State

A Publisher uploading `attribute-aware-gae-v1` receives a structured `422`
and no model row. The only successful registration is `attribute-aware-gae-v2`
plus its bound preprocessing-bundle ZIP. README and the register UI no longer
describe v1 as an upload format. `feature_contract: notebook_raw_v1` remains
graph-feature semantics.

An administrator can dry-run, then apply, a CLI that deletes leftover
`format=attribute-aware-gae-v1` or `preprocessing_bundle_id IS NULL` package
prefixes and then those model rows. Rows with `analysis_runs` are skipped;
the command exits non-zero if any were skipped. Audit events remain.

Package admission calls a private validator HTTP service with the original
ZIP bytes. That service extracts in its own temp dir, runs the existing
tensor probe, and returns `PackageValidationResult`. It has no database,
object-store, or JWT credentials. Tests may still inject
`model_validator_command`. If neither HTTP settings nor a command are set,
registration is `503`. A dedicated `Dockerfile.validator` exists.
`.railway/railway.ts` and `deploy-plan.md` describe the service as unexecuted
future design. Compose is unchanged.

## What We're NOT Doing

- Docker Compose stack, named volumes, or local acceptance procedure
  (`compose-acceptance`).
- Re-running `scripts/verify_hdfs_parity.py` or committing `releases/` /
  `data/` / `artifacts/` binaries (`verify-evidence`).
- v1 runtime compatibility, dual-format admission, or rewriting
  `feature_contract: notebook_raw_v1`.
- Deleting `analysis_runs`, anomaly/provisional results, or audit events.
- Giving the validator `DATABASE_URL`, Bucket keys, or `API_JWT_SECRET`.
- Claiming Railway staging is proven.
- Opening a new `/10x-roadmap` milestone.
- Regenerating `requirements-macos-intel.lock.txt`.

## Implementation Approach

Phase 1 ships the cleanup CLI against the current schema so leftovers can be
removed before the gate flips. Phase 2 makes v1 a contract and admission
failure and converts fixtures, pytest, E2E, and user-facing copy. Phase 3
adds the HTTP validator, API client, image, and unexecuted Railway wiring,
keeping the injectable command for focused tests.

## Critical Implementation Details

Run the cleanup CLI (or document that the operator ran it) before merging
the Phase 2 admission gate into an environment that already has v1 rows.
The implementer must not add `ON DELETE CASCADE`.

Validator HTTP read timeout must stay on the order of the current 120s
subprocess budget; do not copy inference’s 5s read timeout — `torch.load`
is slower than an empty execute POST.

`/health` on the validator must not open a database or object store. Railway
`model-validator` must not receive `sharedStore` or `API_JWT_SECRET`.

API zip preview rejects v1 / missing bundle before the HTTP call. The
package contract also refuses v1 so a token-holder cannot admit v1 by calling
the validator directly.

When `model_validator_command` is set (tests), use that subprocess path and
do not require HTTP settings. When it is unset, require
`MODEL_VALIDATOR_SERVICE_URL` and `MODEL_VALIDATOR_INTERNAL_TOKEN` together;
if both pairs are absent, raise `ValidatorUnavailableError` (HTTP 503). Do
not fall back to `python -m src.model_validator` inside the API image.

Keep `preprocessing_bundle` as `File(default=None)`. An omitted or empty
bundle is a typed admission issue, not a Starlette missing-field 422.

---

## Phase 1: Administrator v1 cleanup

### Overview

Give an administrator a bootstrap-style CLI that inventories leftover v1 /
null-bundle models, deletes their object prefixes, then deletes only rows
with no analysis-run dependents.

### Changes Required:

#### 1. Retire CLI

**File**: `src/api/retire_v1.py` (new; `__main__` entry `python -m src.api.retire_v1`)

**Intent**: One-off administrator cleanup, not a silent migration. Default
is dry-run.

**Contract**: Load `ApiSettings.from_environment()` and `ApiDatabase` /
`build_object_store` like bootstrap. Flags: `--dry-run` (default) and
`--apply`. Identify candidates where parsed `metadata_json.format` is
`attribute-aware-gae-v1` **or** `preprocessing_bundle_id` is null. Do not
treat `feature_contract: notebook_raw_v1` as a package format. For each
candidate: if `COUNT(analysis_runs WHERE model_version_id = id) > 0`, skip
it (dependent). If `storage_kind` is not `object` or `package_reference` is
empty, skip it (not an object-prefix leftover) and do not call
`delete_prefix`. Else `object_store.delete_prefix(package_reference)` (and
the bundle’s `object_prefix` only when a bundle row exists), then `DELETE`
the `model_versions` row. Do not delete audit events. Print every candidate
and action. Exit `0` when every object-kind candidate was applied or the
dry-run listed them with no dependent skips; exit `1` when any row was
skipped because of dependents (including dry-run, so the operator sees
leftovers). Workspace-kind skips do not by themselves force exit `1`. Do
not prompt for a password.

#### 2. Storage helpers

**File**: `src/api/storage.py`

**Intent**: Keep SQL in the existing database module; parse JSON in Python
so SQLite and Postgres stay on one path.

**Contract**: Add list-all-model-versions (or equivalent scan), count runs
for a model id, and delete a model version by id. No schema migration. FK
restrict remains. Deleting a row that still has runs must fail closed if a
race appears.

#### 3. Cleanup tests

**File**: `tests/test_retire_v1.py` (new)

**Intent**: Prove dry-run is a no-op, apply deletes objects and rows, and
dependent rows are skipped with a non-zero exit.

**Contract**: Use the existing sqlite test database + filesystem object
store. Seed: (a) v1-format null-bundle **object-kind** model with objects,
(b) null-bundle row with an `analysis_runs` FK, (c) a v2+bundle model that
must survive, (d) a null-bundle **workspace-kind** row whose
`package_reference` is not an object prefix. Assert prefixes gone only for
(a); (b) row remains (exit 1); (c) untouched; (d) skipped without
`delete_prefix` and without forcing exit 1 by itself; audit rows remain if
seeded.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_retire_v1.py -m "not ml"` passes
- `ruff check src/api/retire_v1.py tests/test_retire_v1.py`
- `python -m src.api.retire_v1 --help` shows `--dry-run` and `--apply`

#### Manual Verification:

- Owner confirms the dry-run listing is readable (candidate id, format,
  bundle-null, run count, action) and that blocked rows are an acceptable
  leftover until those runs are retired separately

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase. Phase
blocks use plain bullets — the corresponding `- [ ]` checkboxes for these
items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: v2-only admission

### Overview

Make v1 a structured 422 at the contract and ZIP-preview layers, convert
default fixtures and E2E to v2+bundle, and remove user-facing v1 upload copy.

### Changes Required:

#### 1. Package contract

**File**: `src/modules/model_package.py`

**Intent**: v1 is not a valid manifest. Tensor schema stays AttributeAwareGAE;
`feature_contract: notebook_raw_v1` stays a feature name.

**Contract**: `format` is only `attribute-aware-gae-v2`. `PACKAGE_FORMAT`
aliases v2. `preprocessing_bundle` is required. A v1 format string is a
manifest issue (typed `PackageValidationIssue`), not a successful validate.
Reword the unexpected-state-dict message that still says
“attribute-aware-gae-v1” if it would be read as a package format.

#### 2. Packaged release

**File**: `src/modules/inference_bundle.py`

**Intent**: `validate_packaged_release` never accepts a v1 package or a
missing bundle.

**Contract**: Drop the v1 “bundle not allowed / skip bundle” branch. v2
without `bundle_root` remains an issue. Keep bundle-ref matching.

#### 3. Admission preview and persist

**File**: `src/api/validation.py`

**Intent**: Cheap 422 before the validator process/HTTP; persist only v2.

**Contract**: After ZIP size checks, read `manifest.json` from the package
ZIP (zip member, no Torch). If format is v1 or `preprocessing_bundle` is
absent, return issues and put nothing. Missing companion ZIP for v2 is the
same 422. Remove the “v1 must not include a bundle” success path. Keep
validate-then-put-then-DB-row and `delete_prefix` on later failure.

#### 4. Register route copy

**File**: `src/api/main.py`

**Intent**: The multipart field is required for the only accepted format.

**Contract**: Keep `preprocessing_bundle: UploadFile | None = File(default=None)`
so an omitted part still reaches the handler. Reject missing or empty bundle
bytes in `admit_uploaded_zip_package` with typed `{valid, issues[]}` (same
envelope as today). Do not use `File(...)` — Starlette’s missing-field 422
is not `PackageValidationResult`, and the UI only unwraps `detail.issues`.
Description no longer says “required for v2”; the UI and E2E still always
send the bundle file.

#### 5. Fixtures and test helpers

**Files**: `tests/fixtures/model_packages/`, `tests/test_model_package.py`,
`tests/test_api.py`, `tests/test_inference_bundle.py`,
`tests/test_model_validator.py`

**Intent**: Happy path is v2+bundle. One committed v1 ZIP/dir remains as a
422 oracle.

**Contract**: Convert `valid_files` (or point helpers at
`tests/fixtures/hdfs_inference_release/`) to v2 package + bundle. Add
`rejected_v1/` (name may vary) used only to assert 422 / invalid. Change
`_manifest_payload` / `_zip_staged` defaults to v2+bundle. Rewrite tests that
expect `201` on bare v1 (`test_model_publication_and_safe_analysis_run_lifecycle`,
`test_registration_accepts_zip_and_persists_declared_files_only`,
`test_http_admission_uses_real_validator_probe`,
`test_unpublished_eligible_model_cannot_start_analysis`) to use v2+bundle
or, for publication-lifecycle 409, a different non-ready condition if still
needed. Add an explicit test: v1 ZIP → 422, empty model list. Do not commit
Colab `releases/` binaries.

#### 6. E2E seed and register

**Files**: `scripts/e2e_package.py`, `frontend/e2e/helpers/packages.ts`,
`frontend/e2e/helpers/publication.ts`, Playwright specs under `frontend/e2e/`

**Intent**: Browser publication uses v2+bundle. Ineligible still fails on
empty evidence, not on format.

**Contract**: Seed script writes a package ZIP and a bundle ZIP. Helpers
upload both inputs. `reject-ineligible-hdfs-model.spec.ts` still matches
evidence rejection, not a v1 format error. Eligible specs still expect 201.

#### 7. UI and README

**Files**: `frontend/src/App.tsx`, `frontend/src/api.ts`, `README.md`

**Intent**: Operators/Publishers are not told v1 is a supported upload.

**Contract**: Remove “legacy packages stay visible but cannot run” and
“Preprocessing-bundle ZIP (required for v2)”. Bundle file is required in
the register dialog (empty bundle cannot submit / API 422). README example
tree and format line are v2+bundle only; delete “V1 uses the `package` field
only”. Keep archive docs immutable.

#### 8. PRD lag sentences

**File**: `context/foundation/prd.md`

**Intent**: The follow-on named in US-01 / FR-002 is this change.

**Contract**: Remove “The running app may still admit v1 until that change
lands” and equivalent lag wording. Keep `retire-v1` only if it still names
historical cleanup, or drop the follow-on once the gate exists. Do not
rewrite Current System Overview.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_model_package.py tests/test_inference_bundle.py tests/test_api.py tests/test_model_validator.py -m "not ml"` passes
- `rg -n "V1 uses the" README.md` has no matches
- `rg -n "legacy packages stay visible" frontend/src/App.tsx` has no matches
- `rg -n "The running app may still admit v1" context/foundation/prd.md` has no matches
- `ruff check src/modules/model_package.py src/modules/inference_bundle.py src/api/validation.py src/api/main.py tests/test_api.py tests/test_model_package.py`
- `npm --prefix frontend run test:e2e`

#### Manual Verification:

- Owner confirms README and the register dialog describe only v2+bundle, and
  that a v1 ZIP is rejected with a structured issue (UI or API)

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase. Phase
blocks use plain bullets — the corresponding `- [ ]` checkboxes for these
items live in the `## Progress` section at the bottom of the plan.

---

## Phase 3: Private validator HTTP service

### Overview

Put the Torch probe behind a token-gated HTTP service, switch production
admission to that client, and describe (not prove) the Railway service.

### Changes Required:

#### 1. Validator HTTP app

**Files**: `src/model_validator/` (new service module; keep directory CLI)

**Intent**: Receive ZIP bytes, extract privately, probe, return the typed
report. No application secrets.

**Contract**: FastAPI app factory. `GET /health` → `{"status": "ok"}` without
DB or object-store. `POST /internal/packages/validate` with Bearer token
(`hmac.compare_digest`, same unauthorized copy style as
`src/inference_service/main.py`) and multipart fields for the package ZIP
and required bundle ZIP. Extract with existing `unpack_zip_bytes` into a
process-local temp dir, run `validate_release_with_probe`, return
`PackageValidationResult` JSON. Size caps unchanged. On extract/probe
typed issues, HTTP 200 with `valid: false` (API maps that to 422). Auth
failure 401. Do not read `API_JWT_SECRET`, `DATABASE_URL`, or Bucket env.
Scrub process env on startup like the CLI. Directory CLI
`python -m src.model_validator <package-root> [bundle-root]` remains for
command-injected tests.

#### 2. API settings and client

**Files**: `src/api/settings.py`, `src/api/validation.py`, `.env.example`,
`README.md`

**Intent**: Match inference’s all-or-nothing private-service settings.
Tests keep injecting `model_validator_command`.

**Contract**: New optional `model_validator_service_url` and
`model_validator_internal_token`, loaded from
`MODEL_VALIDATOR_SERVICE_URL` / `MODEL_VALIDATOR_INTERNAL_TOKEN` together
or neither. Connect timeout default 2s; read timeout default 120s (probe
budget). `run_private_package_validator` (or replacement): if
`model_validator_command` is set, keep the subprocess directory path; else
if URL+token are set, POST the original ZIP bytes (do not unpack for the
probe in the API) using stdlib `http.client` multipart, with the same
scheme/host/timeout constraints as `post_inference_execute`; do not add
`httpx` to `requirements-api.txt`; else raise `ValidatorUnavailableError`. Map HTTP 401/5xx,
timeouts, and malformed JSON to that error (API already returns 503). Do
not retry like inference unless a single retry on 503 is clearly justified;
admission should fail closed. Never log the token. `from_environment` must
not default the command to `python -m src.model_validator`. Document on
`.env.example` and in the README factory/`uvicorn` section that register
requires `MODEL_VALIDATOR_SERVICE_URL` and `MODEL_VALIDATOR_INTERNAL_TOKEN`
together. Point local UI smoke at `scripts/e2e_serve.py` (it already injects
the files-only command). Do not restore a hidden module fallback.

#### 3. Validator image

**Files**: `Dockerfile.validator`, `requirements-model-validator.txt`

**Intent**: Slim Torch+HTTP image, separate from the fat inference image and
the Torch-free API image.

**Contract**: `FROM python:3.10-slim`, install validator requirements
(existing Torch pin plus FastAPI/uvicorn/multipart as needed), copy `src`,
non-root user, `PORT` default 8080, CMD the validator ASGI app. No JWT, no
DB client requirement. Do not regenerate `requirements-macos-intel.lock.txt`.

#### 4. Unexecuted Railway wiring

**Files**: `.railway/railway.ts`, `context/deployment/deploy-plan.md`

**Intent**: Future private service in IaC and prose. Not a validated staging
claim.

**Contract**: Add private `model-validator` service from
`Dockerfile.validator`, no public domain, no `sharedStore`, no
`API_JWT_SECRET`. Shared env `MODEL_VALIDATOR_INTERNAL_TOKEN`. `web` gets
`MODEL_VALIDATOR_SERVICE_URL` (private DNS, e.g.
`http://model-validator.railway.internal:8080`) and the token. Validator
sleep-when-idle is allowed. deploy-plan: name the service, state it is
unexecuted / not proof of Railway staging, and that Compose (later) is the
MVP deployment proof. Do not rewrite the rest of the Railway procedure.

#### 5. Validator tests

**Files**: `tests/test_model_validator.py`, `tests/test_api.py` (admission
client cases)

**Intent**: Cover valid, invalid, unauthorized, unavailable, and secret
isolation. Keep a real Torch probe on `@pytest.mark.ml`.

**Contract**: FastAPI `TestClient` against the validator app: 401 without
token; 200 `valid: false` for the committed v1 oracle and for an invalid
v2; 200 `valid: true` can be files-level if the probe is stubbed in unit
tests. Secret-isolation: validator settings/env reject or omit JWT/DB/Bucket
keys; logs must not contain the token. API tests: command injected →
unchanged files-only path; URL+token with a stub HTTP server or TestClient
double; neither configured → register 503 and no row. Add
`@pytest.mark.ml` coverage that hits the real `weights_only=True` path
through the validator app (not only a stubbed 200).

#### 6. Alignment stamp

**File**: `context/foundation/mvp-alignment-plan.md`

**Intent**: These two workstreams are this change.

**Contract**: Mark `retire-v1` and `isolated-validator` `done`. Leave
`compose-acceptance` and `verify-evidence` `pending`.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_model_validator.py tests/test_api.py -m "not ml"` passes
- `test -f Dockerfile.validator` succeeds
- `rg -n "model-validator" .railway/railway.ts` matches
- `rg -n "MODEL_VALIDATOR_SERVICE_URL" src/api/settings.py` matches
- `rg -n "MODEL_VALIDATOR_SERVICE_URL" README.md .env.example` matches
- `ruff check src/model_validator src/api/settings.py src/api/validation.py`

#### Manual Verification:

- Owner confirms deploy-plan/Railway text still reads as unexecuted future
  design (not a proven staging deployment), and that the validator service
  env in IaC has neither JWT nor object-store credentials
- Owner confirms the `@pytest.mark.ml` validator-app `weights_only=True`
  probe passed in a normal local ML venv (not Cursor’s sandbox, not Ubuntu CI)

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase. Phase
blocks use plain bullets — the corresponding `- [ ]` checkboxes for these
items live in the `## Progress` section at the bottom of the plan.

---

## Testing Strategy

### Unit Tests:

- Manifest/format: v1 string → issues; v2 without bundle → issues; v2+bundle
  directory contract still valid (Torch-free).
- Cleanup: dry-run no deletes; apply deletes prefix+row; skip+exit 1 with
  dependents; v2+bundle survivor; audit rows remain.
- Validator HTTP: 401, typed invalid, token not logged.

### Integration Tests:

- API register v1 ZIP → 422, `GET .../models == []`.
- API register v2+bundle → 201, `inference_ready true` (files-only command).
- API with neither command nor URL → 503, no row.
- `@pytest.mark.ml`: real `python -m src.model_validator` and/or validator
  app TestClient with a tiny tensor state dict.
- Playwright: eligible v2+bundle publish; ineligible empty evidence 422.

### Manual Testing Steps:

1. `python -m src.api.retire_v1 --dry-run` against a local sqlite (or read
   the test output) and confirm skip/apply wording.
2. Register a v1 ZIP in the UI or via curl; confirm 422 and no list entry.
3. Register v2+bundle; confirm eligible.
4. Read deploy-plan validator paragraph: unexecuted, no JWT/store on that
   service.

## Performance Considerations

Admission gains one HTTP hop. Bound connect at 2s and read at 120s. Do not
add inference-style five retries on validation — a stuck probe should fail
closed.

## Migration Notes

No schema migration. Operators apply `python -m src.api.retire_v1 --apply`
on each environment that may contain v1 rows **before** relying on the
Phase 2 gate there. Rows skipped due to `analysis_runs` remain until those
runs are retired in a later change. Audit history is retained with dangling
`resource_id`s.

## References

- Alignment source: `context/foundation/mvp-alignment-plan.md`
- Product contract: `context/foundation/prd.md`
- Inference HTTP pattern: `src/api/inference_dispatch.py`,
  `src/inference_service/main.py`
- Current subprocess validator: `src/model_validator/__main__.py`,
  `src/api/validation.py` `run_private_package_validator`
- Lessons: object-store rollback; real ML subprocess; no generated binaries
  in Git

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Administrator v1 cleanup

#### Automated

- [x] 1.1 `python -m pytest tests/test_retire_v1.py -m "not ml"` passes — fdc6ef1
- [x] 1.2 `ruff check src/api/retire_v1.py tests/test_retire_v1.py` — fdc6ef1
- [x] 1.3 `python -m src.api.retire_v1 --help` shows `--dry-run` and `--apply` — fdc6ef1

#### Manual

- [x] 1.4 Owner confirms the dry-run listing is readable (candidate id, format, bundle-null, run count, action) and that blocked rows are an acceptable leftover until those runs are retired separately — fdc6ef1

### Phase 2: v2-only admission

#### Automated

- [x] 2.1 `python -m pytest tests/test_model_package.py tests/test_inference_bundle.py tests/test_api.py tests/test_model_validator.py -m "not ml"` passes
- [x] 2.2 `rg -n "V1 uses the" README.md` has no matches
- [x] 2.3 `rg -n "legacy packages stay visible" frontend/src/App.tsx` has no matches
- [x] 2.4 `rg -n "The running app may still admit v1" context/foundation/prd.md` has no matches
- [x] 2.5 `ruff check src/modules/model_package.py src/modules/inference_bundle.py src/api/validation.py src/api/main.py tests/test_api.py tests/test_model_package.py`
- [x] 2.7 `npm --prefix frontend run test:e2e`

#### Manual

- [x] 2.6 Owner confirms README and the register dialog describe only v2+bundle, and that a v1 ZIP is rejected with a structured issue (UI or API)

### Phase 3: Private validator HTTP service

#### Automated

- [ ] 3.1 `python -m pytest tests/test_model_validator.py tests/test_api.py -m "not ml"` passes
- [ ] 3.2 `test -f Dockerfile.validator` succeeds
- [ ] 3.3 `rg -n "model-validator" .railway/railway.ts` matches
- [ ] 3.4 `rg -n "MODEL_VALIDATOR_SERVICE_URL" src/api/settings.py` matches
- [ ] 3.7 `rg -n "MODEL_VALIDATOR_SERVICE_URL" README.md .env.example` matches
- [ ] 3.5 `ruff check src/model_validator src/api/settings.py src/api/validation.py`

#### Manual

- [ ] 3.6 Owner confirms deploy-plan/Railway text still reads as unexecuted future design (not a proven staging deployment), and that the validator service env in IaC has neither JWT nor object-store credentials
- [ ] 3.8 Owner confirms the `@pytest.mark.ml` validator-app `weights_only=True` probe passed in a normal local ML venv (not Cursor’s sandbox, not Ubuntu CI)
