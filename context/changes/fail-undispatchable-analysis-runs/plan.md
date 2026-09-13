# Fail undispatchable analysis runs Implementation Plan

## Overview

Close the HDFS analysis-run lifecycle gap that leaves a run permanently `queued` after
the private inference service cannot be activated. Keep the asynchronous `202` contract
and bounded cold-start retry, but record a safe terminal failure when dispatch concludes
without a successful activation.

## Current State Analysis

The API creates a durable `queued` run and schedules dispatch in `BackgroundTasks`.
`dispatch_analysis_run()` retries and logs failures without leaking secrets, but returns
`None` and never writes state. The inference service owns `running → completed|failed`
after it claims a run, so no component owns terminalizing pre-claim failures.

This was an intentional S-04 cold-start decision, but it conflicts with the PRD
requirement that every unsuccessful analysis run expose a terminal `failed` status and a
useful error. The React client polls every `queued`/`running` run as though it is making
progress, so it never communicates this terminal condition.

## Desired End State

An Operator who starts a valid HDFS analysis still receives a fast `202` response whose
initial run is `queued`. If the private inference service accepts dispatch, the existing
inference-service lifecycle is unchanged. If dispatch exhausts configured retry, lacks
both private-service settings, or receives a final non-2xx response, the background task
marks the still-queued run `failed` with `INFERENCE_DISPATCH_FAILED`, a safe explanation,
an audit event, and `completed_at`.

The transition is compare-and-swap guarded: it must never overwrite a run already claimed
as `running` (or already terminal). An Operator does not get a retry control in this
change; after infrastructure is fixed, they submit a new analysis run.

### Key Discoveries:

- `POST /projects/{project_id}/analysis-runs` stores `queued`, queues a background
  dispatch callback, and returns `202` before dispatch outcome is known
  (`src/api/main.py:556-601`).
- The dispatcher deliberately logs and returns without terminal mutation
  (`src/api/inference_dispatch.py:32-52`).
- Only `queued → running` and `running → completed|failed` are legal transitions today
  (`src/api/storage.py:85-87`).
- The service claims a run before scoring; `expected_status="queued"` is therefore the
  mandatory guard for a control-plane failure transition
  (`src/inference_service/runner.py:54-129`).
- `tests/test_api.py::test_exhausted_dispatch_preserves_queued_run` directly encodes the
  obsolete behavior and is the test-driven entry point.

## What We're NOT Doing

- Adding a polling worker, durable queue, automatic recovery job, or infinite retry.
- Adding an Operator retry endpoint, UI button, or reusing the failed run.
- Changing HDFS scoring, inference execution, model/package loading, or notebook parity.
- Adding BGL support, Sentry, Playwright coverage, new ML subprocess coverage, or
  regenerating `requirements-macos-intel.lock.txt`.
- Altering historical archive artifacts. Documentation changes apply only to current README
  and staging guidance.

## Implementation Approach

Keep the dispatcher storage-free. It will report a typed, non-secret activation outcome
to the API callback rather than raise an unhandled background-task exception or mutate
the database itself. The callback owns durable state because it created the queued row and
has the database dependency.

The state repository gains the additive legal transition `queued → failed`. A failed
dispatch attempts that transition with `expected_status="queued"` and stores the stable
code and generic safe report. A CAS conflict is expected when the inference service
already claimed the run and must not be converted into an API error or a second terminal
write.

## Critical Implementation Details

**Timing & lifecycle.** A `202` response reflects creation of a queued record, not the
result of its background dispatch. Tests must therefore assert the POST payload remains
queued and use a subsequent GET as the durable status oracle. Treat all exhausted retry
outcomes—including ambiguous connect/read timeouts—as terminal under the selected product
policy. A late service claim can lose the CAS race and must then be unable to overwrite the
terminal state.

**Debug & observability.** Keep current private diagnostics to server logs and preserve
the existing no-token/no-Authorization/no-Bearer logging guarantee. The persisted report
uses a stable generic message only; it must not expose URL, status-body content, exception
text, credentials, or object-store data.

## Phase 1: Dispatch outcome and durable failure transition

### Overview

Replace the current log-and-return-only terminal path with an explicit dispatch result
that allows the API background callback to close a run safely while leaving normal service
execution untouched.

### Changes Required:

#### 1. Dispatch classification and safe public failure contract

**Files**: `src/api/inference_dispatch.py`

**Intent**: Report whether private inference activation was accepted or conclusively
failed after the configured policy, without coupling the dispatch transport to storage or
leaking diagnostics.

**Contract**: Change `dispatch_analysis_run()` and its internal retry path from `None` to
a typed outcome. Successful HTTP responses remain successful activation. Missing paired
settings, exhausted retryable exceptions or transient statuses, and a non-transient HTTP
status produce a terminal failure outcome with the stable public code
`INFERENCE_DISPATCH_FAILED` and one generic Operator-safe message. Preserve bounded retry
and current private log redaction.

#### 2. API callback owns pre-claim terminalization

**Files**: `src/api/main.py`

**Intent**: Convert a failed dispatch outcome into a durable run result after the `202`
acknowledgement, while preserving the current access checks and queued creation response.

**Contract**: `_dispatch_queued_run()` inspects the dispatcher outcome. For failure, it
serializes only the approved public message and calls the existing transition seam with
`expected_status="queued"`, `next_status="failed"`, null/system actor, and
`INFERENCE_DISPATCH_FAILED`. A CAS conflict is benign and logged safely because inference
may already have claimed the run. The endpoint itself continues to return its original
queued representation and never waits for inference.

#### 3. Legal pre-claim failure transition

**Files**: `src/api/storage.py`

**Intent**: Allow the existing atomic transition implementation to record a failure when
work could not begin.

**Contract**: Add only `queued → failed` to the legal transition set. Reuse the existing
failed-row update and audit behavior so it persists `error_code`, `completed_at`,
`validation_report_json`, and `analysis.failed`; do not add a migration or a special SQL
path.

### Success Criteria:

#### Automated Verification:

- Focused API test first fails under current behavior, then proves an exhausted
  connection-refused dispatch returns `202 queued` but a subsequent GET returns `failed`,
  `INFERENCE_DISPATCH_FAILED`, a safe execution report, and `completed_at`.
- Focused dispatcher tests prove successful retry remains accepted; exhausted retry,
  missing paired settings, and non-transient HTTP response each return the selected safe
  failure outcome without raising to `BackgroundTasks`.
- Shared-state tests prove `queued → failed` is legal, audited, and CAS-protected, while
  existing `queued → running` and `running → completed|failed` behavior remains valid.
- `ruff check src/api/inference_dispatch.py src/api/main.py src/api/storage.py
  tests/test_api.py tests/test_inference_dispatch.py tests/test_shared_state_repository.py`,
  `mypy`, and the focused non-ML pytest modules pass.

#### Manual Verification:

- In a local or staging configuration with unreachable private inference, create one valid
  HDFS run and confirm it first appears queued, then becomes failed with safe copy and no
  secret, URL, or exception detail exposed to the Operator.

**Implementation Note**: Pause after this phase. Confirm manually that a normal
inference-service claim still reaches its existing terminal path before proceeding to
documentation.

---

## Phase 2: Regression and boundary coverage

### Overview

Lock the corrected behavior at the API, dispatch, and repository seams without replacing
the existing private-service tests or expanding to browser E2E.

### Changes Required:

#### 1. Invert the existing exhausted-dispatch integration oracle

**Files**: `tests/test_api.py`

**Intent**: Turn the known stuck-queued behavior into the regression test that proves the
Operator-visible durable result.

**Contract**: Rename and revise `test_exhausted_dispatch_preserves_queued_run` to assert
the selected failure semantics after the background task. Preserve its valid v2 model,
project-scoped dataset, real dispatcher, mocked transport, retry-count, and initial `202`
queued assertions. Add an assertion for the persisted audit event if the existing test
helpers make it direct; do not duplicate UI polling tests.

#### 2. Preserve dispatch transport and state-machine boundaries

**Files**: `tests/test_inference_dispatch.py`, `tests/test_shared_state_repository.py`

**Intent**: Make outcome classification and the new legal transition explicit while
retaining existing coverage of retry count and secret-safe logging.

**Contract**: Update unit or contract assertions for the dispatch return type without
requiring a database. Add a focused repository assertion for `queued → failed`, including
failure fields and a rejected duplicate transition. Keep tests that exercise
`running → failed`, stale-running reclaim, and the real isolated inference subprocess
unchanged because they cover a separate, post-claim owner.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py -k "dispatch" -vv` passes and no longer permits
  exhausted dispatch to leave a durable queued row.
- `python -m pytest tests/test_inference_dispatch.py
  tests/test_shared_state_repository.py -m "not ml" -vv` passes, including retry,
  redaction, and state-transition assertions.
- Existing inference-service tests remain green without importing inference/ML code into
  the public API process.

#### Manual Verification:

- Review the changed test names and assertions: one test owns pre-claim dispatch failure,
  while service tests continue to own post-claim execution failure.

**Implementation Note**: Pause after this phase. Confirm that no test asserts a status
only from the create response when the intent is to verify the background-task result.

---

## Phase 3: Documentation alignment

### Overview

Remove live documentation that calls an exhausted or unconfigured dispatch “honestly
queued,” while retaining truthful wording for the bounded retry window before terminal
failure.

### Changes Required:

#### 1. Local-runtime and API lifecycle documentation

**Files**: `README.md`

**Intent**: Explain the final dispatch lifecycle, including the safe terminal code, so
local users do not mistake missing inference configuration for indefinitely pending work.

**Contract**: Update the three-process and HDFS analysis descriptions to state that an
initial queued run is followed by bounded activation retry, then either inference-service
execution or `INFERENCE_DISPATCH_FAILED`. Retain requirements that the public API stays
Torch-free and private credentials never reach the frontend.

#### 2. Staging cold-start guidance

**Files**: `context/deployment/deploy-plan.md`

**Intent**: Align deployment verification with the new finality policy and preserve
safe-secret operational guidance.

**Contract**: Replace statements that exhausted activation stays queued with instructions
to observe queued only during configured retry, then a terminal failed run if activation
cannot succeed. Keep manual Railway provisioning and rollback procedures unchanged; do
not add an operational logging integration.

### Success Criteria:

#### Automated Verification:

- Repository search finds no live documentation claiming dispatch failures remain queued
  indefinitely; historical archive wording is intentionally excluded.
- Documentation-linked focused tests and all Phase 1–2 verification commands still pass.

#### Manual Verification:

- Read the local and staging run instructions end-to-end and confirm they accurately
  distinguish `queued`, `running`, execution failure, and
  `INFERENCE_DISPATCH_FAILED`.

**Implementation Note**: Pause after this phase. Human confirmation is required before
claiming the lesson exercise complete because the user-facing and deployment contracts
must agree.

## Testing Strategy

### Unit Tests:

- Dispatcher outcome for accepted activation after a transient failure.
- Dispatcher outcome for exhausted retryable exceptions, final transient status,
  non-transient HTTP status, and missing paired configuration.
- Generic safe log assertions continue to exclude token and authorization headers.
- Repository CAS allows `queued → failed`, persists required terminal metadata, audits
  once, and rejects a duplicate/conflicting transition.

### Integration Tests:

- Existing real dispatcher + mocked connection-refused transport creates an inference-ready
  HDFS run, returns initial `202 queued`, and persists terminal dispatch failure after the
  FastAPI background task.
- Existing successful dispatch scheduling test keeps its `202 queued` create contract.
- Existing private inference-service tests retain ownership of claimed-run execution and
  stale-running behavior.

### Manual Testing Steps:

1. Start the API with valid HDFS test fixtures and an unreachable private inference URL.
2. As an authorized Operator, create a run and observe initial queued acknowledgement.
3. Refresh/read the run after retries finish; verify failed status, code, completion time,
   safe report, and no secret exposure.
4. Restore a reachable private service and confirm a newly created run enters the existing
   `running → completed|failed` lifecycle.

## Performance Considerations

No new long-lived process or polling work is added. The existing finite retry budget
continues to bound background dispatch cost; the added database transition is one
compare-and-swap update plus its existing audit record. The initial `202` timing contract
remains unchanged because dispatch and terminalization run after response construction.

## Migration Notes

No database schema migration is required. The legal transition list changes in application
code only, and existing queued rows are not backfilled or automatically failed on deploy.
The new behavior applies to runs created after deployment. If rollout must be reverted,
deploy the prior code; retain any newly failed records and audit events rather than
modifying historical state.

## References

- Research: `context/changes/fail-undispatchable-analysis-runs/research.md`
- Product contract: `context/foundation/prd.md` — externally observable quality targets
- Prior design: `context/archive/2026-09-11-run-parity-hdfs-analysis/plan.md`
- Dispatch: `src/api/inference_dispatch.py`
- Create and callback: `src/api/main.py`
- State machine: `src/api/storage.py`
- Regression test: `tests/test_api.py::test_exhausted_dispatch_preserves_queued_run`
- Test strategy: `context/foundation/test-plan.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Dispatch outcome and durable failure transition

#### Automated

- [x] 1.1 Implement typed dispatch outcomes and safe `INFERENCE_DISPATCH_FAILED` classification — 5cf57d5
- [x] 1.2 Terminalize failed dispatches through guarded `queued → failed` API transition — 5cf57d5
- [x] 1.3 Verify focused API, dispatcher, repository, Ruff, and mypy checks — 5cf57d5

#### Manual

- [x] 1.4 Confirm unreachable private inference produces a safe terminal failed run — 5cf57d5

### Phase 2: Regression and boundary coverage

#### Automated

- [x] 2.1 Convert the exhausted-dispatch test into the pre-claim failure regression oracle — e2a396e
- [x] 2.2 Cover dispatch outcomes and guarded queued-to-failed repository semantics — e2a396e
- [x] 2.3 Verify public API remains non-ML and focused test suites pass — e2a396e

#### Manual

- [x] 2.4 Review ownership boundaries between dispatch and post-claim inference failures — e2a396e

### Phase 3: Documentation alignment

#### Automated

- [x] 3.1 Align README and staging documentation with bounded queued retry then terminal failure
- [x] 3.2 Verify live documentation and focused checks contain no stale queued-preservation contract

#### Manual

- [x] 3.3 Confirm local and staging instructions accurately describe the final lifecycle
