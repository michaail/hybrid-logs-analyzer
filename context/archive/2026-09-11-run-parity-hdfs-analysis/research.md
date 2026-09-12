---
date: 2026-09-11T00:26:45+02:00
researcher: GPT-5.6 Terra
git_commit: c14fc1f1844ffd22b2d085ef39e4197168ee8fd9
branch: feature/Slice-04
repository: hybrid-logs-analyzer
topic: "Port the notebook HDFS pipeline to inference-only raw-log analysis; define parity and run reporting"
tags: [research, codebase, hdfs, inference, parity, analysis-runs]
status: complete
last_updated: 2026-09-11
last_updated_by: GPT-5.6 Terra
---

# Research: HDFS inference-only analysis, parity, and run reporting

**Date**: 2026-09-11T00:26:45+02:00
**Researcher**: GPT-5.6 Terra
**Git Commit**: `c14fc1f1844ffd22b2d085ef39e4197168ee8fd9`
**Branch**: `feature/Slice-04`
**Repository**: hybrid-logs-analyzer

## Research Question

1. How can notebook pipeline elements be ported for inference only when an Operator provides a raw HDFS log file?
2. What does parity mean in this context?
3. How should the system show analysis progress, errors, and results?

## Summary

The repository already has reusable parsing, sequencing, graph-construction, GAE-scoring,
durable-run, audit, API, and UI components. It does not have an executable inference
runner: `POST /analysis-runs` deliberately creates an immediately terminal
`not_supported` run. Production inference should compose existing modules around frozen
training-time preprocessing assets, rather than run the notebook or retrain.

The portable HDFS path is:

`raw log → frozen Drain annotation → HDFS block sequences → frozen enriched templates →
embeddings → PyG graphs → normalized GAE scoring → manifest threshold → persisted results`.

The published model package supplies model weights, architecture, score weights,
edge-normalization statistics, and a decision threshold. It does *not* contain the
frozen Drain snapshot, enriched-template data, or embedding configuration/assets needed
to recreate the model inputs. Those must therefore be an immutable, separately stored
preprocessing bundle bound to the model version.

Parity is not a claim that arbitrary unlabeled uploads reproduce notebook metrics.
It has two distinct parts:

- **Processing parity:** a frozen inference bundle maps the same raw HDFS input to the
  same matched records, ordered `block_id` sequences, graph inputs, scores, and strict
  threshold decisions.
- **Evaluation-metric parity:** against an agreed, labelled HDFS baseline corpus, each
  named baseline metric differs by no more than 0.01 absolute. This is the PRD's binding
  acceptance criterion but cannot yet be validated because no baseline notebook,
  configuration, trained model, and reference results have been selected.

For the S-04 MVP, expose durable coarse lifecycle state only:
`queued → running → completed|failed`. The existing frontend already polls these states.
Detailed per-step progress is explicitly nice-to-have and should not delay the run path.
Rich anomaly inspection belongs primarily to S-05, although the worker should persist the
summary and anomaly rows that S-05 will read.

## Detailed Findings

### 1. Reusable HDFS inference path

The notebook pipeline has already been partially extracted into `src/modules/`; the
headless training/evaluation runner is `run_ablation.py`. Its stages demonstrate the
required ordering, but are not usable as-is for inference because stage 1 fits a parser,
later stages require labels and splits, and stage 6 trains a model.

| Stage | Reuse for inference | Do not run in production inference |
| --- | --- | --- |
| Parse | `DrainParser.load()` then `annotate_file()` | `fit_file()` or template mutation |
| Enrich | Load frozen enriched templates | Live/LLM enrichment |
| Sequence | `build_sequences(..., "hdfs")` | Nothing additional |
| Features/graphs | `compute_embeddings()` and `build_pyg_dataset()` with training-matched settings | Train/validation/test split |
| Score | `AttributeAwareGAE` and `compute_anomaly_scores()` | Training and threshold selection |

HDFS sequences are block-level: the sequencer groups records by `block_id` and preserves
timestamp order. A result should therefore identify a block as the scored entity; source
lines and raw log context are supporting evidence, not separately scored events.

The required execution contract is:

1. Resolve a trusted published model and its immutable preprocessing bundle in the same
   project.
2. Load the frozen Drain snapshot with the exact `configs/drain.ini`; call
   `annotate_file()` only.
3. Fail explicitly, or apply a documented policy, when a syntactically valid line does
   not match a frozen template. The current parser silently skips unmatched lines, which
   makes this a parity-critical design decision.
4. Build chronologically ordered HDFS sequences and use the frozen enriched templates to
   reproduce embedding inputs.
5. Build graph features using the same feature flags/configuration as training and apply
   the model package's `edge_mean` and `edge_std` before the model forward pass.
6. Construct the GAE architecture from package metadata, load only the tensor state dict
   with `weights_only=True`, set evaluation mode, compute scores with package
   `alpha`/`beta`/`gamma`, and classify strictly with `score > best_threshold`.
7. Persist the run summary and block-level anomaly rows atomically through the existing
   repository transition operation.

This path must run in an isolated worker/process, keeping PyTorch and model loading out
of the web-facing API process. That is required by the repository security boundary for
the legacy PyTorch runtime.

### 2. What "parity" means

The PRD requires that, for the identical dataset, model, and configuration, every
evaluation metric reported by the agreed notebook baseline remains within one percentage
point. It does not define an agreed reference yet. The roadmap therefore correctly marks
S-04 blocked, despite the prerequisite work being complete.

Metric parity alone is insufficient. Aggregate F1, PR-AUC, or ROC-AUC can remain close
while a different set of HDFS blocks is labelled anomalous. A complete parity contract
should add deterministic processing and decision checks:

| Layer | Required reference | Proposed assertion |
| --- | --- | --- |
| Parsing | Frozen Drain snapshot and config | Identical matched/unmatched line policy |
| Sequencing | Ordered HDFS block fixture | Exact ordered `block_id` set and source context |
| Graph inputs | Golden feature artifacts | Topology exact; feature values within a documented float tolerance |
| Scoring | Per-block baseline scores | Scores within a documented numerical tolerance |
| Decisions | Frozen threshold | Exact equality for `score > threshold` |
| Evaluation | Labelled held-out HDFS corpus | Each named metric delta ≤ 0.01 |

The future baseline release should record checksums for the labelled corpus and ordered
test blocks, Drain snapshot/configuration, template/enrichment assets, embeddings or
their reproducible inputs, model state dict, model metadata, code revision, runtime
versions, threshold, score weights, and per-block baseline results. The model package
can reference that preprocessing bundle by immutable ID and checksums without putting
the parser binary inside the package ZIP.

The current reproducible runner selects `best_threshold` from validation F1, then reports
test F1, PR-AUC, ROC-AUC, precision, recall, and a confusion matrix. The older evaluator
using a fixed 0.5 threshold is a different semantic path and must not become the oracle
by accident.

### 3. Existing asynchronous run/reporting foundation

The persistence layer already defines the intended status state machine and uses
compare-and-swap transitions:

`queued → running → completed`

`queued → running → failed`

It writes the audit event and completed anomaly rows in the same transaction. However,
the create endpoint currently returns `202` only after persisting a terminal
`not_supported` result with `INFERENCE_CONTRACT_UNAVAILABLE`. There is no worker that
claims queued runs, loads a model, or writes results.

The React app already:

- starts an analysis request and lists runs;
- polls every five seconds when a run is `queued` or `running`;
- displays run status, error code, validation report, summaries, and anomaly rows; and
- has a results dialog ready for rows that are not yet produced.

The worker is the missing producer. Once parity assets are available, the create endpoint
should insert `queued` with no completion time, and a worker should call
`transition_analysis_run()` for `queued → running → completed|failed`.

### 4. Progress, errors, and results recommendations

#### S-04: coarse observable lifecycle

Keep the public contract limited to the durable statuses required by FR-006:

| Operator-visible state | Meaning | Persisted data |
| --- | --- | --- |
| `queued` | Request accepted and awaiting a worker | Run ID, selected model and dataset |
| `running` | Worker claimed the run | Audit lifecycle entry |
| `completed` | Scoring and persistence succeeded | Summary and anomaly rows |
| `failed` | Worker could not complete inference | Stable error code and safe explanation |

Internally, structured logs may identify `resolve_bundle`, `annotate`, `sequence`,
`feature_graph`, `score`, and `persist`. Do not expose percentages or intermediate
artifacts yet: FR-009 is nice-to-have and the roadmap parks it to avoid delaying S-04.

#### Error boundary

Invalid HDFS syntax belongs to S-03 intake and remains a whole-dataset `422` report
before a dataset or run is created. A run that has been accepted should use terminal
`failed` and an error code. Candidate codes include `MODEL_LOAD_FAILED`,
`PARSER_FAILED`, `UNMATCHED_TEMPLATE`, `PREPROCESSING_BUNDLE_UNAVAILABLE`, and
`INFERENCE_FAILED`. Avoid leaking filesystem paths, untrusted exception messages, model
internals, or cross-project identity in the user-facing explanation; retain diagnostic
detail in server logs and project-scoped audit data.

`PARITY_CHECK_FAILED` should be used only for an explicit baseline verification run, not
for a normal Operator upload, because raw uploads normally lack labels.

#### Result boundary

On completion, S-04 should persist at least:

- `anomaly_count`, `normal_count`, invalid/rejected counts as appropriate;
- selected model version, dataset checksum, inference/preprocessing-bundle identity;
- baseline identity and metric deltas when the run is a labelled parity verification; and
- anomaly rows with `block_id`, score, decision threshold, anomaly level, and safe
  source-log context.

S-05 should own the richer presentation and filtering of anomalies and outcome summaries.
It should not list every normal record, consistent with FR-007.

## Code References

- `src/modules/parser/drain_parser.py:148-188, 238-252` — non-mutating annotation and
  frozen parser loading.
- `src/modules/sequencer.py:114-128` — HDFS blocks and timestamp ordering.
- `src/modules/enrichment.py:88-127` — loading enriched templates.
- `src/modules/dataset.py:38-119, 125-387` — embeddings and PyG graph construction.
- `src/modules/models/gae.py:47-311` — model architecture and weighted anomaly scores.
- `src/modules/model_package.py:60-115, 149-160` — package architecture, score, and
  threshold metadata, but no preprocessing bundle.
- `src/model_validator/runtime.py:67-76` — tensor-only model state loading.
- `run_ablation.py:424-469, 542-614, 659-683` — training runner parsing, metric/
  checkpoint production, and strict threshold rule.
- `src/api/main.py:506-598` — terminal `not_supported` create behavior and read APIs.
- `src/api/schemas.py:36-44, 187-218` — run status and HTTP response schemas.
- `src/api/storage.py:35-47, 830-909` — legal run transitions, atomic persistence, and
  audit.
- `src/api/validation.py:255-337, 346-366` — whole-HDFS-file intake validation report.
- `frontend/src/App.tsx:79-89, 711-744, 1427-1431, 1466-1526` — polling, run list,
  current notice, and result dialog.
- `tests/test_pipeline_smoke.py:26-64` — closest current pipeline smoke coverage; it
  trains and is not inference parity coverage.
- `tests/test_api.py:705-712` — current `not_supported` behavior.

## Architecture Insights

- Production should orchestrate reusable `src/modules/` code; notebooks remain the
  R&D/comparison baseline and must not be the only implementation of inference.
- A GAE model is not a complete HDFS inference artifact. The preprocessing state is part
  of model semantics and needs immutable provenance.
- Package acceptance and package execution are distinct trust boundaries. Model artifact
  loading belongs in an isolated process even after a Publisher's package passes
  eligibility validation.
- Durable run status and atomic result/audit persistence already form a sufficient
  control-plane seam for an external or in-process worker; API endpoints should not
  acquire ML-runtime responsibility.
- The notebook graph-preparation path and reusable dataset module may differ in numeric
  feature transformations. Select one exact baseline path before treating either as the
  parity oracle.

## Historical Context

- `context/foundation/roadmap.md:166-179` — S-04 is blocked on selecting the notebook
  and configuration that form the parity baseline.
- `context/foundation/roadmap.md:235-236` — detailed progress is parked as a
  nice-to-have.
- `context/archive/2026-09-10-intake-hdfs-dataset/plan.md:50-59` — leaves the
  unmatched-template policy for S-04 and separates intake validation from inference.
- `context/archive/2026-09-10-intake-hdfs-dataset/plan.md:77-88` — the full LogHub
  corpus does not fit the public upload path; parity evaluation is a release gate rather
  than a browser-upload workflow.
- `context/archive/2026-09-09-shared-durable-runtime-state/plan-brief.md:36-40,
  54-55` — durable statuses, results summary, and CAS transition seam were introduced
  before an execution worker.
- `context/archive/2026-09-10-publish-hdfs-model-package/research.md:77, 133` —
  publishing does not make an inference contract available by itself.

## Related Research

- `context/archive/2026-09-10-publish-hdfs-model-package/research.md`
- `context/archive/2026-09-10-testing-critical-path-api-isolation/research.md`

## Open Questions

1. Which exact HDFS notebook or headless runner version, configuration, model, corpus
   split, and reference metrics will be the accepted parity baseline?
2. Will the trained export include a reproducible embedding representation/vectorizer, or
   will it require deterministic recomputation from frozen templates and explicit model
   versions?
3. What policy should apply to a syntactically valid raw HDFS line that cannot match the
   frozen Drain snapshot: fail the run, mark it invalid, or report a separate unmatched
   count? Silent dropping is not suitable for a parity-preserving contract.
4. Where and how will preprocessing bundles be stored, checksummed, project-scoped, and
   retained alongside published model versions?
5. Is the intended execution worker a local process for the initial deployment or a
   separate service/job runtime? This affects deployment isolation but not the durable
   run interface.
