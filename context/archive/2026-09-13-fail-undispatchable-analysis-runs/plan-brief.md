# Fail undispatchable analysis runs — Plan Brief

> Full plan: `context/changes/fail-undispatchable-analysis-runs/plan.md`
> Research: `context/changes/fail-undispatchable-analysis-runs/research.md`

## What & Why

An HDFS analysis run currently remains `queued` if the private inference service cannot
be activated after its finite retry policy. The Operator sees ongoing progress forever,
despite the PRD requiring every unsuccessful run to expose terminal `failed` and a useful
error.

This change makes failure to activate inference durable and visible without changing how
the HDFS model is loaded, scored, or executed.

## Starting Point

The public API creates a run, returns `202 queued`, and dispatches inference in a
background task. The dispatcher logs failures without secrets but returns no outcome;
only the inference service can currently fail a run, and it can do so only after claiming
`queued → running`.

## Desired End State

A valid request remains asynchronous: `POST` returns initial `202 queued`. If dispatch
does not activate inference after configured bounded retry, the API atomically changes the
still-queued run to `failed` with `INFERENCE_DISPATCH_FAILED`, a safe generic report,
completion timestamp, and audit record.

A run already claimed by inference is never overwritten. The existing inference service
continues to own execution failures after `running`.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Final dispatch policy | Fail after finite retry | A forever-queued run violates the PRD terminal-status contract. | Plan |
| Ambiguous timeout | Fail after policy exhaustion | Keeps lifecycle finite and avoids adding a recovery protocol or worker. | Plan |
| Missing paired settings | Queue then fail in background | Preserves `202` and creates a traceable failure record. | Plan |
| Public error code | `INFERENCE_DISPATCH_FAILED` | Separates pre-claim activation failure from worker/scoring failure. | Plan |
| Concurrency guard | CAS `queued → failed` | Cannot overwrite a run the inference service already claimed. | Research |
| Recovery | No retry API or worker | Avoids duplicate-execution and scheduling scope in this MVP. | Plan |

## Scope

**In scope:**
- Typed dispatch outcomes and safe failure classification.
- API-owned guarded terminalization of an unclaimed run.
- Additive `queued → failed` transition, tests, README, and deployment-guide updates.

**Out of scope:**
- Browser E2E, Sentry, retry UI/API, durable worker, BGL, inference/model changes, and
  database migrations.

## Architecture / Approach

`POST` creates `queued` → background dispatch reports accepted/failed outcome → on failure
the API performs `queued → failed` through the existing compare-and-swap repository seam.
The inference service separately owns `queued → running → completed|failed` once it wins
the claim.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Dispatch outcome and transition | Safe dispatch result and CAS failure path | Late service claim must not be overwritten |
| 2. Regression and boundary coverage | Red/green API, dispatcher, and state-machine proof | Testing create response instead of durable state |
| 3. Documentation alignment | Correct local and staging lifecycle guidance | Stale “queued forever” operator expectations |

**Prerequisites:** Existing HDFS v2 fixture, API test harness, and completed research.
**Estimated effort:** One focused implementation session plus manual local/staging check.

## Open Risks & Assumptions

- A timeout can be ambiguous: the selected finite-failure policy prefers terminal
  observability over allowing a late claim to start work.
- Existing queued rows are not backfilled; only runs created after deployment receive the
  new behavior.
- The existing single-run scale and bounded retry budget remain suitable for this MVP.

## Success Criteria (Summary)

- A connection-refused, unconfigured, or final non-2xx dispatch leaves a new HDFS run
  `failed`, not indefinitely `queued`.
- The initial API acknowledgement remains `202 queued`, and normal claimed-run execution
  is unchanged.
- Operators see only a stable code and generic message; logs and API responses contain no
  private-service or credential detail.
