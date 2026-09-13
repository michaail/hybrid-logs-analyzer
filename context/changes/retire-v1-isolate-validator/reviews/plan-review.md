<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Retire v1 and Isolate Validator Implementation Plan

- **Plan**: `context/changes/retire-v1-isolate-validator/plan.md`
- **Mode**: Deep
- **Date**: 2026-09-13
- **Verdict**: SOUND (after triage)
- **Findings**: 0 critical, 6 warnings, 0 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | WARNING (F4, F3 — both fixed) |
| Lean Execution | PASS |
| Architectural Fitness | WARNING (F1 — fixed) |
| Blind Spots | WARNING (F2 — fixed) |
| Plan Completeness | WARNING (F3, F5, F6 — fixed) |

## Grounding

Grounding: 6/6 existing paths ✓ (`src/api/{storage,validation,main,settings}.py`, `src/modules/model_package.py`, `scripts/e2e_serve.py`), 3/3 symbols ✓ (`run_private_package_validator`, `admit_uploaded_zip_package`, `build_object_store`), brief↔plan ✓

## Findings

### F1 — Required File(...) conflicts with a typed {valid, issues[]} 422

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Architectural Fitness
- **Location**: Phase 2 — Register route copy + Admission preview
- **Detail**: Making `preprocessing_bundle` `File(...)` causes Starlette 422 when the part is omitted. That is not `PackageValidationResult`. The UI only unwraps `detail.issues[].reason`.
- **Fix A ⭐ Recommended**: Keep `File(default=None)`; reject missing/empty bundle in `admit_uploaded_zip_package` with typed issues; UI/E2E still always send the file.
- **Fix B**: `File(...)` plus `RequestValidationError` → typed envelope.
- **Decision**: FIXED (Fix A)

### F2 — Cleanup `delete_prefix(package_reference)` is wrong for workspace-kind rows

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 — Retire CLI
- **Detail**: ZIP leftovers are object-kind; schema/tests still have workspace-kind rows and empty prefixes. Blind `delete_prefix` is a no-op, collision, or ValueError.
- **Fix**: Only `delete_prefix` for `storage_kind=object` with a non-empty prefix; skip workspace/empty with a printed reason; dependents still exit 1.
- **Decision**: FIXED

### F3 — Phase 2 can close while Playwright (and CI e2e) still fail

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — E2E seed and Success Criteria
- **Detail**: Phase 2 changes E2E helpers/specs; Progress did not run Playwright; CI does.
- **Fix**: Add `npm --prefix frontend run test:e2e` as Phase 2 automated 2.7.
- **Decision**: FIXED

### F4 — After Phase 3, README/Docker factory register 503s with no documented validator env

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Phase 3 — API settings and client
- **Detail**: Intended 503-if-neither-set; README factory and Dockerfile use `from_environment()` with no command. e2e_serve already injects files-only.
- **Fix**: Document `MODEL_VALIDATOR_*` on README and `.env.example`; point local UI at `scripts/e2e_serve.py`; do not restore hidden module fallback.
- **Decision**: FIXED

### F5 — Validator HTTP client could silently add httpx to the API image

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 3 — API settings and client
- **Detail**: Inference uses stdlib `http.client`; httpx is dev-only.
- **Fix**: Specify stdlib multipart POST; do not add httpx to `requirements-api.txt`.
- **Decision**: FIXED

### F6 — `@pytest.mark.ml` probe coverage is required in the contract but not in Progress

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 3 — Validator tests / Success Criteria
- **Detail**: 3.1 is `not ml`; lesson requires a real probe; Ubuntu CI skips `@ml`.
- **Fix**: Phase 3 Manual 3.8 — owner confirms `@ml` validator-app probe in a local ML venv.
- **Decision**: FIXED
