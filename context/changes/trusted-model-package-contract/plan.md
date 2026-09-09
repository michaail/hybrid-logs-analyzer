# Trusted model package contract Implementation Plan

## Overview

Define and enforce a non-executable HDFS model-package contract before a model
can enter the workflow. A Publisher-authorized package is checked for
completeness, declared HDFS compatibility, evidence presence, file integrity,
and a tensor-only `.pt` payload. The PyTorch payload probe runs in a dedicated,
minimally privileged package-validation process; it does not run the model.
This change does not store uploads in object storage or enable isolated
inference.

## Current State Analysis

Admission today is a trusted-workspace pipeline-run pointer, not a package
contract. `POST /projects/{project_id}/models` calls `validate_pipeline_model`
in `src/api/validation.py`, which requires a JSON run manifest, HDFS
`dataset`, a finite `best_threshold`, and a file at
`outputs/hdfs/<run_id>/attribute_gae.pt`. It never opens the checkpoint. API
tests therefore register dummy bytes. Explicit publish already exists and
stays a separate audited action.

The training path still writes a pickle checkpoint loaded with
`weights_only=False`: `src/modules/model.py` `load_checkpoint`,
`run_ablation.py` graph bundles, and notebooks. The ablation checkpoint mixes
`model_state_dict` with architecture scalars. Health-check, tech-stack, and
`AGENTS.md` forbid passing uploaded artifacts to that loader. Analysis runs
intentionally finish as `not_supported` /
`INFERENCE_CONTRACT_UNAVAILABLE` until a later inference slice.

`src/modules/models/gae.py` `AttributeAwareGAE` is what later reconstruction
needs (`node_dim`, `edge_dim`, `hidden_dim`, `latent_dim`,
`gine_aggregation`, `node_transformation`). F-02 only declares and type-checks
those fields, its state-dict format, input-normalization vectors, and the
`alpha` / `beta` / `gamma` scoring weights. It must not instantiate the
network or call `forward`.

The public API is deliberately free of PyTorch and model deserialization:
`requirements-api.txt` contains only control-plane dependencies and
`src/api/main.py` states that it never deserializes uploaded artifacts. A
`weights_only=True` probe is still a PyTorch deserialization operation, so it
cannot run in the registration request process.

## Desired End State

A reusable validator accepts a package directory, or a zip that unpacks to
one, inside the trusted workspace. The isolated package-validation process,
not the public API, checks that `manifest.json` matches the closed Pydantic
contract; `source_compatibility` is `hdfs`; metrics include a finite
`best_threshold`; `evidence.json` is present; SHA-256 of every declared file
matches; and the artifact is an `attribute-aware-gae-v1`
`weights_only=True` tensor state dict. Its complete format-specific tensor key
set, shapes, and dtypes must agree with the declared architecture and scoring
configuration. Extra undeclared files do not fail eligibility but still count
toward zip resource caps. Zip-slip, nested archives, and oversize archives
are rejected.

The current registration API accepts only a pre-staged, immutable directory
package. It stores the validated package identity, actual artifact path,
artifact digest, metrics, architecture metadata, and evidence path, then
remains `eligible` until explicit publish. It does not store a ZIP-member
reference. F-01/S-02 later validate ZIP transport and materialize only
declared files under private immutable storage before calling the same
directory contract. Operators still cannot register. Dummy-byte checkpoints,
pipeline-manifest-only requests, and direct ZIP references are ineligible.
Inference stays `not_supported`.

### Key Discoveries:

- Current admission never inspects `.pt` bytes and accepts dummy files:
  `src/api/validation.py:31-70`, `tests/test_api.py:94-115`.
- Ablation checkpoints are combined pickle dicts, not tensor-only state
  dicts: `run_ablation.py:600-613`.
- `load_checkpoint` uses `weights_only=False`: `src/modules/model.py:82-84`.
- Reconstruction target is `AttributeAwareGAE`, not `GraphAutoEncoder`:
  `src/modules/models/gae.py:69-77`.
- `alpha`, `beta`, and `gamma` are part of the thresholded anomaly score, and
  edge normalization is fitted before training: `run_ablation.py:513-518,
  525-548`.
- Tech-stack already names immutable package keys and checksums in
  PostgreSQL; F-01 owns durable Bucket storage, not this change:
  `context/foundation/tech-stack.md:75-97`.
- Frontend `responseMessage` only surfaces string `detail`, so structured
  422 reports need a join of issue reasons: `frontend/src/api.ts:283-299`.

## What We're NOT Doing

- Browser or HTTP multipart upload of package bytes (S-02).
- Direct ZIP registration or storage of an opaque `<zip>#<member>` artifact
  reference. ZIP transport is validated by the reusable contract now and
  materialized by F-01/S-02 later.
- Shared durable Bucket/PostgreSQL object storage beyond additive
  model-version columns needed to record a validated package (F-01).
- Isolated inference, `AttributeAwareGAE` construction, `forward`, or
  changing `not_supported` / `INFERENCE_CONTRACT_UNAVAILABLE` (S-04). The
  separate package-validation process is limited to static package checks and
  a restricted tensor deserialization probe; it is not an inference runtime.
- A pipeline package exporter (`run_ablation.py` stays unchanged).
- Cryptographic publisher signatures.
- Scoring model quality; evidence and metrics are presence/completeness
  checks only.
- Non-HDFS `source_compatibility`, including BGL.
- Changing notebook `weights_only=False` research loaders.
- Regenerating `requirements-macos-intel.lock.txt`.

## Implementation Approach

Put the contract in reusable modules and a private package-validation process,
then switch the existing Publisher registration path to consume its typed
result. The canonical unit is a directory whose root contains `manifest.json`.
A zip is only a transport that must unpack to that directory under hard
resource caps. The reusable validator accepts either source, but the current
HTTP request accepts only a pre-staged immutable directory
`package_reference`; it rejects direct ZIP sources. Identity, metrics,
architecture, evidence, and checksums come from the package, not from extra
request fields.

Keep explicit publish, project isolation, and audit actions. Add an additive
migration for package path and artifact digest; do not rewrite `001_initial_schema`.
Hand-built fixtures are the producer until a later exporter or S-02 upload
exists. The API sends only a resolved package reference to the private
validator and rejects malformed or unavailable validator responses; it never
imports PyTorch, opens the artifact, or receives model bytes.

## Critical Implementation Details

### Timing & lifecycle

The API requests validation before any `model_versions` insert or
`model.registered` audit row. The dedicated validation process performs the
`weights_only=True` probe and returns a typed report. A failed, malformed, or
unavailable validation response must leave no eligible row.

### State sequencing

Do not extract a zip in place inside the trusted workspace. The reusable
validator unpacks to a process-local temporary directory, validates, and
deletes it. F-02 does not register such a temporary package. Its registration
route accepts only a pre-staged immutable directory and stores actual
workspace-relative paths to its declared artifact and evidence. Later S-02
must validate its ZIP, then copy only declared files into an immutable F-01
storage location before it asks this route to register that directory. Every
future artifact resolver must recheck the manifest and declared digests before
use; no component may infer a model from a ZIP member fragment. Extra files
may remain in the temporary zip extraction; eligibility ignores them.

### Security

Only the package-validation process may call
`torch.load(path, map_location="cpu", weights_only=True)` and then accept
only a mapping of tensor values (a state dict). Its runtime has the minimum
ML dependencies, a scrubbed environment with no application or Bucket secrets,
no unnecessary network access, and access only to the package source. The API
must never call `load_checkpoint`, import PyTorch, use `weights_only=False`,
pickle-load, or construct `AttributeAwareGAE`. Reject zip members with
absolute paths, `..` segments, or nested archive extensions before extraction.

---

## Phase 1: Directory package contract and validator

### Overview

Encode the closed manifest schema and validate an unpacked directory without
running the model.

### Changes Required:

#### 1. Package schema

**Files**: `src/modules/model_package.py` (new; split schema/report types into
an adjacent module only if the file would mix unrelated concerns),
`src/model_validator/` (new), `requirements-model-validator.txt` (new),
`requirements-api.txt`

**Intent**: Declare the inspectable package contract that admission and later
inference reconstruction will share, and execute its PyTorch probe outside the
public API process.

**Contract**: Pydantic models with `extra="forbid"` on the manifest.
Required manifest fields:

- `model_identifier` and `version` using the existing
  `^[A-Za-z0-9_.-]+$` length limits
- `source_compatibility` literal `"hdfs"`
- optional `pipeline_run_id` string
- `metrics` object that must contain a finite numeric `best_threshold`;
  additional metric keys are allowed
- `format` literal `"attribute-aware-gae-v1"`, whose contract is tied to the
  versioned `AttributeAwareGAE` tensor schema
- `architecture` object with positive `node_dim`, `hidden_dim`, `latent_dim`;
  non-negative `edge_dim`; `gine_aggregation` in `sum|mean|max`;
  `node_transformation` in `mlp|linear`; `edge_mean` / `edge_std` that are
  both null or finite equal-length vectors of exactly `edge_dim` values, with
  each standard deviation at least `0.1`
- `scoring` object with finite non-negative `alpha`, `beta`, and `gamma`,
  with at least one positive value
- `files.artifact` and `files.evidence` as relative POSIX paths
- `files.checksums` mapping each declared file path to a lowercase hex
  SHA-256

Fixed root file: `manifest.json`. Default declared names may be `model.pt`
and `evidence.json`. Extra manifest keys are rejected. Keep
`requirements-api.txt` Torch-free. `requirements-model-validator.txt` is a
separate, pinned runtime contract for this minimal validator process; it must
not alter `requirements-macos-intel.lock.txt`.

#### 2. Directory validator

**File**: `src/modules/model_package.py`

**Intent**: Collect every completeness, compatibility, and integrity failure
for a directory package, including a restricted tensor probe run only by the
package-validation process.

**Contract**: Public function
`validate_model_package(root: Path) -> PackageValidationResult` where
`issues` is a list of `{path, reason}` and the result is valid only when the
list is empty. Checks, all collected rather than fail-fast:

- `manifest.json` exists, is UTF-8 JSON, and matches the schema
- declared paths stay inside `root` (no `..`, no absolute paths)
- declared files exist as regular files
- SHA-256 of each declared file matches `files.checksums`
- evidence file exists and is non-empty JSON object (contents are not scored)
- artifact suffix is `.pt`
- `torch.load(..., map_location="cpu", weights_only=True)` returns a
  non-empty tensor state dict that exactly matches the
  `attribute-aware-gae-v1` key set, tensor shapes, and permitted dtypes
  derived from the manifest architecture

Undeclared sibling files do not add issues. Do not hash or schema-check them.
The static schema includes `raw_node_norm`, `node_proj`, `edge_proj`, the
branch-specific `encoder_conv.nn`, `node_decoder`, and `edge_decoder` state
keys plus BatchNorm buffers. It rejects missing, unexpected, non-tensor, or
shape/dtype-incompatible entries. This proves executable compatibility with
the declared format without constructing `AttributeAwareGAE`; it does not
score model quality.

The package-validation process performs the required probe:

```python
payload = torch.load(artifact_path, map_location="cpu", weights_only=True)
```

#### 3. Validator tests and fixtures

**Files**: `tests/test_model_package.py` (new),
`tests/test_model_validator.py` (new), `tests/fixtures/model_packages/` as
needed

**Intent**: Prove eligibility and rejection without the HTTP stack, using
hand-built packages rather than a pipeline exporter, and prove the API cannot
deserialise an artifact when the validator fails or is unavailable.

**Contract**: Non-ML tests cover schema, missing files, SHA mismatch, extra
files accepted, extra manifest keys rejected, non-HDFS compatibility,
missing/non-finite threshold, path escape in declared names, empty evidence.
`@pytest.mark.ml` tests cover a tiny real state-dict `.pt` accepted and a
pickle / `weights_only=False`-style payload rejected. Do not instantiate
`AttributeAwareGAE`. Validator-process tests prove that its report is typed,
that a stripped environment is used, and that the public API runtime has no
Torch import or artifact-loading call path. Include format-specific fixtures
for each `node_transformation` branch and negative cases for a missing,
unexpected, wrong-shape, or wrong-dtype state key; inconsistent normalization
vectors; and missing/invalid scoring weights.

### Success Criteria:

#### Automated Verification:

- Focused package tests cover the directory contract cases above, including
  extra-file acceptance and pickle-payload rejection.
- Focused validator-process tests prove its restricted execution boundary and
  typed report behavior.
- `ruff check src/modules/model_package.py tests/test_model_package.py` and
  `mypy` pass.

#### Manual Verification:

- Inspect one valid fixture directory and one invalid fixture and confirm the
  validator report paths match the broken fields.

**Implementation Note**: After completing this phase and all automated
verification passes, pause for human confirmation that the fixture reports
are readable before proceeding.

---

## Phase 2: Zip transport and resource limits

### Overview

Accept a zip only as transport onto the directory contract, with zip-slip and
bomb protections.

### Changes Required:

#### 1. Zip unpack helper

**File**: `src/modules/model_package.py`

**Intent**: Turn a Publisher zip into a temporary directory the Phase 1
validator can check, without trusting member names or unbounded size.

**Contract**: Public entry
`validate_model_package_source(path: Path) -> PackageValidationResult`.
If `path` is a directory, validate in place. If it is a zip:

- reject nested `.zip` / `.tar` / `.tgz` / `.gz` members
- reject member names that are absolute or contain `..`
- reject more than 64 members
- reject compressed archive size above 32 MiB
- reject total uncompressed `file_size` above 96 MiB
- extract into a private temporary directory, run the directory validator,
  then delete the temp tree

Resource-limit and zip-slip failures append structured issues; they do not
raise raw `zipfile` traces to API clients. Extra members inside the zip are
extracted and ignored by eligibility, but they consume the 64-file and size
caps. This public helper is not an admission-storage operation: it deletes its
temporary extraction and returns no artifact reference for a ZIP member.

#### 2. Zip safety tests

**File**: `tests/test_model_package.py`

**Intent**: Lock zip-slip, oversize, nested-archive, and happy-path zip
unpack behavior.

**Contract**: Include a zip whose members escape the extract root; a zip
that exceeds the uncompressed cap; a zip containing a nested archive; a zip
that unpacks to a valid directory package. Extra undeclared members must not
fail a otherwise valid zip under the caps.

### Success Criteria:

#### Automated Verification:

- Zip-slip, nested-archive, oversize, extra-member, and valid-zip cases pass
  in `tests/test_model_package.py`.
- `ruff check src/modules/model_package.py tests/test_model_package.py` and
  `mypy` pass.

#### Manual Verification:

- Confirm a valid fixture zip and an oversize or zip-slip zip produce
  structured issues with no files written outside the temp extract root.

**Implementation Note**: After completing this phase and all automated
verification passes, pause for human confirmation that zip extraction cannot
write outside the temp directory.

---

## Phase 3: Admission API, persistence, and thin UI

### Overview

Replace pipeline-manifest registration with package-reference admission while
keeping explicit publish and `not_supported` analysis.

### Changes Required:

#### 1. Additive model-version columns

**File**: `src/api/migrations.py`

**Intent**: Record the validated package location and artifact digest without
rewriting `001_initial_schema`.

**Contract**: Migration `002_model_package_admission` adds
`package_reference TEXT NOT NULL DEFAULT ''` and
`artifact_sha256 TEXT NOT NULL DEFAULT ''` on `model_versions`. Existing
`pipeline_run_id`, `artifact_reference`, `metrics_json`, `metadata_json`, and
`external_evaluation_evidence` remain. New rows always write real package
values from a pre-staged directory; empty defaults exist only for
pre-migration local rows. `package_reference` remains a resolvable directory
path, never an archive/member compound.

#### 2. Registration request and response

**Files**: `src/api/schemas.py`, `src/api/storage.py`, `src/api/main.py`,
`src/model_validator/`

**Intent**: Make the package the source of identity and eligibility; stop
accepting pipeline-run manifests and dummy checkpoints.

**Contract**: `ModelRegistrationRequest` contains only `package_reference`
(non-empty path). Resolve it with the existing trusted-workspace file/dir
rule (reject path escape) and reject non-directory or ZIP sources with the
same structured 422 shape. The API passes only the resolved directory source
reference to the private validator and validates its typed response; the
validator calls `validate_model_package`. On any issue, return HTTP 422 whose
`detail` is
`{"valid": false, "issues": [{"path": str, "reason": str}, ...]}`. On
success, insert `eligible` with:

- `model_identifier` / `version` from the manifest
- `pipeline_run_id` from optional manifest field, else `model_identifier`
- `package_reference` as the workspace-relative source path
- `artifact_reference` as the workspace-relative declared `.pt` path beneath
  the registered directory; it must name a regular physical file, not an
  archive/member fragment
- `artifact_sha256` from the manifest checksum
- `metrics_json` from manifest metrics
- `metadata_json` containing the format, architecture, and scoring objects
- `external_evaluation_evidence` as the declared evidence relative path

Retain unique `(project_id, model_identifier, version)` 409. Publisher-only
register/publish, Operator 403, cross-project 404, and `model.registered` /
`model.published` audit names stay. Remove `validate_pipeline_model` from
the admission path. Do not start inference.

`ModelVersionResponse` adds `package_reference` and `artifact_sha256`.

#### 3. API tests

**File**: `tests/test_api.py`

**Intent**: Replace `_write_trusted_manifest` dummy-byte registration with
hand-built valid/invalid packages.

**Contract**: Cover: valid directory package → 201 `eligible`; direct ZIP
package → structured 422 because direct ZIP admission is unavailable;
pickle/dummy `.pt` → 422 with artifact issue; SHA mismatch collects together
with other issues in one 422; BGL/`source_compatibility` rejection; path
outside workspace → 422; Operator 403; duplicate version 409; publish still
Publisher-only; analysis of a published model still `not_supported` /
`INFERENCE_CONTRACT_UNAVAILABLE`. No remaining test may register via
`pipeline_run_manifest`. Cover unavailable or malformed private validator
responses as a safe no-insert API failure. Prove that registration does not
import Torch or load the package in the API process.

#### 4. Thin registration UI

**Files**: `frontend/src/api.ts`, `frontend/src/App.tsx`

**Intent**: Point the existing dialog at a workspace package path and show
structured eligibility failures. This is not a file-upload control.

**Contract**: `ModelRegistration` is `{ package_reference: string }`.
`ModelVersion` includes `package_reference` and `artifact_sha256`.
`responseMessage` joins `detail.issues[].reason` when `detail` is the
structured report. The dialog keeps the “no browser artifact upload”
warning, drops pipeline-manifest / freeform-evidence / metadata JSON
fields, and still does not send model bytes.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py tests/test_model_package.py` passes,
  including structured 422 and retained `not_supported` analysis.
- The public API package test environment remains Torch-free; validator tests
  exercise the separate ML runtime.
- Generated OpenAPI exposes `package_reference` registration and no
  `pipeline_run_manifest` field.
- `ruff check src/api tests/test_api.py` and `mypy` pass.
- `cd frontend && npm run build` completes without TypeScript errors.

#### Manual Verification:

- As a Publisher, register a valid fixture package through `/docs` and the
  React dialog; confirm `eligible` then explicit publish.
- Submit an invalid package and confirm the UI lists issue reasons.
- Confirm an Operator cannot register, and a published model still yields
  `not_supported` analysis.

**Implementation Note**: After completing this phase and all automated
verification passes, pause for human confirmation that the dialog and
`/docs` flow match the package contract before documentation updates.

---

## Phase 4: Verification and documentation

### Overview

Align operator-facing docs with the resolved package contract and run the
established checks.

### Changes Required:

#### 1. Documentation

**Files**: `README.md`, `context/foundation/prd.md`

**Intent**: Replace pipeline-manifest admission language with the trusted
package contract and record the resolved format decision.

**Contract**: Document directory layout, zip transport caps, SHA-256,
`attribute-aware-gae-v1` state-dict key/shape/dtype rule, architecture,
normalization, and scoring fields, evidence-file presence, HDFS-only
compatibility, the isolated package-validation boundary, and that inference
remains unavailable. Close PRD open question 2 with: pretrained PyTorch `.pt`
state dict inside the package contract (format, architecture,
input-normalization/scoring configuration, metrics with `best_threshold`,
HDFS compatibility, evidence file). Keep “no browser upload” until S-02.
Explain that current registration accepts only a pre-staged directory; direct
ZIP registration waits for S-02 to materialize declared files in F-01 storage.
Never put secrets in examples.

#### 2. Full change verification

**Files**: `tests/`, `frontend/`, `README.md`

**Intent**: Prove the admission boundary with the project toolchain without
changing the Intel lockfile.

**Contract**: Run API, package, and artifact tests used by local
verification; Ruff; mypy; frontend production build. Native ML-marked
package tests may fail in the restricted sandbox; distinguish
shared-memory environment crashes from assertion failures.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py tests/test_artifacts.py tests/test_model_package.py`
  passes outside the cases that only fail from native sandbox limits.
- `ruff check src tests scripts run_ablation.py` and `mypy` pass.
- `cd frontend && npm ci && npm run build` passes.

#### Manual Verification:

- Follow README to register a hand-built HDFS package, publish it, and
  observe `not_supported` analysis with no `torch.load(..., weights_only=False)`
  on the uploaded artifact or any PyTorch deserialization in the API process.
- Review OpenAPI and the UI warning to confirm bytes are still not uploaded
  from the browser.

**Implementation Note**: After completing this phase and all automated
verification passes, pause for human confirmation that the documented
admission path matches the running API before declaring the change ready
to archive.

## Testing Strategy

### Unit Tests:

- Closed manifest schema, threshold, HDFS literal, architecture enums.
- SHA-256 mismatch and path-escape declared files.
- Extra undeclared files do not fail; extra manifest keys do.
- Tensor-only state dict accepted; pickle payload rejected under
  `weights_only=True`.
- Every required `attribute-aware-gae-v1` state key, tensor shape, and dtype;
  both `node_transformation` branches; paired normalization vectors; and
  finite non-negative scoring weights.
- The `attribute-aware-gae-v1` static state-dict schema rejects incompatible
  key sets, tensor shapes/dtypes, normalization vectors, and scoring weights
  without constructing the model.
- Public API remains free of Torch imports and package loading; an unavailable
  or malformed validator response creates no model row or audit event.
- Zip-slip, nested archive, size and file-count caps.

### Integration Tests:

- Publisher package_reference admission, Operator denial, duplicate 409.
- Structured 422 collects multiple issues.
- Explicit publish unchanged; analysis remains `not_supported`.
- Cross-project 404 retained.

### Manual Testing Steps:

1. Build a minimal pre-staged directory package by hand (manifest,
   evidence.json, tiny state-dict `.pt`, matching checksums).
2. Register and publish it as a Publisher in the selected project.
3. Attempt the same path as Operator; confirm 403.
4. Break checksum, swap in a pickle `.pt`, and submit a direct ZIP; confirm
   structured rejection and no eligible row. Exercise a zip-slip ZIP through
   the reusable validator tests.
5. Start analysis on the published model and confirm `not_supported`.

## Performance Considerations

Package checks are bounded by the 32 MiB / 96 MiB / 64-file caps. SHA-256
over a GAT `.pt` at that size is acceptable for one active thesis user. Do
not add caching, background workers, or persistent extract directories.

## Migration Notes

Additive `002_model_package_admission` only. Apply with
`python -m src.api.migrations`. Local databases created under `001` gain
empty package columns; they are not valid packages until re-registered.
The first Railway deploy of this revision applies `001` then `002` on an
empty database. Do not rewrite `001_initial_schema`.

## References

- Product requirements: `context/foundation/prd.md:59-72,89-93,137-145`
- Roadmap foundation: `context/foundation/roadmap.md:110-123`
- Stack security boundary: `context/foundation/tech-stack.md:40-43,88-95`
- Health-check deserialization rule: `context/foundation/health-check.md:140-155`
- Current admission: `src/api/validation.py:22-70`, `src/api/main.py:368-421`
- Unsafe research loader: `src/modules/model.py:82-84`
- Ablation checkpoint shape: `run_ablation.py:600-613`
- Reconstruction architecture: `src/modules/models/gae.py:47-77`
- API tests to replace: `tests/test_api.py:94-115,343-457`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Directory package contract and validator

#### Automated

- [x] 1.1 Focused package tests cover the directory contract cases above, including extra-file acceptance and pickle-payload rejection — e7c0c15
- [x] 1.2 `ruff check src/modules/model_package.py tests/test_model_package.py` and `mypy` pass — e7c0c15

#### Manual

- [x] 1.3 Inspect one valid fixture directory and one invalid fixture and confirm the validator report paths match the broken fields — e7c0c15

### Phase 2: Zip transport and resource limits

#### Automated

- [x] 2.1 Zip-slip, nested-archive, oversize, extra-member, and valid-zip cases pass in `tests/test_model_package.py` — f43b37a
- [x] 2.2 `ruff check src/modules/model_package.py tests/test_model_package.py` and `mypy` pass — f43b37a

#### Manual

- [x] 2.3 Confirm a valid fixture zip and an oversize or zip-slip zip produce structured issues with no files written outside the temp extract root — f43b37a

### Phase 3: Admission API, persistence, and thin UI

#### Automated

- [x] 3.1 `python -m pytest tests/test_api.py tests/test_model_package.py` passes, including structured 422 and retained `not_supported` analysis — ae085a4
- [x] 3.2 Generated OpenAPI exposes `package_reference` registration and no `pipeline_run_manifest` field — ae085a4
- [x] 3.3 `ruff check src/api tests/test_api.py` and `mypy` pass — ae085a4
- [x] 3.4 `cd frontend && npm run build` completes without TypeScript errors — ae085a4

#### Manual

- [x] 3.5 As a Publisher, register a valid fixture package through `/docs` and the React dialog; confirm `eligible` then explicit publish — ae085a4
- [x] 3.6 Submit an invalid package and confirm the UI lists issue reasons — ae085a4
- [x] 3.7 Confirm an Operator cannot register, and a published model still yields `not_supported` analysis — ae085a4

### Phase 4: Verification and documentation

#### Automated

- [x] 4.1 `python -m pytest tests/test_api.py tests/test_artifacts.py tests/test_model_package.py` passes outside the cases that only fail from native sandbox limits
- [x] 4.2 `ruff check src tests scripts run_ablation.py` and `mypy` pass
- [x] 4.3 `cd frontend && npm ci && npm run build` passes

#### Manual

- [x] 4.4 Follow README to register a hand-built HDFS package, publish it, and observe `not_supported` analysis with no `torch.load(..., weights_only=False)` on the uploaded artifact
- [x] 4.5 Review OpenAPI and the UI warning to confirm bytes are still not uploaded from the browser
