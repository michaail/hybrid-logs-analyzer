<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Fail undispatchable analysis runs

- **Plan**: context/changes/fail-undispatchable-analysis-runs/plan.md
- **Scope**: Phase 1–3 of 3
- **Date**: 2026-09-13
- **Verdict**: APPROVED
- **Findings**: 0 critical 0 warnings 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — HTTP 3xx counted as successful activation

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/inference_dispatch.py:171
- **Detail**: `status_code < 400` treats redirects as `DispatchOutcome.ok()`, so the callback skips `queued → failed`. `http.client` does not follow redirects. The plan and research treated HTTP &lt; 400 as accepted activation; Railway private HTTP is unlikely to redirect. A misconfigured URL that only returns 3xx would still leave a run queued.
- **Fix**: Treat success as `200 <= status_code < 300` so a final non-2xx response terminalizes the run.
- **Decision**: FIXED

### F2 — Callback CAS-miss path is untested

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: tests/test_shared_state_repository.py:356
- **Detail**: Production CAS (`WHERE status = 'queued'`) plus swallowed `RunStatusConflict` in `_dispatch_queued_run` correctly refuses to overwrite `running`/`completed`. The new repository test covers duplicate `queued → failed` and `queued → running` after already failed, not `queued → running` then `queued → failed`. There is no API test that the callback no-ops on that conflict.
- **Fix**: Add a repository assertion that `queued → running` then `queued → failed` raises `RunStatusConflict` and leaves status `running`.
- **Decision**: FIXED
