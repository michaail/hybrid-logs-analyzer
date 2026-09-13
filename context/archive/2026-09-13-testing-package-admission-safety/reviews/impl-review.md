<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Package admission leftover-prefix safety

- **Plan**: context/changes/testing-package-admission-safety/plan.md
- **Scope**: Phase 1–3 of 3
- **Date**: 2026-09-14
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

### F1 — Dual-prefix rollback stops after first delete_prefix failure

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/main.py:452-455
- **Detail**: `_delete_admitted_prefixes` deletes the package prefix, then the bundle prefix. After Phase 2, Bucket `delete_prefix` raises on a non-empty `Errors` list. If that raise happens on the package prefix, the bundle prefix is never attempted. v2 admit writes both prefixes before insert; the Phase 1 HTTP oracle uses a v1 ZIP with no bundle, so this interaction is untested. The same sequential pattern already exists in `src/api/validation.py` put-failure cleanup.
- **Fix A ⭐ Recommended**: Attempt both deletes in `_delete_admitted_prefixes` (try/finally or collect-and-re-raise), then propagate the first error.
  - Strength: Matches the lesson to delete every written prefix on failed admission; one helper, no new tests required for v1.
  - Tradeoff: Still no v2 leftover HTTP coverage unless a follow-up test is added.
  - Confidence: HIGH — same two prefixes are already known at this call site.
  - Blind spot: Put-failure cleanup in `validation.py` has the same sequential gap.
- **Fix B**: Extract a shared “delete package then bundle, always both” helper used by register and `validation.py`.
  - Strength: Closes the same gap on put-failure cleanup, not only insert rollback.
  - Tradeoff: Wider than this change’s planned files.
  - Confidence: MEDIUM — helper shape needs to match both call sites.
  - Blind spot: Callers besides register/admit not audited.
- **Decision**: FIXED via Fix A

### F2 — HTTP leftover test treats any 5xx as the insert failure

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: tests/test_api.py:1248-1250
- **Detail**: Nested `TestClient(..., raise_server_exceptions=False)` plus `status_code >= 500` also matches a validator **503** (or any crash before `put`). Empty `_object_files` then means “never wrote,” not “rolled back.” Sibling `_fail_audit_event` tests assert `RuntimeError` / `"forced audit failure"`. In the full `test_api.py` suite the same ZIP is 201 elsewhere, so this is unlikely in CI. Nested TestClient was a necessary adaptation so Starlette does not surface the re-raised `RuntimeError` instead of HTTP 5xx.
- **Fix**: Assert `failed.status_code == 500` (and keep `_object_files == set()`).
- **Decision**: FIXED
