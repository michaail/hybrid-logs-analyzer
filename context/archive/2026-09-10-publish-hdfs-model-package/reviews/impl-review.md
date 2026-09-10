<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Publish HDFS Model Package

- **Plan**: context/changes/publish-hdfs-model-package/plan.md
- **Scope**: Phases 1–4 of 4
- **Date**: 2026-09-10
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical 2 warnings 6 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | WARNING |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — Unplanned files landed in slice commits

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Scope Discipline
- **Location**: 8a6d902 (`.cursor/*`), 6370900 (`.github/workflows/verify.yml`)
- **Detail**: Phase 1 committed `.cursor` skill/rule/manifest updates that are not in the plan's Changes Required. Phase 4 also added `verify.yml` pytest paths (adapter + model-package tests) which the plan did not list as a file to touch, though they match Phase 4 automated verification. Roadmap `in-progress` in 8a6d902 is expected by `/10x-implement`. Change-folder docs in p1 are expected bootstrap.
- **Fix A ⭐ Recommended**: Keep the files. Treat `.cursor` as incidental tooling already on the branch; keep the CI pytest expansion because it is how 4.1 stays enforced in GitHub Actions.
  - Strength: No product behavior change; CI now runs the adapter tests the plan requires.
  - Tradeoff: The slice history includes unrelated skill-file noise.
  - Confidence: HIGH — none of these files alter admission, storage, or authz.
  - Blind spot: Whether the `.cursor` edits were meant for a different lesson branch.
- **Fix B**: Revert the `.cursor` paths from this branch and leave `verify.yml` as-is.
  - Strength: Restores a tighter slice diff.
  - Tradeoff: Rewrites history or a revert commit; later agents lose the skill updates.
  - Confidence: MEDIUM — depends whether other work on the branch needs those skill files.
  - Blind spot: Downstream 10x-cli consumers of the manifest.
- **Decision**: FIXED via Fix A — keep `.cursor` tooling and the `verify.yml` pytest expansion

### F2 — Leftover unused admission/UI helpers

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: src/api/validation.py:65 (`trusted_package_directory`); frontend/src/App.tsx:52 (`publishedModels`)
- **Detail**: After ZIP-only HTTP admission, `trusted_package_directory` has no callers. `publishedModels` is computed and never read (pre-existing; research already noted it). `admit_validated_package` is still used by tests for symlink rejection, so it is not dead. lessons.md requires operator confirmation before deleting unused code after impl-review.
- **Fix**: Confirm with the operator, then delete `trusted_package_directory` and the unused `publishedModels` memo. Leave `admit_validated_package` while tests still call it.
- **Decision**: FIXED — removed `trusted_package_directory` and the unused `publishedModels` memo

### F3 — Duplicate 409 does not assert prefix cleanup

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: tests/test_api.py:444; src/api/main.py:434-437
- **Detail**: The testing strategy asked for “duplicate identity → 409 + no orphan prefix.” HTTP does `object_store.delete_prefix` on `DatabaseIntegrityError`, and 409 is asserted, but the test never checks that a second put left no extra objects under the object root.
- **Fix**: After the duplicate 409, assert only the first version prefix remains (three declared files) and that a second UUID prefix was deleted.
- **Decision**: FIXED — duplicate 409 now asserts the original three declared objects remain and no second prefix was left

### F4 — Bucket dataclass flag can bypass the four-secret guard

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/settings.py:29-32; src/api/object_store.py:70-75
- **Detail**: `from_environment` requires endpoint, bucket, and both keys together. `uses_bucket_object_store` only checks `object_store_endpoint is not None`. A hand-built `ApiSettings` with a lone endpoint would select the Bucket backend and pass null access keys into boto3. Production startup uses `from_environment`; pytest injects a stub client. Live Railway `ref(bucket, …)` bindings were not exercised in this review (`bucket()` in railway/iac 3.11 has no `.env` accessor).
- **Fix**: Derive `uses_bucket_object_store` from all four fields being non-empty (same rule as `_bucket_credentials_from_environment`).
- **Decision**: FIXED — Bucket backend requires endpoint, bucket, and both access keys

### F5 — Staging API image cannot run the tensor probe

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/api/validation.py:82; Dockerfile; requirements-api.txt
- **Detail**: Late finding from [Safety quality patterns](f4fc6a65-e91a-42c9-bd96-6a86a6a78925). Default validator command is `sys.executable -m src.model_validator` in the same API runtime. The Docker image installs only Torch-free `requirements-api.txt`, so a real ZIP on Railway fail-closes as 503 (no unprobed insert). That matches isolation, but staging ZIP→eligible then depends on a Torch-bearing validator process that this slice did not ship. Local Intel venv still works. Plan 4.6 allowed skipping live Bucket if staging is unprovisioned.
- **Fix A ⭐ Recommended**: Document in `context/deployment/deploy-plan.md` that staging ZIP admission 503s until a Torch validator command/image is attached; do not put Torch in `requirements-api.txt`.
  - Strength: Keeps FastAPI Torch-free; matches the isolated-process contract.
  - Tradeoff: Railway Publishers cannot get `eligible` until that follow-on exists.
  - Confidence: HIGH — Dockerfile copies only `requirements-api.txt`.
  - Blind spot: Whether `API` already has an undocumented `model_validator_command` on staging.
- **Fix B**: Add a separate validator install path (second image or extra layer) and point `model_validator_command` at it, still without importing Torch in FastAPI.
  - Strength: Makes staging ZIP admission actually work.
  - Tradeoff: New image/contract work adjacent to S-04; easy to leak Torch into the API image.
  - Confidence: MEDIUM — no validator image exists yet.
  - Blind spot: Linux wheel availability for the Intel-locked Torch stack.
- **Decision**: PENDING

### F6 — JSON `package_reference` POST is a FastAPI missing-file 422

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: tests/test_api.py:607-612; src/api/main.py:385-386
- **Detail**: Late finding from [Plan drift detection](1be1a656-a267-4106-bba8-938a73c8c5b7). The public JSON registration schema is gone (MATCH). A JSON POST still returns 422 because the `package` file is missing, not because the handler emits `{valid, issues[]}`. The structured envelope is used for ZIP content failures. Plan asked for that envelope on non-ZIP/oversize.
- **Fix**: Map missing/`RequestValidationError` for this route to `{valid: false, issues: [{path: "package", reason: "..."}]}` if the old JSON body must look like an ineligible package. Otherwise leave FastAPI's default 422 — clients that send JSON are already rejected.
- **Decision**: PENDING

### F7 — S3 `delete_objects` per-key errors are ignored

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/object_store.py:155-157
- **Detail**: Late finding from [Safety quality patterns](f4fc6a65-e91a-42c9-bd96-6a86a6a78925). boto3 can return HTTP 200 with an `Errors` list. A 409 prefix cleanup on Bucket could leave objects.
- **Fix**: Raise if `delete_objects` returns a non-empty `Errors` list.
- **Decision**: PENDING

### F8 — Non-409 insert failures do not delete the object prefix

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/main.py:434-439
- **Detail**: Late finding from [Safety quality patterns](f4fc6a65-e91a-42c9-bd96-6a86a6a78925). `delete_prefix` runs on `DatabaseIntegrityError` (the planned 409 path). Connection loss or other insert failures leave the already-written prefix. The leftover `admit_validated_package` helper remains test-only (intentional after F2).
- **Fix**: `delete_prefix` in a broader `except` around `create_model_version`, then re-raise (keep the 409 mapping for integrity errors).
- **Decision**: PENDING
