---
project: "Log Anomaly Detection System"
context_type: brownfield
created: 2026-08-31
updated: 2026-08-31
product_type: web-app
target_scale:
  users: small
  qps: "low; one active analysis run at a time"
  data_volume: "datasets comparable to the LogHub HDFS and BGL references"
timeline_budget:
  delivery_weeks: 2
  hard_deadline: null
  after_hours_only: false
checkpoint:
  current_phase: 8
  phases_completed: [1, 2, 3, 4, 5, 6, 7]
  gray_areas_resolved:
    - topic: "change category"
      decision: "New production workflow/module, architectural improvement, and migration from notebook execution."
    - topic: "primary persona"
      decision: "SRE."
    - topic: "initial log-source scope"
      decision: "HDFS and BGL are both must-have input sources for the first shippable version; additional sources may follow."
    - topic: "why now"
      decision: "Deliver a production-oriented MVP for the master's thesis."
    - topic: "key insight"
      decision: "Notebook orchestration, state, and traceability are implicit; extraction must preserve validated numerical behavior; product boundaries were absent from the research prototype."
    - topic: "current access model"
      decision: "No application authentication; users access the notebook environment directly."
    - topic: "planned account access"
      decision: "Administrator-provisioned accounts with no public sign-up; exact sign-in method remains undecided."
    - topic: "role separation"
      decision: "Operators can analyze and verify; Publishers can additionally upload, register, and publish pretrained models."
    - topic: "isolation boundary"
      decision: "Logs, runs, models, and results are isolated by project."
    - topic: "MVP scope"
      decision: "Training is excluded; Publishers provide pretrained models with metadata, metrics, and evidence of external evaluation."
    - topic: "model eligibility and publication"
      decision: "A model package must be complete, declare compatible sources, and include external-evaluation evidence before versioned registration; these checks do not establish model quality. A Publisher then publishes it explicitly."
    - topic: "analysis execution"
      decision: "Analysis runs are asynchronous and expose status; detailed per-step progress and intermediate outputs are nice-to-have."
    - topic: "delivery estimate"
      decision: "Two weeks during normal working hours for the reduced MVP."
    - topic: "numerical parity"
      decision: "Agreed evaluation metrics may differ from notebook baselines by at most one percentage point for the same dataset, model, and configuration."
    - topic: "log intake"
      decision: "Operators can upload new HDFS or BGL logs or select a previously stored dataset."
    - topic: "invalid dataset handling"
      decision: "Reject the entire dataset with a clear validation report."
    - topic: "primary story split"
      decision: "Separate Publisher import/publication and Operator analysis stories."
    - topic: "result presentation"
      decision: "Show detected anomalies plus summaries for normal, rejected, and invalid outcomes rather than listing every normal record."
    - topic: "parity metric set"
      decision: "Every evaluation metric reported by the agreed notebook baseline is subject to the one-percentage-point tolerance."
    - topic: "business-rule delta"
      decision: "Preserve score-versus-threshold anomaly classification and add model eligibility, publication, source-compatibility, and same-project use rules."
    - topic: "compatibility boundary"
      decision: "Preserve notebook dataset/configuration semantics, model artifacts, evaluation outputs, and notebook fallback; no existing data is migrated."
    - topic: "run feedback"
      decision: "Acknowledge an analysis start within two seconds and show initial status within five seconds."
    - topic: "retention"
      decision: "Uploaded logs, models, run records, and results remain available until an authorized user deletes them."
    - topic: "product surface"
      decision: "Add a web app while preserving notebooks as the R&D environment."
    - topic: "target scale"
      decision: "A handful of users, one active analysis run at a time, and datasets comparable to the LogHub HDFS and BGL references."
    - topic: "timeline"
      decision: "Two weeks during normal working hours with no hard deadline."
    - topic: "existing operational constraints"
      decision: "No existing production deployment, CI/CD, API-consumer, monitoring, or alerting contract."
  frs_drafted: 11
  quality_check_status: accepted
---

# Shape Notes

Seed source: `context/foundation/mvp-draft.md`

## Current System Overview

The existing system detects anomalies in system logs and currently focuses on HDFS logs from the LogHub dataset. It is implemented mainly as a sequence of Jupyter Notebooks for data preparation, transformations, feature engineering, model training, evaluation, and exploratory analysis.

The current architecture is a research and development workflow whose execution order, environment setup, intermediate state, and assumptions are implicit in notebook structure and cells. Jupyter Notebooks are the only technology identified so far; the underlying languages, frameworks, storage, and infrastructure have not yet been captured. Current use requires notebook and machine-learning implementation knowledge, and the present user scale is not specified.

## Problem Statement & Motivation

An SRE investigating unusual behavior after incidents, deployments, or operational changes cannot independently validate, publish, and reuse a pretrained anomaly-detection model or analyze new logs without manually executing notebooks and understanding their internals. The current workaround requires notebook-order knowledge, local environment setup, manual state preparation, and implicit coordination between cells.

The change is needed now to deliver a production-oriented MVP for the master's thesis. It adds a repeatable web workflow for pretrained-model intake, publication, and analysis while retaining notebook-based training, research, and exploration. Both HDFS and BGL logs are must-have sources for the first shippable version, and additional log sources may be supported later.

Simply wrapping the notebooks is insufficient: orchestration, state, and traceability are implicit; extracting the analysis path risks changing validated numerical behavior; and authentication, isolation, model lifecycle, and auditability were outside the research prototype. The production workflow must preserve the validated anomaly-detection, data-preparation, and evaluation behavior and reproduce agreed notebook results for the same dataset and configuration within a defined numerical tolerance.

At one hundred times the initial user scale, the model eligibility, publication, and same-project-use rules remain unchanged; only capacity and operational needs change.

## User & Persona

The primary persona is an SRE responsible for investigating unusual system-log behavior after incidents, deployments, or operational changes. The SRE can provide or select input log data and interpret technical results, but standard model publication and analysis must not require understanding notebook internals, modifying machine-learning code, preparing state manually, or directly changing storage.

## Success Criteria

### Primary

- A Publisher can upload a pretrained model with its required metadata, metrics, source compatibility, and external-evaluation evidence; validate and register it as a versioned model; and explicitly publish an eligible version without executing or editing notebooks.
- An Operator can submit HDFS or BGL logs to an asynchronous analysis run using a compatible published model from the same project and inspect anomalies, scores or levels, threshold, log context, run identity, and exact model version.

### Secondary

- An Operator can observe detailed per-step progress and selected intermediate outputs during an analysis run.

### Guardrails

- For the same dataset, model, and configuration, agreed evaluation metrics differ from notebook baselines by no more than one percentage point.
- Existing notebooks remain usable for research, exploration, experimentation, and comparison.

## User Stories

### US-01: Publisher imports and publishes a pretrained model

- **Given** an authenticated Publisher authorized for a project and a pretrained model package containing its artifact, required metadata, evaluation metrics, declared log-source compatibility, and evidence of successful external evaluation
- **When** the Publisher uploads the package, its eligibility validation succeeds, and the Publisher explicitly publishes it
- **Then** the model is registered as a traceable version and made available as a published model within that project

#### Acceptance Criteria

- Missing or invalid artifacts, required metadata, metrics, source compatibility, or external-evaluation evidence produce a clear rejection and cannot be published.
- Registration retains the model identifier, version, status, metadata, metrics, artifact reference, and project ownership.
- Publication records the Publisher, publication time, and exact model version in the audit log.
- An Operator cannot register or publish a model.

### US-02: Operator analyzes HDFS or BGL logs

- **Given** an authenticated Operator authorized for a project, a valid uploaded or stored HDFS or BGL dataset, and a compatible published model in the same project
- **When** the Operator starts an anomaly-analysis run
- **Then** the run proceeds asynchronously and exposes its status before presenting traceable anomaly results

#### Acceptance Criteria

- A malformed or invalid dataset is rejected in full with a clear validation report and does not start analysis.
- An unpublished, source-incompatible, or cross-project model cannot be used for the run.
- Results identify the relevant log record, anomaly score or level, decision threshold, contextual log information, analysis-run identifier, model identifier, and exact model version.
- The Operator can inspect detected anomalous records and summaries for normal, rejected, and invalid outcomes.
- Detailed per-step progress and selected intermediate analysis outputs are nice-to-have.

## Scope of Change

- FR-001: [new] Administrator can provision user accounts; public sign-up is unavailable. Priority: must-have
  > Socrates: Counter-argument considered: account provisioning adds scope that could be replaced by pre-seeded users. Resolution: kept; provisioning is necessary to demonstrate the authentication boundary.
- FR-002: [new] Publisher can upload a pretrained model with its artifact, required metadata, evaluation metrics, declared log-source compatibility, and evidence of successful external evaluation. Priority: must-have
  > Socrates: Counter-argument considered: uploaded model artifacts add security and compatibility risk. Resolution: kept; the MVP accepts only a defined model-package format.
- FR-003: [new] System can validate the completeness and declared source compatibility of an uploaded model package, clearly reject failures, and register eligible models as traceable versions; this validation does not establish model quality. Priority: must-have
  > Socrates: Counter-argument considered: presence of external-evaluation evidence cannot prove actual model quality. Resolution: revised; eligibility validation establishes completeness and compatibility only.
- FR-004: [new] Publisher can explicitly publish an eligible model version within an authorized project. Priority: must-have
  > Socrates: Counter-argument considered: explicit publication duplicates eligibility state and adds workflow friction. Resolution: kept; the audited gate prevents accidental use of merely registered models.
- FR-005: [new] Operator can upload or select HDFS or BGL logs and receive a clear full-dataset rejection when validation fails. Priority: must-have
  > Socrates: Counter-arguments considered: two intake paths increase scope, and one malformed record blocks all valid records. Resolution: kept; strict full-dataset rejection is the safer and clearer MVP behavior.
- FR-006: [new] Operator can start asynchronous analysis with a compatible published model from the same project and observe run status. Priority: must-have
  > Socrates: Counter-argument considered: asynchronous orchestration may cost more than it proves. Resolution: kept; potentially long analysis needs a durable run identity and observable status.
- FR-007: [new] Operator can inspect traceable detected anomalies and view summaries for normal, rejected, and invalid outcomes. Priority: must-have
  > Socrates: Counter-argument considered: listing every normal record can overwhelm an investigation. Resolution: revised; show detected anomalies plus outcome summaries.
- FR-008: [new] System can isolate logs, models, runs, and results by project and audit significant user actions. Priority: must-have
  > Socrates: Counter-argument considered: a single-project MVP could prove the workflow with less access-control scope. Resolution: kept; project isolation and auditability are production-baseline requirements.
- FR-009: [new] Operator can observe per-step progress and selected intermediate outputs during analysis. Priority: nice-to-have
  > Socrates: Counter-argument considered: detailed progress can distract from the core workflow. Resolution: kept as nice-to-have and cannot delay the primary flow.
- FR-010: [preserved] User can continue using the existing notebooks for research, exploration, experimentation, and comparison. Priority: must-have
  > Socrates: Counter-argument considered: maintaining active notebooks may constrain production refactoring. Resolution: kept; notebooks remain a separate R&D path and comparison baseline.
- FR-011: [preserved] Operator can receive production-analysis results whose agreed metrics differ from notebook baselines by no more than one percentage point for the same dataset, model, and configuration. Priority: must-have
  > Socrates: Counter-argument considered: aggregate metrics can hide record-level differences or become ambiguous if the metric set is unnamed. Resolution: kept; every evaluation metric reported by the agreed notebook baseline is subject to the tolerance.

## Constraints & Compatibility

### Backward compatibility

- Preserve the dataset and configuration semantics used by the agreed notebook baselines.
- Preserve compatibility with the model artifacts and evaluation outputs used by those baselines.
- For identical datasets, models, and configurations, every evaluation metric reported by the agreed notebook baseline remains within one percentage point.

### Data migration

- No existing data is migrated. Pretrained models enter through the new Publisher upload flow.

### Existing integrations

- No existing external API or integration contract has been identified.
- The current system has no production deployment window, CI/CD release requirement, API-consumer compatibility obligation, or monitoring and alerting SLA to preserve.

### Preserved behavior and fallback

- Existing notebooks remain available as a separate research, exploration, experimentation, and comparison workflow.
- Standard model publication and log analysis do not require notebook execution, notebook edits, manual state preparation, or direct storage modification.

### Externally observable quality targets

- An accepted request to start analysis is acknowledged within two seconds, and its initial run status is visible within five seconds.
- Every unsuccessful analysis run exposes a terminal failed status and a useful error; no maximum failure-detection time is specified for the MVP.
- Uploaded logs, models, run records, and results remain available until an authorized user deletes them.
- No user can observe or act on logs, models, runs, or results outside an authorized project.
- Invalid model packages and invalid HDFS or BGL datasets fail with a clear validation result and do not silently proceed.

## Business Logic Changes

The existing notebook workflow classifies a log record as anomalous when its model-produced anomaly score crosses that model's decision threshold.

The MVP preserves that classification rule and adds a lifecycle rule: a pretrained model can be published and used for anomaly analysis only when its package is complete and compatible with its declared log source, evidence of successful external evaluation is present, a Publisher explicitly publishes it, and the model and analyzed logs belong to the same project.

The lifecycle rule consumes the uploaded model package, declared HDFS or BGL compatibility, external-evaluation evidence, publication action, and project ownership. It produces either a clear rejection or a published model version that an Operator can select for a compatible analysis run.

## Access Control Changes

The current notebook workflow has no application authentication; access is direct through the notebook environment.

The MVP introduces administrator-provisioned accounts with no public sign-up. The exact sign-in method is not yet decided. An unauthenticated request to any protected action or resource is denied and requires sign-in without revealing project data.

- **Operator:** can run analysis and verify results within an authorized project.
- **Publisher:** has Operator capabilities and can additionally upload, register, and explicitly publish pretrained models within an authorized project.

Input data, model artifacts, analysis runs, and results are isolated by project. A user cannot access or act on resources belonging to a project for which they are not authorized. Significant actions, including model upload, analysis-run execution, and model publication, are recorded in the audit log.

## Non-Goals

- **No model training in the web app.** Training, retraining, scheduled retraining, hyperparameter optimization, automated model selection, multi-model experiments, and A/B testing remain outside this MVP; Publishers provide pretrained models.
- **No real-time or continuous detection.** The MVP analyzes submitted HDFS or BGL datasets as asynchronous runs rather than consuming live streams.
- **No additional log-source formats.** User-facing support is limited to HDFS and BGL for the first release.
- **No advanced MLOps platform.** Feature stores, full experiment-tracking infrastructure, and production model monitoring are outside the publish-and-analyze workflow.
- **No external operational integrations.** PagerDuty, Slack, SIEM, Elasticsearch, OpenSearch, ticketing, and advanced alerting integrations are excluded.
- **No automated root-cause analysis or remediation.** Results stop at anomaly identification, score or level, threshold, and relevant log context.
- **No replacement of Jupyter Notebooks.** Notebooks remain the separate R&D, exploration, experimentation, and comparison environment.

## Open Questions

1. **Which account sign-in method will the web app use?** — Owner: user. Resolve before access-control implementation.
2. **What languages, frameworks, storage, and infrastructure make up the current notebook system?** — Owner: user. Resolve before downstream stack assessment.
3. **What exact model-package format and artifact contract can a Publisher upload?** — Owner: user. Resolve before model-intake implementation.
4. **Which notebook and configuration form the agreed parity baseline?** — Owner: user. Resolve before parity acceptance testing.

## Quality cross-check

Accepted on 2026-08-31. Access control, business logic, project artifacts, timeline-cost handling, non-goals, and preserved behavior are all present; no quality-gate gaps remain.
