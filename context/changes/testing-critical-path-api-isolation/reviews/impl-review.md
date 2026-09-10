<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Critical-path API isolation tests

- **Plan**: context/changes/testing-critical-path-api-isolation/plan.md
- **Scope**: Phase 1–3 of 3
- **Date**: 2026-09-10
- **Verdict**: APPROVED
- **Findings**: 0 critical 0 warnings 1 observation

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

### F1 — Own-project empty models list is not asserted for project B

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: tests/test_api.py:486-490
- **Detail**: Phase 1 Changes Required explicitly require empty `GET /projects/{B}/analysis-runs` (asserted at lines 531–536). Cookbook §6.2 item 3 generalizes that oracle to member-route lists including models. `test_cross_project_member_routes_return_404` asserts A's model list unchanged after a foreign register 404, and IDOR get-by-id under B, but never `GET /projects/{B}/models` → 200 + `[]` while A holds a version. A list-models query that ignored `project_id` would not be caught here. Foreign list-models 404 on A's path is covered by `test_authentication_roles_and_project_isolation`.
- **Fix**: In `test_cross_project_member_routes_return_404`, after A has a registered model, assert `GET /projects/{B}/models` as `operator_b` (or `publisher_b`) is 200 and `[]`.
- **Decision**: PENDING
