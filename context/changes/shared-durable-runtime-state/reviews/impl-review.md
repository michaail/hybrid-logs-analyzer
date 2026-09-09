<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Shared durable runtime state

- **Plan**: context/changes/shared-durable-runtime-state/plan.md
- **Scope**: Phase 1 of 4 through Phase 4 of 4 (full plan)
- **Date**: 2026-09-09
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical 4 warnings 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | WARNING |

## Findings

### F1 — Dataset upsert race rolls back the analysis run

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/api/storage.py:694
- **Detail**: `_upsert_dataset` is SELECT-then-INSERT on `(project_id, storage_kind, object_reference)` with no `ON CONFLICT` and no IntegrityError retry. Concurrent `POST /analysis-runs` for the same path can both miss the SELECT; the loser raises `DatabaseIntegrityError` inside `create_analysis_run`'s session, so the analysis run is rolled back too. `create_analysis_run` in `src/api/main.py` does not catch that error (unlike model register). Unique violation here should mean reuse, not HTTP 500. FastAPI sync routes run in a thread pool, so this is reachable without two processes. MVP currently expects one active analysis, which lowers the practical blast radius.
- **Fix A ⭐ Recommended**: Catch unique IntegrityError in `_upsert_dataset`, re-SELECT the existing row, and continue the run insert. Audit only on a true insert.
  - Strength: Keeps one transaction; matches the get-or-create contract; no HTTP 409 for a reused dataset.
  - Tradeoff: Dual-dialect `ON CONFLICT` / exception handling is a few extra lines and needs a concurrency test.
  - Confidence: HIGH — unique index already exists; S-01 already maps IntegrityError at other write sites.
  - Blind spot: Have not reproduced two overlapping POSTs under load.
- **Fix B**: Catch `DatabaseIntegrityError` in the HTTP analyze route and retry the whole `create_analysis_run`.
  - Strength: Leaves repository as-is.
  - Tradeoff: Can double-audit or retry rejected/not_supported inserts; weaker than fixing get-or-create at the source.
  - Confidence: MEDIUM — retrying the full run write is broader than the race.
  - Blind spot: Retry storms if the unique failure is a real duplicate of something else.
- **Decision**: Fixed via Fix A

### F2 — Listing analysis runs does N+1 dataset lookups

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: src/api/main.py:465
- **Detail**: `list_analysis_runs` maps every row through `_analysis_run_from_store`, which calls `database.get_dataset` → `_one()` → a new `session()` per run. Model list already has `storage_kind`/`checksum` on the row. MVP scale is small, but polling `queued`/`running` will amplify this.
- **Fix**: LEFT JOIN `datasets` in `list_analysis_runs` / `get_analysis_run` (or batch-load dataset ids once) and pass pointer fields into `_analysis_run_response` without a per-row session.
  - Strength: Matches how model pointer columns are already denormalized on the model row.
  - Tradeoff: Small SQL change; tests should still assert pointer fields.
  - Confidence: HIGH — column names are already on `datasets`.
  - Blind spot: None significant.
- **Decision**: Fixed via Fix now

### F3 — SQLite 002 eligibility is checked outside BEGIN IMMEDIATE

- **Severity**: 💤 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/migrations.py:201
- **Detail**: Postgres 002 runs under `pg_advisory_xact_lock` in the same session as the version read. SQLite 002 eligibility uses `_current_applied_versions()` in a separate committed session, then `_upgrade_shared_state_sqlite` starts `BEGIN IMMEDIATE`. Two local migrators can both pass the version check; the loser then hits `CREATE TABLE datasets` (no `IF NOT EXISTS`) after 002 is recorded. Winner's data stays intact; loser fails loudly. Unlikely outside overlapping CLI runs.
- **Fix**: After `BEGIN IMMEDIATE`, re-read `schema_migrations` and no-op if `002` is already present.
- **Decision**: Fixed via Fix now

### F4 — Manual `/docs` and Operator UI steps were checked without a live click-through

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Success Criteria
- **Location**: context/changes/shared-durable-runtime-state/plan.md:545
- **Detail**: Progress marks 3.4 and 4.4 `[x]` with SHAs. Automated HTTP tests cover register/publish/analyze, dataset list/get, stored summaries, and OpenAPI (no result POST). The React client lists datasets and `dataset_id`. There is no evidence of a live Operator session in `/docs` or the compiled UI. 1.4, 1.5, and 2.4 were executed as local commands; 4.5 is backed by OpenAPI tests plus README/deploy-plan text.
- **Fix A ⭐ Recommended**: Leave the checkboxes as recorded coverage of the HTTP/UI contract, and do a short Operator click-through before `/10x-archive`.
  - Strength: Does not rewrite history; still requires the missing live evidence.
  - Tradeoff: Archive waits on a local bootstrap + UI pass.
  - Confidence: HIGH — the missing evidence is specifically interactive, not code.
  - Blind spot: Staging/Railway UI was not in this review.
- **Fix B**: Re-open 3.4 and 4.4 as `[ ]` until a human confirms in `/docs` and the Analysis view.
  - Strength: Progress stays strictly honest.
  - Tradeoff: `/10x-archive` and the implemented stamp become inconsistent until a new Progress edit + commit.
  - Confidence: MEDIUM — epilogue already closed the plan.
  - Blind spot: Whether the operator already ran those steps locally after the commits.
- **Decision**: Fixed via Fix A — click-through recorded as a pre-archive follow-up

### F5 — README `pytest -m postgres` collects ML tests and can fail before dialect checks

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: README.md:379
- **Detail**: The FastAPI section documents `TEST_DATABASE_URL=... python -m pytest -m postgres`. `pyproject.toml` `testpaths = ["tests"]`, so collection imports `tests/test_pipeline_smoke.py`, which needs `drain3`. In this review that command aborted with `ModuleNotFoundError: No module named 'drain3'` and never ran the postgres-marked API tests. Targeting `tests/test_migrations.py tests/test_shared_state_repository.py -m postgres` passed (2 passed).
- **Fix**: Point the README command at those two files (and optionally add `pytest.ini` ignore/`norecursedirs` is out of scope). Do not add drain3 to the API venv.
- **Decision**: Fixed via Fix now

## Triage

- **Fixed**: F1 (Fix A), F2, F3, F4 (Fix A — follow-up), F5
- **Date**: 2026-09-09
