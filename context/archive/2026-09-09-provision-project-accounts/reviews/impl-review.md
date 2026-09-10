<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Provision project-authorized accounts

- **Plan**: context/changes/provision-project-accounts/plan.md
- **Scope**: Phase 4 of 4 (all phases complete)
- **Date**: 2026-09-10
- **Verdict**: APPROVED
- **Findings**: 0 critical 1 warnings 1 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — Administration refresh fails closed when project resource GETs fail

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: frontend/src/App.tsx:118-155
- **Detail**: `refreshProjectData` loads models, analysis-runs, and datasets in one `Promise.all` and only then loads accounts, memberships, and system audit. A 500 from `GET /projects/{id}/analysis-runs` (for example a missing later-slice `datasets` table) aborts the whole refresh, so Administration shows no users even though `GET /admin/users` succeeds. This matches the observed UI failure; FastAPI `/docs` was unaffected because it does not share that client batch.
- **Fix**: Split administrator account/membership/audit fetches from the models/runs/datasets batch so a project-resource failure still populates Administration, and keep the resource error as a page banner.
- **Decision**: FIXED

### F2 — Unaudited `create_user` / `create_project` remain as test seed helpers

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: src/api/storage.py:148
- **Detail**: The plan replaced independent write-and-commit helpers with audited lifecycle methods. HTTP and CLI now use `provision_project_account`, `create_administrator`, and `create_project_with_audit`. `create_user` still inserts without an audit row and can set `is_administrator=True`; `create_project` still inserts without audit. Both are called from `tests/test_api.py`, `tests/test_migrations.py`, and `tests/test_shared_state_repository.py`, not from `src/api/main.py`. `POST /admin/users` is gone (OpenAPI GET-only; POST returns 405).
- **Fix**: After operator confirmation, keep these as explicit test-only seeds or switch tests onto the audited methods. Do not re-expose them over HTTP.
- **Decision**: SKIPPED
