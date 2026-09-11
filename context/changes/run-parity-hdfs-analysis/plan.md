# Run parity-preserving HDFS analysis Implementation Plan

## Overview

Turn a published HDFS model and an admitted HDFS log dataset into a durable,
asynchronous, block-level anomaly-analysis run. The public FastAPI control plane stays
free of PyTorch and Drain3; a private, on-demand inference service verifies and
materializes only the bound model and preprocessing assets, then writes terminal results
through the existing CAS transition seam.

The plan establishes an executable, parity-preserving inference contract. It does not
claim FR-011 complete until the selected labelled baseline release is supplied and its
metric gate passes.

## Current State Analysis

The product already has project-scoped model and dataset upload, a durable
`analysis_runs` state model, transactional audit/result persistence, and a React view
that polls `queued` and `running` status. The analysis endpoint deliberately creates
the terminal `not_supported` result; no ML runner or object-store read interface exists
yet.

`run_ablation.py` can create the necessary training-stage assets, but it trains Drain
from raw input and stores its parser state, templates, embeddings, and checkpoint as
separate workspace artifacts. The currently admitted `attribute-aware-gae-v1` package
contains only a tensor-state-dict, evidence, and manifest. It cannot recreate the graph
features required to score a new raw HDFS log.

The selected solution decisions are:

- Capture an approved baseline release before calling the feature parity-preserving.
- Store an immutable preprocessing bundle separately from the model package, bound to
  the model version by database identity and checksums.
- Fail an analysis run when any admitted line does not match the frozen Drain snapshot.
- Persist one anomaly result per HDFS `block_id`, with its contributing log context.
- Dispatch the private service after the API has acknowledged `queued`; transient
  activation errors retain the queued run rather than becoming terminal failures.
- Expose only `queued`, `running`, `completed`, and `failed` publicly in S-04. Detailed
  step progress remains deferred.
- Show stable error codes and safe explanations to Operators; diagnostics remain private.
- Require a golden processing fixture, isolated-service integration, API lifecycle tests,
  and a later full-corpus parity gate.
- Gate later baseline verification on test F1, PR-AUC, ROC-AUC, and the exact selected
  decision threshold.

## Desired End State

An Operator chooses a published HDFS inference release and an accepted same-project HDFS
dataset, receives a fast `202` response with a `queued` run, and can observe it reach
`running`, `completed`, or `failed`. A completed run stores a block-level anomaly count,
normal-block count, and rows with block IDs, scores, threshold, level, and bounded source
context. A failed run exposes only a stable code and safe execution message.

Only a model package bound to a verified immutable preprocessing bundle can run. The
bundle contains the frozen Drain snapshot and its exact configuration plus an ordered
cluster-ID-to-embedding array. The inference process refuses checksum mismatches,
unknown/missing embeddings, malformed assets, and unmatched admitted log lines. It does
not fit Drain, call enrichment, retrain, or make a model-selection decision.

When the selected baseline corpus and reference release exist, a release-only command
recomputes its core metrics and accepts the release only when each delta is at most 0.01
and the threshold is exactly equal.

### Key Discoveries:

- `POST /projects/{project_id}/analysis-runs` already authorizes a published,
  same-project model and dataset but persists `not_supported`
  (`src/api/main.py:511-551`).
- `ApiDatabase.transition_analysis_run()` already atomically enforces
  `queued → running → completed|failed`, stores result rows, and adds audits
  (`src/api/storage.py:830-909`).
- HDFS inference must load the frozen parser and use `annotate_file()`, not
  `fit_file()` (`src/modules/parser/drain_parser.py:148-188, 238-252`).
- `build_pyg_dataset()` substitutes a zero embedding and skips graph conversion errors;
  the inference contract must override both permissive behaviours
  (`src/modules/dataset.py:151-186, 303-309`).
- The selected stack explicitly calls for an on-demand private service, not a polling
  worker (`context/foundation/tech-stack.md:53-69, 109-113`).

## What We're NOT Doing

- Training, retraining, model selection, notebook replacement, or a BGL execution path.
- A polling worker, WebSockets, percentage progress, live log streaming, or operational
  alert integrations.
- Permitting legacy `attribute-aware-gae-v1` packages to execute without the bound
  preprocessing bundle.
- Accepting an uploaded model with `torch.load(..., weights_only=False)` or loading model
  data in the public API process.
- Silently dropping unmatched template lines or zero-filling missing embeddings.
- Full-corpus browser upload; the labelled corpus is a controlled release verification
  input, not an Operator upload.
- Regenerating `requirements-macos-intel.lock.txt`.

## Implementation Approach

Introduce an additive HDFS inference-release format while preserving existing v1
admission/readability. A Publisher uploads the v2 model ZIP and its companion
preprocessing-bundle ZIP in one registration request. The control plane validates both
archives through the existing scrubbed validator boundary, writes their declared members
to distinct immutable object prefixes, and persists a project-owned
`preprocessing_bundles` row linked to the created model version.

The public API creates a queued run and schedules a bounded asynchronous request to the
private inference service. The service accepts only a shared internal invocation token,
uses the shared database and object store, claims the run by CAS, verifies all persisted
checksums into an ephemeral directory, runs the frozen inference path, and atomically
persists the terminal state. It receives no JWT secret and never trusts caller-supplied
object references.

## Critical Implementation Details

**State sequencing.** Persist `queued` before dispatching. The inference service may
execute a run only after winning `queued → running`; duplicate private invocations see a
CAS conflict and perform no work. The service computes all output first, then performs
the one `running → completed` transition that writes summary, rows, and audit together.

**Inference inputs.** The raw uploaded dataset has already passed whole-file syntax
validation, but this does not prove it matches the frozen parser. Count source lines
during annotation and fail with `UNMATCHED_TEMPLATE` on the first unmatched line,
including only a capped safe set of line numbers in the public execution report.

## Phase 1: Capture the approved baseline release

### Overview

Convert the user-supplied, trained HDFS notebook/headless-run output into one explicit
baseline release definition before accepting the feature as parity-preserving. This phase
is an external prerequisite: it begins only when the trained model, labelled held-out
corpus, selected configuration, and expected values are available.

### Changes Required:

#### 1. Baseline-release record and controlled artefacts

**Files**: `context/changes/run-parity-hdfs-analysis/baseline.md` (new),
`configs/hdfs_baseline.yaml` (new), and the ignored workspace release directory

**Intent**: Record one immutable parity oracle instead of selecting the newest notebook
output or inferring configuration from execution state.

**Contract**: Capture the exact code commit, source notebook or `run_ablation.py` path,
full resolved configuration, model state-dict SHA-256, Drain snapshot/config SHA-256,
templates/embeddings SHA-256, labelled corpus SHA-256, ordered block IDs, expected test
F1/PR-AUC/ROC-AUC, and exact threshold. `baseline.md` is filled only from the supplied,
reviewed training output; no placeholder values or guessed metrics are permitted.

#### 2. HDFS inference-release exporter

**Files**: `src/modules/inference_release.py` (new), `run_ablation.py`,
`tests/test_pipeline_smoke.py`

**Intent**: Export trusted training artefacts into the model ZIP and separate
preprocessing-bundle ZIP without making notebooks the sole production path.

**Contract**: Given explicit completed-stage paths and the resolved HDFS configuration,
write atomically:

- an `attribute-aware-gae-v2` model package containing a tensor-only `model.pt`,
  manifest, and evidence; and
- a preprocessing bundle containing a manifest, exact `drain.ini`, frozen
  `drain_parser.bin`, and `embeddings.npz` with ordered integer `cluster_ids` and finite
  float32 `embeddings`.

The exporter rejects smoke/test outputs and incomplete HDFS artefacts. It copies only
the trained `model_state_dict` into `model.pt`; it does not package the training graph
bundle or use a public untrusted loader.

### Success Criteria:

#### Automated Verification:

- A focused ML test exports a synthetic HDFS training result, validates both archives,
  and proves the model state dict, parser, config, and embeddings are explicit declared
  files with stable checksums.
- The exporter rejects BGL, smoke-mode, missing-label, missing-parser, and missing
  embedding inputs.
- `ruff check src/modules/inference_release.py run_ablation.py tests/test_pipeline_smoke.py`,
  `mypy`, and focused pytest pass.

#### Manual Verification:

- The human records the selected trained baseline's provenance and core metric values in
  `baseline.md`, then confirms the exported release matches those SHA-256 values.

**Implementation Note**: Pause after this phase. The human must confirm that the supplied
baseline—not a synthetic test fixture—is the approved parity oracle before package
admission or release verification proceeds.

---

## Phase 2: Bind and admit immutable preprocessing bundles

### Overview

Extend the trusted package contract and persistence model so executable v2 model releases
are cryptographically and project-scopedly bound to a separately stored preprocessing
bundle. Existing v1 packages remain readable/registrable but are not inference-eligible.

### Changes Required:

#### 1. V2 package and preprocessing-bundle contracts

**Files**: `src/modules/model_package.py`, `src/modules/inference_bundle.py` (new),
`src/model_validator/runtime.py`, `src/model_validator/__main__.py`

**Intent**: Validate the model and preprocessing inputs before either is persisted or
loaded for inference.

**Contract**: Support `attribute-aware-gae-v1` and `attribute-aware-gae-v2` manifests.
V2 requires a descriptor for bundle identifier/version/digest and matches it against the
uploaded bundle manifest. Bundle validation permits exactly the declared regular files,
enforces relative POSIX paths, SHA-256 checksums, the supplied Drain config/state,
`np.load(..., allow_pickle=False)`, unique integer cluster IDs, finite float32
embedding rows, nonzero dimensions, and architecture-compatible node dimensions.
The validator process returns typed issues and retains its scrubbed environment.

#### 2. Immutable bundle persistence

**Files**: `src/api/migrations.py`, `src/api/storage.py`, `src/api/schemas.py`,
`src/api/object_store.py`

**Intent**: Make the preprocessing bundle an independently immutable, project-scoped
resource rather than unchecked JSON in a model row.

**Contract**: Add a forward migration with a `preprocessing_bundles` table and nullable
`model_versions.preprocessing_bundle_id` FK. The bundle owns project ID, stable
identifier/version, object prefix, manifest checksum, metadata JSON, and creation time;
it is unique per project identifier/version. Add object key helpers and a private
`get(key) -> bytes` protocol operation for filesystem and Bucket implementations.
Persist the exact declared members at
`projects/<project-id>/preprocessing-bundles/<bundle-id>/<version>/...`; model and
dataset reads remain project-scoped and checksum verified by the consumer.

#### 3. Publisher admission path

**Files**: `src/api/validation.py`, `src/api/main.py`, `tests/test_model_package.py`,
`tests/test_model_validator.py`, `tests/test_object_store.py`,
`tests/test_shared_state_repository.py`, `tests/test_api.py`

**Intent**: Admit the companion bundle in the same Publisher action as its v2 model,
without giving the public API a Torch loader.

**Contract**: Extend model registration multipart input with a required
`preprocessing_bundle` ZIP for v2 and reject a bundle supplied for v1. Validate both
before writes; materialize the declared members under separate prefixes; create the
bundle and model link in one database transaction; delete both prefixes on any
post-persist conflict. The response exposes a non-sensitive inference-readiness/bundle
identity field. v1 registration remains supported but published v1 models are rejected
as not inference-ready when an analysis is requested.

### Success Criteria:

#### Automated Verification:

- Contract tests cover v1 compatibility; v2 success; missing, swapped, symlinked,
  undeclared, path-escaping, checksum-mismatched, pickle-enabled NPZ, non-finite,
  duplicate-cluster, and dimension-mismatched bundle files.
- Object-store tests cover authenticated consumer reads in filesystem and fake Bucket
  backends, including missing-key and path-escape failures.
- Migration and repository tests prove same-project binding, foreign-project rejection,
  model/bundle atomic rollback, and no orphaned objects after registration failure.
- API tests prove Publisher-only multipart admission; valid v2 storage of separate
  prefixes; legacy v1 compatibility; and no Torch import in API sources.
- Ruff, mypy, and all focused non-ML tests pass; ML contract tests run with
  `@pytest.mark.ml`.

#### Manual Verification:

- Register the approved v2 release as a Publisher and inspect its distinct model and
  preprocessing-bundle object prefixes plus its project-scoped model metadata.

**Implementation Note**: Pause after this phase. Confirm that legacy models remain
non-executable and that the new model cannot be linked to a bundle from another project.

---

## Phase 3: Implement the private, on-demand inference service

### Overview

Create an isolated Linux ML service that receives only a protected run ID, reconstructs
the frozen HDFS pipeline from verified artefacts, and performs block-level scoring.

### Changes Required:

#### 1. Service-specific configuration and launch surface

**Files**: `src/inference_service/settings.py` (new),
`src/inference_service/main.py` (new), `src/inference_service/runner.py` (new),
`src/inference_service/__main__.py` (new), `requirements-inference.txt` (new),
`Dockerfile.inference` (new), `.env.example`

**Intent**: Separate ML execution credentials and Linux dependencies from the public
control plane and the intentional Intel macOS lockfile.

**Contract**: The private service receives only `DATABASE_URL`, object-store settings,
code root, and a dedicated internal invocation token; it must reject absent/invalid
tokens and must never require `API_JWT_SECRET`. Its endpoint accepts a run UUID only.
Pin and test a Linux-compatible Torch/PyG/Drain3 dependency set independently of
`requirements-macos-intel.lock.txt`. The inference image runs as a non-root user with an
ephemeral working directory.

#### 2. Frozen HDFS inference runner

**Files**: `src/inference_service/runner.py`, `src/modules/parser/drain_parser.py`,
`src/modules/dataset.py`, `src/api/storage.py`, `tests/test_inference_service.py` (new)

**Intent**: Compose reusable modules without their notebook training, enrichment, or
permissive fallbacks.

**Contract**: Resolve the run, published v2 model, bound bundle, and dataset through
project-scoped repository queries; retrieve and checksum every object into a temporary
directory. Load the parser with the materialized `drain.ini`, annotate without fitting,
and retain source line numbers. Fail `UNMATCHED_TEMPLATE` on any line without a match and
`MISSING_CLUSTER_EMBEDDING` on any unknown cluster ID. Build HDFS sequences, use frozen
embeddings directly, normalize edge attributes with manifest statistics, instantiate the
declared GAE, and load the state dict only with `weights_only=True`.

Compute scores in `eval()` mode with manifest `alpha`, `beta`, and `gamma`; classify
strictly using `score > best_threshold`. Store one row per anomalous `block_id` with
score, level, threshold, matched-line count, and capped source-line/raw-context evidence.
Completed summaries provide at least anomaly and normal block counts; no per-line normal
rows are stored.

#### 3. Run claim and private idempotency

**Files**: `src/api/storage.py`, `tests/test_shared_state_repository.py`,
`tests/test_inference_service.py`

**Intent**: Make duplicate or concurrent private service invocations harmless without
adding a polling queue.

**Contract**: Add a project-safe lookup for all execution inputs and use the existing
CAS transition to claim `queued → running`. A second invocation of the same run returns
an idempotent no-op after the CAS conflict. Terminal errors use the selected safe public
shape: `MODEL_LOAD_FAILED`, `PREPROCESSING_BUNDLE_UNAVAILABLE`, `PARSER_FAILED`,
`UNMATCHED_TEMPLATE`, `MISSING_CLUSTER_EMBEDDING`, or `INFERENCE_FAILED`, with private
causal detail logged by the service. Audit actor remains null/system for transitions;
the original requester is preserved on the run record.

### Success Criteria:

#### Automated Verification:

- Isolated-service tests prove a valid frozen tiny HDFS release completes from
  `queued` through `running` to `completed`, writes block-level rows, and never imports
  the inference package from the API process.
- Failure tests cover invalid internal token, absent/corrupt/checksum-mismatched objects,
  mismatched model/bundle metadata, unmatched lines, unknown cluster IDs, state-dict
  loading failure, and duplicate invocation.
- Repository tests prove terminal errors preserve a safe report/code and that completion
  inserts summary, rows, and audit atomically.
- Ruff and mypy pass on service and changed repository paths; focused ML tests run in the
  Linux inference environment.

#### Manual Verification:

- Invoke the private endpoint against a local v2 release and verify only the selected
  project’s dataset/model are materialized in its temporary workspace; inspect the
  completed run from the public API as an Operator.

**Implementation Note**: Pause after this phase. Confirm that the public API image
remains Torch-free and the inference container has no JWT secret before adding dispatch.

---

## Phase 4: Queue dispatch and coarse Operator lifecycle

### Overview

Replace the terminal `not_supported` path for inference-ready v2 models with a durable
queued request and bounded private-service activation, while retaining the existing
five-second frontend polling model.

### Changes Required:

#### 1. Asynchronous private dispatch

**Files**: `src/api/inference_dispatch.py` (new), `src/api/settings.py`,
`src/api/main.py`, `.env.example`, `tests/test_api.py`

**Intent**: Start on-demand inference after issuing a fast acknowledgement without
embedding a worker loop or ML dependency in FastAPI.

**Contract**: Add the private service URL, invocation token, bounded connect/read
timeouts, and a finite cold-start retry policy to API settings. `POST /analysis-runs`
still validates membership, published model, same-project dataset, and model bundle
readiness, then stores `queued` with null completion/error fields and schedules private
dispatch after returning `202`. Dispatch failures remain queued, are logged safely, and
never fabricate completion; the service owns terminal state transitions. A v1 model
returns a clear conflict before any run is created.

#### 2. Operator-facing state and result copy

**Files**: `frontend/src/App.tsx`, `frontend/src/api.ts`, `README.md`,
`context/deployment/deploy-plan.md`

**Intent**: Remove the obsolete “valid requests finish not supported” promise and make
the current run lifecycle understandable without expanding into S-05 result UX.

**Contract**: Preserve the existing polling interval and status badges. On creation,
display queued acknowledgement; for a failed run, render the safe execution report and
error code already returned by the API. The existing results dialog displays the
persisted aggregate summary and block anomaly rows; no percentage or per-stage API/UI
fields are introduced. Documentation records the new local three-process flow and the
private Railway service boundary, without suggesting a polling worker.

#### 3. Railway topology

**Files**: `.railway/railway.ts`, `context/deployment/deploy-plan.md`

**Intent**: Deploy the control plane and the finite ML service with independently scoped
credentials while maintaining one shared PostgreSQL database and private Bucket.

**Contract**: Add a private inference service built from `Dockerfile.inference`, with
database and object-store references plus its invocation token. Keep `web` on
`requirements-api.txt`, omit ML dependencies and object materialization from it, and
never put either internal token or Bucket keys in the frontend build. Do not add a
long-lived polling process, heartbeat, or public inference route.

### Success Criteria:

#### Automated Verification:

- API integration tests assert `202 queued` for an inference-ready published v2 model,
  existing `409`/`404` authorization failures, v1 non-readiness rejection, and no new
  public status/result writer.
- Dispatcher tests simulate first-attempt startup failure followed by successful retry,
  exhausted retry that preserves `queued`, and safe log-only network errors.
- TypeScript build, Ruff, mypy, focused API tests, and the public API Torch-import guard
  pass.
- Railway IaC type/check command validates the two-service staging topology without
  applying infrastructure.

#### Manual Verification:

- As an Operator, upload/select an accepted HDFS dataset, start a v2 run, observe
  queued/running/completed or failed status refresh, and inspect its block summary.
- Confirm an invalid dataset still fails at upload with `422`, and the browser receives
  neither the internal invocation token nor object-store credentials.

**Implementation Note**: Pause after this phase. Human confirmation must include a
staging cold-start observation and confirmation that a transient activation leaves an
honest queued record rather than a misleading terminal success.

---

## Phase 5: Golden processing and release parity verification

### Overview

Make processing drift visible on a small versioned fixture and metric drift measurable on
the approved labelled baseline. This phase becomes executable only after Phase 1’s
baseline artefacts are approved.

### Changes Required:

#### 1. Golden inference fixture

**Files**: `tests/fixtures/hdfs_inference_release/` (new),
`tests/test_hdfs_inference_parity.py` (new)

**Intent**: Detect parser, ordering, feature, normalisation, score, and strict-threshold
drift before a full-corpus release check.

**Contract**: Store a small HDFS raw-log fixture, trusted v2 release inputs, expected
ordered block IDs, selected graph topology/features, scores, decisions, and capped
context. The test asserts all lines match, block ordering and source references are
exact, features and scores meet documented numerical tolerances, and predictions equal
the strict manifest threshold decision.

#### 2. Controlled full-corpus parity gate

**Files**: `scripts/verify_hdfs_parity.py` (new),
`tests/test_hdfs_inference_parity.py`, `README.md`

**Intent**: Verify FR-011 from explicit provenance rather than normal Operator uploads
that lack labels.

**Contract**: The command accepts explicit baseline-release paths/IDs only, verifies
corpus and artefact checksums, emits a machine-readable comparison report, and exits
nonzero when test F1, PR-AUC, or ROC-AUC changes by more than 0.01 or the threshold
changes at all. It is `@pytest.mark.ml`/release-gate work, not a default web or
lightweight CI check. Record the report alongside the baseline release without replacing
the immutable expected values.

### Success Criteria:

#### Automated Verification:

- The golden fixture passes in the supported inference environment and fails
  deterministically when a graph feature, score, ordered block, parser checksum, or
  decision threshold is altered.
- Parity-command tests prove missing/changed corpus or artefact checksums and metric
  deltas above 0.01 fail; exact threshold equality is enforced.
- Ruff, mypy, and all focused tests pass; full baseline verification runs successfully
  outside Cursor’s restricted native-library sandbox.

#### Manual Verification:

- Run the parity command against the human-approved baseline corpus and attach its
  generated comparison report to the release evidence before declaring FR-011 satisfied.

**Implementation Note**: Pause after this phase. A human must review the generated
metric report and confirm that the named baseline, exact threshold, and all three metric
deltas meet the agreed acceptance rule.

## Testing Strategy

### Unit Tests:

- V1/v2 model manifest and preprocessing-bundle validation, including safe NPZ loading,
  checksums, dimensions, and malicious archive paths.
- Object-store reads, checksum verification, project-scoped bundle lookup, and atomic
  bundle/model registration rollback.
- Frozen parser annotation accounting, strict unmatched-line failure, no zero embedding
  fallback, edge normalisation, block-level result construction, and score thresholding.
- Dispatcher configuration/token validation, bounded retry, and no terminal mutation on
  unavailable service.

### Integration Tests:

- Publisher registers a v2 release, publishes it, and Operator starts a queued run
  against a same-project dataset; foreign/unpublished/v1 models cannot execute.
- Private service runs `queued → running → completed|failed` and atomically persists
  project-owned summary, anomaly rows, and audit events.
- API never exposes private-service mutation endpoints, and public API/module imports
  remain Torch-free.
- Golden fixture covers the complete frozen HDFS inference composition; the controlled
  full baseline separately checks F1, PR-AUC, ROC-AUC, and threshold.

### Manual Testing Steps:

1. Supply and approve the trained HDFS baseline release, then export and register its v2
   model/bundle pair as a Publisher.
2. As an Operator, upload a valid HDFS file with known blocks, start analysis, and watch
   lifecycle polling reach a truthful terminal state.
3. Review block anomaly rows and bounded line context; submit a line that the frozen
   parser cannot match and confirm `UNMATCHED_TEMPLATE` without partial results.
4. Run the controlled full-corpus parity command in the Linux ML environment and review
   the comparison evidence.

## Performance Considerations

The two-second create acknowledgement applies to database persistence and bounded
dispatch scheduling, not completion of ML inference. The service processes one run per
invocation and uses temporary local files only for the selected immutable artefacts.
Do not recompute embeddings, enrich templates, rescan at API admission, or keep either
service awake through queue polling. The existing 32 MiB browser dataset limit remains;
the large labelled corpus is outside this route.

## Migration Notes

Add the migration forward-only after current migration `004_model_object_checksum`. It
must preserve existing model, dataset, run, result, and audit rows. Legacy v1 rows have a
null preprocessing-bundle link and stay visible/publishable but are not executable.
Do not rewrite past model references, delete object prefixes, or alter the status/CAS
schema. Apply and test the migration on SQLite and the disposable PostgreSQL harness
before staging; never roll back a deployed schema by destructive SQL.

## References

- Research: `context/changes/run-parity-hdfs-analysis/research.md`
- Product contract: `context/foundation/prd.md` — US-02, FR-006, FR-010, FR-011
- Roadmap: `context/foundation/roadmap.md` — S-04
- Stack topology: `context/foundation/tech-stack.md:53-113`
- Model package: `src/modules/model_package.py:120-161, 260-328`
- Pipeline artefacts and metrics: `run_ablation.py:203-280, 424-469, 542-683`
- Run CAS: `src/api/storage.py:601-675, 830-942`
- Current API/UI lifecycle: `src/api/main.py:511-598`, `frontend/src/App.tsx:79-89`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Capture the approved baseline release

#### Automated

- [x] 1.1 Export and validate a synthetic HDFS inference release; reject incomplete or smoke inputs — 8e59962
- [x] 1.2 Ruff, mypy, and focused exporter tests pass

#### Manual

- [x] 1.3 Record and approve the supplied trained baseline provenance, checksums, threshold, and core metrics — 8e59962

### Phase 2: Bind and admit immutable preprocessing bundles

#### Automated

- [x] 2.1 Package and bundle contract tests cover v1/v2 compatibility, hostile files, and schema mismatches — b5ca618
- [x] 2.2 Object-store, migration, repository, and API admission tests pass — b5ca618
- [x] 2.3 Ruff, mypy, and focused non-ML and marked ML tests pass — b5ca618

#### Manual

- [x] 2.4 Register a v2 release and verify separate, project-scoped immutable prefixes — b5ca618

### Phase 3: Implement the private, on-demand inference service

#### Automated

- [x] 3.1 Valid frozen tiny HDFS release completes through the isolated service — 8db9ddf
- [x] 3.2 Service failure, checksum, authorization, duplicate-invocation, and atomic-persistence tests pass — 8db9ddf
- [x] 3.3 Ruff, mypy, and Linux ML tests pass while the API Torch-import guard remains green — 8db9ddf

#### Manual

- [x] 3.4 Verify only selected project artefacts materialize and completed results are Operator-readable — 8db9ddf

### Phase 4: Queue dispatch and coarse Operator lifecycle

#### Automated

- [x] 4.1 API, dispatcher, TypeScript, static analysis, and Railway topology checks pass — 0258b7d
- [x] 4.2 Authorization, v1 non-readiness, retry, queued-preservation, and no-public-writer tests pass — 0258b7d

#### Manual

- [x] 4.3 Verify queued/running/terminal UI behavior, upload rejection, secret isolation, and staging cold start — 0258b7d

### Phase 5: Golden processing and release parity verification

#### Automated

- [x] 5.1 Golden HDFS fixture detects parsing, graph, score, ordering, and threshold drift
- [x] 5.2 Full parity command rejects checksum, threshold, and core metric deltas beyond tolerance
- [x] 5.3 Ruff, mypy, focused tests, and the native full-baseline gate pass

#### Manual

- [x] 5.4 Review and approve the controlled baseline comparison report before claiming FR-011
