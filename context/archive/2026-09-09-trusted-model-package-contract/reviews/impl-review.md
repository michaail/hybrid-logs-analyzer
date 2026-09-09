<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Trusted model package contract

- **Plan**: context/changes/trusted-model-package-contract/plan.md
- **Scope**: Phase 1–4 of 4
- **Date**: 2026-09-09
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical 5 warnings 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | WARNING |

## Findings

### F1 — Leftover pipeline-manifest copy in the models view

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: frontend/src/App.tsx:556, frontend/src/App.tsx:614-615
- **Detail**: The registration dialog now sends only `package_reference` and warns that the API never receives model bytes. The models empty state still says a Publisher can register a “complete HDFS pipeline manifest”, and the info-strip still says the client “registers a trusted pipeline manifest”. Phase 3 required dropping pipeline-manifest language from that UI.
- **Fix**: Rewrite those two strings to “pre-staged HDFS model package directory” (or equivalent) so they match the dialog and README.
- **Decision**: FIXED

### F2 — Symlink rejection runs after Path.resolve()

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/modules/model_package.py:445-461, src/api/validation.py:110-116
- **Detail**: Both the directory validator and `admit_validated_package` call `.resolve()` (which follows the symlink) and then `is_symlink()` on the target. An in-workspace symlink therefore looks like a regular file. Out-of-workspace targets still fail `relative_to`, but a declared `model.pt` can alias another file inside the trusted workspace. There are no symlink tests. Plan F5 asked for resolved-containment plus symlink escape handling.
- **Fix A ⭐ Recommended**: `lstat` / `is_symlink()` on the unresolved path, then `resolve()` and `relative_to(package_root)` (validator) or `relative_to(workspace)` (admit). Re-hash the artifact in `admit_validated_package`. Add a test that a declared symlink is rejected.
  - Strength: Matches the plan’s “regular file, not a symlink” contract and closes the TOCTOU/alias gap.
  - Tradeoff: A few extra path checks and one new test.
  - Confidence: HIGH — the current `is_symlink()` after resolve cannot see the link.
  - Blind spot: macOS vs Linux `lstat` behavior on dangling links.
- **Fix B**: Keep resolve+relative_to as the only containment rule and drop the ineffective `is_symlink()` check.
  - Strength: Smaller change; containment already blocks links that escape the root.
  - Tradeoff: In-workspace aliasing of the artifact remains allowed.
  - Confidence: MEDIUM — enough for zip-slip-style escape, not for “must be a regular file”.
  - Blind spot: Whether later inference will re-read through a swapped symlink.
- **Decision**: FIXED via Fix A

### F3 — Validator subprocess still inherits non-prefixed application secrets

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/api/validation.py:21-33, src/api/validation.py:191-200, src/model_validator/runtime.py:13-36
- **Detail**: Scrubbing removes `API_*`, `AWS_*`, `RAILWAY_*`, `BUCKET_*`, and `DATABASE_URL`. `.env.example` still documents `AZURE_OPENAI_API_KEY` and similar names that are copied into the child. The child also inherits the API user’s filesystem view (`cwd=code_root`). The plan required a scrubbed environment with no application secrets and access only to the package source. Duplicate allowlists in API vs runtime can drift.
- **Fix A ⭐ Recommended**: Allowlist the child env (`PATH`, `HOME`, `LANG`, `PYTHONPATH`, `VIRTUAL_ENV`) from one shared helper used by both the API and `python -m src.model_validator`.
  - Strength: Closes Azure/other secret leak in one place; matches “minimum privilege”.
  - Tradeoff: Some ML runtimes expect extra env vars; those would need an explicit allowlist.
  - Confidence: HIGH — current prefix denylist is incomplete by construction.
  - Blind spot: Whether Torch or site-packages need extra vars on this Intel Mac.
- **Fix B**: Add `AZURE_`, `HF_`, `OPENAI_`, `PGPASSWORD` to the denylist only.
  - Strength: Small patch for the known `.env.example` keys.
  - Tradeoff: The next unprefixed secret is missed again.
  - Confidence: LOW — denylists rot.
  - Blind spot: Full process env on Railway.
- **Decision**: FIXED via Fix A

### F4 — HTTP admission tests stub the tensor probe, so dummy `.pt` can register

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Success Criteria
- **Location**: tests/test_api.py:43-46, tests/support/files_only_validator.py:17, tests/support/rejecting_artifact_validator.py:21-28
- **Detail**: The default API fixture runs `files_only_validator.py`, which calls `validate_model_package` without `load_state_dict`. Happy-path 201 therefore persists dummy artifact bytes. Dummy rejection uses `rejecting_artifact_validator.py`, which appends a fake issue and never loads Torch. Plan: dummy/pickle `.pt` → 422 and stop accepting dummy checkpoints. Real `weights_only=True` coverage is only in `@pytest.mark.ml` unit tests, not the HTTP path. A broken `python -m src.model_validator` wiring would not fail `tests/test_api.py`. A one-off live script in this session did 201 through the real validator; that is not a checked-in test.
- **Fix A ⭐ Recommended**: Add an `@pytest.mark.ml` API test that uses `(sys.executable, "-m", "src.model_validator")` for dummy/pickle 422 and a tiny real state-dict 201.
  - Strength: Proves the production subprocess path without forcing Torch on the default API suite.
  - Tradeoff: ML-marked tests still skip in the restricted sandbox.
  - Confidence: HIGH — matches existing `@pytest.mark.ml` convention.
  - Blind spot: CI image may lack Torch.
- **Fix B**: Keep Torch-free API tests; document the stub as the official HTTP seam and rely on unit ML tests only.
  - Strength: Default pytest stays green without Torch.
  - Tradeoff: Admission wiring of the real validator remains untested in-repo.
  - Confidence: MEDIUM — live script already passed once.
  - Blind spot: Future refactors of `run_private_package_validator`.
- **Decision**: FIXED via Fix A

### F5 — SQLite migration 002 is two non-idempotent ALTER statements

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/migrations.py:103-115, src/api/storage.py:67-70, src/api/storage.py:91-95
- **Detail**: Plan-review F4 asked for transactional DDL. The implementation sets SQLite `isolation_level=None` and `BEGIN` in `session()`, which is the right shape. `002` is still two `ADD COLUMN` statements without existence checks. If SQLite implicit-commits DDL (or a crash lands between the two ALTERs), retry fails with duplicate column name. `001` used `IF NOT EXISTS`.
- **Fix**: Before each ADD COLUMN, skip if `PRAGMA table_info(model_versions)` already has the name; record `002` only when both columns exist.
- **Decision**: FIXED

### F6 — Manual Progress rows were checked without a browser /docs or React pass

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Success Criteria
- **Location**: context/changes/trusted-model-package-contract/plan.md:638-653
- **Detail**: 3.5–3.7 and 4.4–4.5 are `[x]`. Observable evidence: TestClient Publisher 201 / Operator 403 / structured 422 / `not_supported`; a one-off real-validator script; OpenAPI test; frontend production build; dialog warning-strip. There is no recorded `/docs` or React-dialog session. Zip-slip “no files outside extract root” is proven by `test_zip_slip_member_is_rejected_without_writing_outside`, which is stronger than a manual unzip. The rubber-stamp risk is the UI/docs flow, not zip extraction.
- **Fix**: Re-run 3.5–3.6 and 4.4–4.5 in `/docs` and the React dialog against a pre-staged package, or downgrade those Progress rows until that happens.
- **Decision**: FIXED

### F7 — Zip extract trusts declared uncompressed sizes

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/modules/model_package.py:570-580, src/modules/model_package.py:642-647
- **Detail**: Caps use `ZipInfo.file_size` as the plan specified. Extract copies chunks with no running total, so a lying header is still a zip bomb. The API does not extract zips today; S-02 will call this helper.
- **Fix**: Abort extract when bytes written exceed `MAX_ZIP_UNCOMPRESSED_BYTES` (and per-member `file_size`).
- **Decision**: FIXED
