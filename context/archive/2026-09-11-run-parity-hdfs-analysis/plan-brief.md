# Run parity-preserving HDFS analysis — Plan Brief

> Full plan: `context/changes/run-parity-hdfs-analysis/plan.md`
> Research: `context/changes/run-parity-hdfs-analysis/research.md`

## What & Why

This change turns an admitted HDFS log and compatible published model into a real,
asynchronous anomaly-analysis run. It replaces the deliberate `not_supported` endpoint
stub with a private ML inference service while preserving project isolation, model safety,
and notebook-derived semantics.

The current model package is insufficient to score raw logs: it lacks the frozen Drain
parser/configuration and embeddings that produce graph inputs. This plan makes that
preprocessing state explicit, immutable, and bound to the model.

## Starting Point

The public FastAPI API already authorizes model/dataset selection, persists durable
analysis runs, and exposes result reads; the React UI already polls queued/running runs.
However, valid requests immediately finish `not_supported`, and there is no worker,
object-store read operation, inference runtime, or accepted parity baseline.

## Desired End State

An Operator receives a quick queued acknowledgement, sees the run reach a truthful
terminal state, and can inspect block-level anomaly counts, scores, thresholds, and
bounded log context. The public API remains Torch-free; a private on-demand service
loads only verified release objects and writes results transactionally.

Once a trained baseline is supplied and approved, the release gate verifies exact
threshold equality and ≤1 percentage-point deltas for test F1, PR-AUC, and ROC-AUC.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Baseline availability | Capture and approve it before parity claim | The required oracle does not yet exist | Plan |
| Preprocessing ownership | Separate immutable bundle | Parser/config/embeddings are model semantics, not incidental cache | User |
| Parser mismatch | Fail entire run | Silent dropping invalidates a parity claim | User |
| Result granularity | One row per HDFS block | HDFS labels and graphs are block-level | User |
| Execution topology | Private on-demand service | Matches the selected Railway/serverless architecture | Research |
| Public progress | Lifecycle states only | Detailed stages are a parked nice-to-have | User |
| Error surface | Stable code plus safe explanation | Operators need actionability without internal leakage | User |
| Parity checks | Golden fixture plus release gate | Separates fast deterministic regression checks from full-corpus validation | User |

## Scope

**In scope:**
- Baseline-release export of a tensor-only v2 model package and separate preprocessing bundle.
- Validated, checksum-bound project-scoped bundle persistence and object reads.
- A Linux private inference service, durable queue dispatch, and block-level results.
- Golden processing tests plus controlled full-corpus F1/PR-AUC/ROC-AUC verification.

**Out of scope:**
- Training, BGL, real-time detection, polling workers, WebSockets, per-step percentages,
  full-corpus browser upload, and rich result exploration beyond the existing dialog.

## Architecture / Approach

`React → FastAPI (authorization + queued run) → private inference service → PostgreSQL`

The service reads selected model, bundle, and dataset objects from private storage, verifies
them in a temporary directory, runs frozen `Drain → sequence → graph → GAE score`, and
uses the existing compare-and-swap transition to persist a completed or failed run.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Baseline release | Approved reference and reproducible exporter | Training artefacts are not yet available |
| 2. Bundle admission | Versioned contract, storage, model binding | Security and cross-project integrity |
| 3. Inference service | Isolated frozen HDFS scoring | ML runtime and hidden preprocessing drift |
| 4. Queue lifecycle | Async dispatch and honest Operator state | Cold-start activation reliability |
| 5. Verification | Golden fixture and full release gate | Native full-corpus execution environment |

**Prerequisites:** A user-supplied trained HDFS baseline, labelled held-out corpus, model,
parser snapshot, templates/embeddings, configuration, threshold, and core metrics.
**Estimated effort:** ~5–7 focused implementation sessions plus a separate baseline-training
and native parity-validation session.

## Open Risks & Assumptions

- The designated baseline artefacts will be available before release verification begins.
- No selected v1 model becomes inference-capable without a verified v2 preprocessing bundle.
- An on-demand service can be activated privately in the Railway environment without exposing
  its invocation token or object-store credentials.

## Success Criteria (Summary)

- A valid v2 HDFS release reaches a terminal asynchronous result with block-level anomalies.
- Parser mismatch, bundle mismatch, missing embedding, and corrupted object failures are
  explicit, safe, and leave no partial completion.
- The approved full baseline passes the named metric tolerance and exact-threshold gate.
