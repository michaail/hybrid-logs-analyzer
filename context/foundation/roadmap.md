---
project: "Log Anomaly Detection System"
version: 1
status: draft
created: 2026-09-09
updated: 2026-09-09
prd_version: 1
main_goal: speed
top_blocker: decisions
milestone_id: first-hdfs-publish-analyze
milestone_seq: 1
milestone_status: open
---

# Roadmap: Log Anomaly Detection System

> Derived from `context/foundation/prd.md` plus the auto-researched codebase baseline.
> Edit in place; archive when superseded.
> Slices below are listed in dependency order. The "At a glance" table is the index.

## Milestone

**M-1: First HDFS publish-and-analyze workflow** — Status: open

- **Intent:** Deliver the first protected workflow in which a Publisher can make an
  HDFS-compatible pretrained model available and an Operator can use it to analyze
  HDFS logs. It establishes the traceability and project boundaries needed for the
  workflow without adding training or additional log sources.
- **Source materials:** `context/foundation/prd.md` (v1); technical-stack contract
  used as supplementary context.
- **Done when:** every F-NN and S-NN below is `done`, and a Publisher can publish an
  eligible HDFS model that an authorized Operator can use to inspect traceable results.
- **Scope anchors:** US-01, US-02; FR-001–FR-008, FR-010, FR-011.

## Vision recap

An SRE currently needs notebook-order knowledge and manual preparation to reuse a
pretrained anomaly-detection model or analyze new logs. This milestone turns the
proven HDFS analysis path into a repeatable web workflow while keeping notebooks
available for research and comparison. The workflow must preserve agreed notebook
evaluation results, isolate every project, and make model and run actions traceable.

## North star

**S-02: Publisher can upload, validate, and explicitly publish an HDFS-compatible
model package.** This was selected as the first product proof because it creates the
controlled model lifecycle that every later analysis run requires.

> Here, "north star" means the smallest end-to-end user-facing slice that demonstrates
> the product's central promise; it is placed as early as its prerequisites allow.

## At a glance

| ID | Change ID | Outcome (user can …) | Prerequisites | PRD refs | Status |
| --- | --- | --- | --- | --- | --- |
| F-01 | shared-durable-runtime-state | (foundation) Model, run, and result records have a minimal shared, durable ownership and version boundary for the deployed workflow. | — | FR-006, FR-008 | ready |
| F-02 | trusted-model-package-contract | (foundation) A declared, non-executable model-package contract is checked before a model can enter the workflow; it does not run the model itself. | — | FR-002, FR-003, FR-004, FR-008 | in-progress |
| S-01 | provision-project-accounts | An administrator can provision a project-authorized Operator or Publisher account without public sign-up. | — | FR-001, FR-008 | in-progress |
| S-02 | publish-hdfs-model-package | A Publisher can upload a complete HDFS-compatible model package, receive a clear rejection when ineligible, and explicitly publish the eligible version. | F-01, F-02, S-01 | US-01, FR-002, FR-003, FR-004, FR-008 | proposed |
| S-03 | intake-hdfs-dataset | An Operator can upload or select an HDFS dataset and receive a clear whole-dataset acceptance or rejection result. | F-01, S-01 | US-02, FR-005, FR-008 | proposed |
| S-04 | run-parity-hdfs-analysis | An Operator can start asynchronous analysis of an HDFS dataset with a compatible, published same-project model and see a terminal run status. | F-01, F-02, S-02, S-03 | US-02, FR-006, FR-010, FR-011 | blocked |
| S-05 | inspect-hdfs-analysis-results | An Operator can inspect traceable detected anomalies and summaries for normal, rejected, and invalid outcomes. | S-04 | US-02, FR-007, FR-008 | proposed |

## Streams

Navigation aid — groups items that share a prerequisites chain. Canonical ordering
still lives in the dependency graph below; this table is the proposed reading order
across parallel tracks.

| Stream | Theme | Chain | Note |
| --- | --- | --- | --- |
| A | Durable analysis flow | `F-01` → `S-03` → `S-04` → `S-05` | Joins Stream B at `S-04`; keeps the operator path focused on the launch goal. |
| B | Trusted model availability | `F-02` → `S-02` | Joins Stream A at `S-04`; resolves the model-entry decision before use. |
| C | Account access | `S-01` | Enables the protected roles consumed by Streams A and B. |

## Baseline

What's already in place in the codebase as of `2026-09-09` (auto-researched and
user-confirmed). Foundations below assume these are present and do not re-scaffold them.

- **Frontend:** partial — a thin browser interface is selected, but its implementation
  remains an explicit prerequisite.
- **Backend / API:** present — the existing API is the control boundary for
  authentication, authorization, validation, and audit actions.
- **Data:** partial — local metadata persistence exists; the deployed workflow needs
  shared durable state.
- **Auth:** present — administrator-provisioned accounts, protected roles, and
  signed access tokens are established.
- **Deploy / infra:** partial — a hosting target and manual test deployment path are
  selected, but no production environment exists.
- **Observability:** partial — pipeline modules have basic logging, but there is no
  shared logging configuration, error tracking, metrics, tracing, or dashboard.

## Foundations

### F-01: Shared durable runtime state

- **Outcome:** (foundation) Model, run, and result records have a minimal shared, durable ownership and version boundary for the deployed workflow.
- **Change ID:** shared-durable-runtime-state
- **PRD refs:** FR-006, FR-008
- **Unlocks:** S-02, S-03, S-04, S-05
- **Prerequisites:** —
- **Parallel with:** F-02, S-01
- **Blockers:** —
- **Unknowns:** —
- **Risk:** A partial transition could break the project-ownership boundary between
  model publication and analysis.
- **Status:** ready

### F-02: Trusted model-package contract

- **Outcome:** (foundation) A declared, non-executable model-package contract is checked before a model can enter the workflow; it does not run the model itself.
- **Change ID:** trusted-model-package-contract
- **PRD refs:** FR-002, FR-003, FR-004, FR-008
- **Unlocks:** S-02, S-04; model-package eligibility verification
- **Prerequisites:** —
- **Parallel with:** F-01, S-01
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Pretrained PyTorch `.pt` artifacts must enter only through a trusted
  Publisher package contract; the control plane must not treat upload as license to
  deserialize untrusted model code.
- **Status:** in-progress

## Slices

### S-01: Provision project accounts

- **Outcome:** An administrator can provision a project-authorized Operator or Publisher account without public sign-up.
- **Change ID:** provision-project-accounts
- **PRD refs:** FR-001, FR-008
- **Prerequisites:** —
- **Parallel with:** F-01, F-02
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Provisioning must stay on the existing administrator-created account
  boundary and must not weaken project role isolation.
- **Status:** in-progress

### S-02: Publish an HDFS model package

- **Outcome:** A Publisher can upload a complete HDFS-compatible model package, receive a clear rejection when ineligible, and explicitly publish the eligible version.
- **Change ID:** publish-hdfs-model-package
- **PRD refs:** US-01, FR-002, FR-003, FR-004, FR-008
- **Prerequisites:** F-01, F-02, S-01
- **Parallel with:** S-03
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Explicit publication of a pretrained PyTorch `.pt` package must not make
  an eligible model usable outside its authorized project.
- **Status:** proposed

### S-03: Intake an HDFS dataset

- **Outcome:** An Operator can upload or select an HDFS dataset and receive a clear whole-dataset acceptance or rejection result.
- **Change ID:** intake-hdfs-dataset
- **PRD refs:** US-02, FR-005, FR-008
- **Prerequisites:** F-01, S-01
- **Parallel with:** S-02
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Validation must reject an invalid dataset before it becomes available to
  a protected analysis run.
- **Status:** proposed

### S-04: Run parity-preserving HDFS analysis

- **Outcome:** An Operator can start asynchronous analysis of an HDFS dataset with a compatible, published same-project model and see a terminal run status.
- **Change ID:** run-parity-hdfs-analysis
- **PRD refs:** US-02, FR-006, FR-010, FR-011
- **Prerequisites:** F-01, F-02, S-02, S-03
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:**
  - Which notebook and configuration form the agreed parity baseline? — Owner: user.
    Block: yes.
- **Risk:** Without an agreed comparison baseline, the analysis result cannot be
  accepted as preserving the required notebook behavior.
- **Status:** blocked

### S-05: Inspect HDFS analysis results

- **Outcome:** An Operator can inspect traceable detected anomalies and summaries for normal, rejected, and invalid outcomes.
- **Change ID:** inspect-hdfs-analysis-results
- **PRD refs:** US-02, FR-007, FR-008
- **Prerequisites:** S-04
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Results must give useful log context without exposing a different
  project's runs, models, or data.
- **Status:** proposed

## Backlog Handoff

| Roadmap ID | Change ID | Suggested issue title | Ready for `/10x-plan` | Notes |
| --- | --- | --- | --- | --- |
| F-01 | shared-durable-runtime-state | Establish shared durable runtime state | yes | Directly unlocks the selected model-publication slice. |
| F-02 | trusted-model-package-contract | Define the trusted model-package contract | yes | Artifact weight is a pretrained PyTorch `.pt` file. |
| S-01 | provision-project-accounts | Provision project-authorized accounts | yes | Keep administrator-provisioned accounts; no public sign-up. |
| S-02 | publish-hdfs-model-package | Publish an HDFS-compatible model package | no | Depends on F-01, F-02, and S-01. |
| S-03 | intake-hdfs-dataset | Intake and validate an HDFS dataset | no | Depends on F-01 and S-01. |
| S-04 | run-parity-hdfs-analysis | Run parity-preserving HDFS analysis | no | Depends on the selected model and dataset paths plus the parity baseline. |
| S-05 | inspect-hdfs-analysis-results | Inspect traceable HDFS results | no | Depends on S-04. |

## Open Roadmap Questions

1. **Account access decision (resolved 2026-09-09):** keep administrator-provisioned
   accounts with no public sign-up; do not introduce a separate self-serve sign-up
   path. — Owner: user. Block: none.
2. **What languages, frameworks, storage, and infrastructure make up the current
   notebook system? (resolved 2026-09-09)** — Jupyter notebooks in python, storage: local artifacts, infrastructure: local.
3. **Model-package format decision (resolved 2026-09-09):** Publishers provide
   pretrained PyTorch `.pt` models inside the package contract (metadata, metrics,
   source compatibility, and external-evaluation evidence remain required). —
   Owner: user. Block: none.
4. **Which notebook and configuration form the agreed parity baseline? (resolved 2026-09-09)** — Owner:
   user. Block: S-04. - This will be provided in due course as the baseline models needs to be trained first
5. **What is the current user scale of the notebook system? (resolved 2026-09-09)** — One user, same as admin, owner of the solution and infrastructure

## Parked

- **Web-based model training, retraining, automated model selection, and experiments**
  — Why parked: PRD §Non-Goals keeps training in the notebook research workflow.
- **Real-time or continuous detection** — Why parked: PRD §Non-Goals limits the MVP
  to submitted HDFS datasets.
- **Additional log-source formats** — Why parked: PRD §Non-Goals and repository
  scope limit user-facing MVP support to HDFS.
- **Advanced MLOps capabilities and production model monitoring** — Why parked: PRD
  §Non-Goals limits this milestone to publication and analysis.
- **External operational integrations and automated remediation** — Why parked: PRD
  §Non-Goals ends the workflow at anomaly identification and inspection.
- **Replacing the R&D notebooks** — Why parked: FR-010 preserves their separate
  research and comparison role.
- **Detailed per-step progress and intermediate outputs** — Why parked: FR-009 is
  nice-to-have and cannot delay the selected fast-launch path.

## Milestone History

## Done
