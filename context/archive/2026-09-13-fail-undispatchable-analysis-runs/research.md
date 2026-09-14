---
date: 2026-09-13T20:01:20+02:00
researcher: Cursor Grok 4.6
git_commit: b8a0706d0b5897e823b9f8a309abad17ececacd4
branch: module3lesson5
repository: hybrid-logs-analyzer
topic: "Fail undispatchable HDFS analysis runs after exhausted inference dispatch"
tags: [research, codebase, analysis-runs, inference-dispatch, swallowed-errors, run-status]
status: complete
last_updated: 2026-09-13
last_updated_by: Cursor Grok 4.6
---

# Research: Fail undispatchable HDFS analysis runs after exhausted inference dispatch

**Date**: 2026-09-13T20:01:20+02:00
**Researcher**: Cursor Grok 4.6
**Git Commit**: `b8a0706d0b5897e823b9f8a309abad17ececacd4`
**Branch**: `module3lesson5`
**Repository**: hybrid-logs-analyzer

## Research Question

When an Operator starts HDFS analysis and the private inference service never accepts the
activation request (exhausted retries, connection refused, missing configuration, or a
permanent HTTP failure), what happens to the persisted run? Can a definitive dispatch
failure safely transition `queued → failed` without racing a run the service already
claimed, and which tests currently lock in “leave queued”?

## Summary

This is a **swallowed activation failure**, not a missing `try`. `POST /analysis-runs`
returns `202` with a durable `queued` row and schedules `dispatch_analysis_run` on
FastAPI `BackgroundTasks`. Dispatch retries a bounded number of times, logs only the
exception type name, returns `None`, and **never writes run state**. The inference
service is the only production caller of `transition_analysis_run` to `failed`, and it
does so only after `queued → running`. Legal CAS transitions today are
`queued → running` and `running → completed|failed`. **`queued → failed` is illegal.**

That behavior is **intentional S-04 design** (“honest queued” during cold-start; service
owns terminal state). It now conflicts with the PRD: every unsuccessful run must expose
terminal `failed` and a useful error. After finite retries there is no reclaim path for
stuck `queued` (stale reclaim covers only `running`). The UI polls every 5 seconds and
renders forever-queued as **in-progress**, not as failure.

Re-raising from dispatch would **not** fix this: `BackgroundTasks` run after `202`, so an
uncaught exception still leaves the row `queued`. The safe contract is: keep bounded
retry and log-without-secrets; after dispatch is known non-recoverable, the **API**
CAS-transitions `queued → failed` with a public error code. CAS `expected_status="queued"`
refuses overwrite if the service already claimed `running`.

Only one test locks the current product oracle:
`test_exhausted_dispatch_preserves_queued_run`. Invert that GET after create; keep
dispatch unit tests (retry/logging, no DB) and inference-service tests (fail after claim).

## Detailed Findings

### 1. Create-run and background dispatch

[`src/api/main.py:556-601`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/api/main.py#L556-L601)
creates the run as `queued` with `error_code=None` and `completed_at=None`, then
`background_tasks.add_task(_dispatch_queued_run, …)` and returns the stored row.
The HTTP response does **not** wait for dispatch.

[`src/api/main.py:140-141`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/api/main.py#L140-L141)
calls `dispatch_analysis_run(run_id, resolved_settings)` and discards any result
(the function is typed `-> None` anyway).

Starlette/FastAPI `TestClient` runs `BackgroundTasks` synchronously after building the
response and before returning to the test. That is why
`test_exhausted_dispatch_preserves_queued_run` can assert retry count and then GET the
run on the same request cycle. The POST body can still say `queued` even if a later
background task marks `failed`; **GET after the task** is the persistence oracle.

### 2. Dispatch swallows failure and leaves the row unchanged

[`src/api/inference_dispatch.py:32-52`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/api/inference_dispatch.py#L32-L52):

> Activate inference for `run_id` without writing terminal run state.
> Missing configuration, exhausted retries, and network errors are logged
> without a token or object-store secret. The queued row is left unchanged.

Outer `except Exception` logs `type(error).__name__` only. Inner `_dispatch`:

| Condition | Behavior | DB write |
| --- | --- | --- |
| Both URL and token missing | debug skip, return | none — stays queued |
| One of URL/token at startup | `ApiSettings` raises; API will not start | N/A |
| `ConnectionRefusedError` / timeout / other retryable | bounded retry + backoff; then warning + return | none |
| Non-retryable POST exception | warning + return | none |
| HTTP 408/425/429/5xx | retry; exhaust → warning + return | none |
| HTTP 401 (and other non-transient ≥400) | one attempt, warning, return | none |
| HTTP &lt; 400 | return success | none (service may have claimed) |

Logs omit token, `Authorization`, and `Bearer`
([`tests/test_inference_dispatch.py:73-93`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/tests/test_inference_dispatch.py#L73-L93)).
Keep that invariant.

### 3. Status machine: only the runner can fail, and only after claim

[`src/api/storage.py:85-87`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/api/storage.py#L85-L87):

```text
_LEGAL_RUN_TRANSITIONS = {queued→running, running→completed, running→failed}
```

`queued → failed` hits `RunStatusConflict` before SQL
([`storage.py:930-931`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/api/storage.py#L930-L931)).

Failed UPDATE writes `status`, `error_code`, `completed_at`, and optional
`validation_report_json` (`COALESCE`), plus audit `analysis.failed`. It does not
write result rows.

Production `transition_analysis_run` callers: **only**
[`src/inference_service/runner.py`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/inference_service/runner.py).
Claim is `queued → running` (`:79-84`). `_fail_run` is always
`running → failed` (`:132-144`), used after scoring errors and stale-running reclaim.
There is **no** path that fails a still-`queued` run.

Public error codes live in
[`src/inference_service/errors.py:5-18`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/inference_service/errors.py#L5-L18)
(`SAFE_MESSAGES`). Catch-all is `INFERENCE_FAILED`. There is **no** dispatch-specific
code (`INFERENCE_DISPATCH_FAILED` / `DISPATCH_FAILED`).

### 4. Race with a claimed run

Claim happens **before** scoring returns HTTP
([`runner.py:78-84`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/inference_service/runner.py#L78-L84)).
Default read timeout is 5s (`src/api/settings.py`). If the service claims then the
client times out, a retry may see `running` and treat HTTP &lt; 400 as dispatch success.
If the process dies after claim, stale reclaim (health / execute) can mark
`running → failed` with `INFERENCE_FAILED`.

Implication for this change: **fail from the API only when the row is still `queued`.**
CAS `expected_status="queued", next_status="failed"` is a no-op conflict if the service
already moved the row. Do not use `expected_status="running"` for never-started runs.
Do not treat a timeout after a successful HTTP as “undispatchable” without checking
persisted status.

True unavailability (connection refused, no listener) never claims → row stays
`queued` today. That is the ticket.

### 5. Operator-visible hang

[`frontend/src/App.tsx:85-95`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/frontend/src/App.tsx#L85-L95)
polls every 5s while any run is `queued` or `running`.
[`App.tsx:2275-2279`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/frontend/src/App.tsx#L2275-L2279)
renders queued/running as progress: “still in progress.” Failed uses a distinct tone
and the stored execution report. A forever-queued run looks like ongoing work, not a
crash and not a terminal error.

No frontend change is required for the contract if GET starts returning `failed` +
`error_code`; the existing failed rendering should pick it up. Cheapest verification
is API integration, not Playwright (test-plan: publication E2E only; this risk is
absent from the risk map).

### 6. Tests that lock current behavior

| Test | Oracle | Breaks if exhausted dispatch → failed? |
| --- | --- | --- |
| [`test_exhausted_dispatch_preserves_queued_run`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/tests/test_api.py#L1507) | After BG dispatch, GET `queued`, `error_code is None`, `completed_at is None`; 2 POSTs | **Yes — invert this** |
| `test_published_v2_model_queues_and_schedules_dispatch` | `202` + payload `queued`; stubs `dispatch_analysis_run` | No |
| `_queued_v2_run` | no-op dispatch so later tests own CAS | No |
| Result/provisional empty-state tests | stub dispatch; manual `running→failed` | No |
| `tests/test_inference_dispatch.py` | retry/logging; **no DB** | No for status; keep “does not raise” / secrets |
| `tests/test_inference_service.py` | fail **after claim** (`INFERENCE_FAILED`, catalog, unmatched, …) | No |
| `test_legal_cas_stores_summary_and_illegal_cas_conflicts` | illegal transitions raise | **Maybe** — add `queued→failed` as legal and keep other illegal pairs |

Lesson prior ([`context/foundation/lessons.md`](context/foundation/lessons.md)):
exercise real isolated subprocesses for ML wiring. Dispatch tests stub HTTP; they
must not be treated as proof of inference subprocess wiring. Do not expand this
change into `@ml` subprocess coverage.

### 7. PRD vs S-04 “honest queued”

PRD ([`context/foundation/prd.md:168`](context/foundation/prd.md)):

> Every unsuccessful analysis run exposes a terminal failed status and a useful error;
> no maximum failure-detection time is specified for the MVP.

Roadmap S-04: Operator sees a **terminal** run status.

S-04 plan selected decision
([`context/archive/2026-09-11-run-parity-hdfs-analysis/plan.md:36-37`](context/archive/2026-09-11-run-parity-hdfs-analysis/plan.md)):

> Dispatch the private service after the API has acknowledged `queued`; transient
> activation errors retain the queued run rather than becoming terminal failures.

Phase 4 contract (`plan.md:388-390`): dispatch failures remain queued, logged safely,
never fabricate completion; **the service owns terminal state**.

That carve-out is compatible with “no max failure-detection time” **only while**
something can still activate the run. After finite retries with no further worker,
the run is unsuccessful in practice but not terminal. Stale **`running`** was later
closed to `failed`; stuck **`queued`** was left as accepted cold-start behavior.

Recommended contract for planning:

1. Keep `202` + initial `queued` (async ack).
2. Keep bounded cold-start retry; do not fabricate `completed`.
3. After exhaustion / permanent non-retryable HTTP: API CAS `queued → failed`.
4. Missing both URL and token: product choice (stay skipped vs fail the inserted row);
   do not fail at create unless you want Operators to see 4xx/5xx instead of `202`.
5. Public message from a stable code; diagnostics stay in server logs.
6. No polling worker, no Sentry, no Playwright, no model deserialization.

## Code References

- [`src/api/main.py:140-141`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/api/main.py#L140-L141) — background dispatch; return ignored
- [`src/api/main.py:556-601`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/api/main.py#L556-L601) — `202`, insert queued, schedule task
- [`src/api/inference_dispatch.py:32-52`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/api/inference_dispatch.py#L32-L52) — swallow + “queued row is left unchanged”
- [`src/api/inference_dispatch.py:91-150`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/api/inference_dispatch.py#L91-L150) — retry / skip / HTTP handling
- [`src/api/storage.py:85-87`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/api/storage.py#L85-L87) — legal transitions; no `queued→failed`
- [`src/inference_service/runner.py:54-144`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/inference_service/runner.py#L54-L144) — claim then complete/fail
- [`src/inference_service/errors.py:5-18`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/src/inference_service/errors.py#L5-L18) — public error codes
- [`tests/test_api.py:1507-1561`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/tests/test_api.py#L1507-L1561) — lock-in: exhausted dispatch preserves queued
- [`frontend/src/App.tsx:85-95`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/frontend/src/App.tsx#L85-L95) — poll queued/running
- [`frontend/src/App.tsx:2275-2285`](https://github.com/michaail/hybrid-logs-analyzer/blob/b8a0706d0b5897e823b9f8a309abad17ececacd4/frontend/src/App.tsx#L2275-L2285) — queued = progress, failed = error copy

## Architecture Insights

- **Two owners of terminal state.** S-04 split “activate” (API, non-terminal) from
  “execute” (inference service, terminal). The gap is pre-claim failure: activate can
  finish with no owner left to terminalize.
- **Do not uncatch.** An exception from `BackgroundTasks` is not an Operator-visible
  API error and does not mutate the row. Structured outcome + CAS is the product fix.
- **CAS is the race control.** Adding `("queued", "failed")` plus
  `expected_status="queued"` is the same pattern as duplicate claim
  (`queued → running` conflict).
- **Layering.** Dispatch should classify “definitively did not activate” without
  importing the database. The API (or a small helper used from `_dispatch_queued_run`)
  should own the fail write, matching who inserted the row.
- **Cheapest test.** Integration on the existing exhausted-dispatch fixture. Do not
  promote to E2E. Do not add Sentry for the lesson exercise; PRD non-goal is external
  operational integrations.

## Historical Context (from prior changes)

- [`context/archive/2026-09-11-run-parity-hdfs-analysis/plan.md`](context/archive/2026-09-11-run-parity-hdfs-analysis/plan.md)
  — selected decision: transient activation retains queued; Phase 4: dispatch never
  fabricates completion; service owns terminal transitions.
- [`context/archive/2026-09-11-run-parity-hdfs-analysis/research.md`](context/archive/2026-09-11-run-parity-hdfs-analysis/research.md)
  — accepted runs should use terminal `failed` + codes such as `INFERENCE_FAILED`;
  that list described **worker** failures, not dispatch exhaustion.
- [`context/archive/2026-09-11-run-parity-hdfs-analysis/reviews/impl-review.md`](context/archive/2026-09-11-run-parity-hdfs-analysis/reviews/impl-review.md)
  — confirmed non-terminal dispatch; closed stale **running**, not stuck queued.
- [`context/foundation/test-plan.md`](context/foundation/test-plan.md) — this failure
  mode is not in the risk map; cheapest layer for a new oracle is still HTTP/integration.

## Related Research

- [`context/archive/2026-09-11-run-parity-hdfs-analysis/research.md`](context/archive/2026-09-11-run-parity-hdfs-analysis/research.md) — HDFS inference-only analysis, parity, and run reporting

## Open Questions

1. New public code (`INFERENCE_DISPATCH_FAILED`) vs reuse `INFERENCE_FAILED` for
   never-claimed activation?
2. After exhaustion, fail immediately when the background task finishes, or keep a
   grace window analogous to 30-minute stale-running reclaim?
3. If inference URL/token are both unset, should create still insert `queued` (current
   debug skip) or fail the row / reject create?
4. Is Operator re-dispatch (retry button) in scope? MVP recommendation: fail-closed
   only; no new retry API.
5. Should README / deploy-plan “honest queued” wording be narrowed to the retry window
   only, once this lands?
