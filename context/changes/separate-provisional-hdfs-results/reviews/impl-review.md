<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Separate Provisional HDFS Results

- **Plan**: `context/changes/separate-provisional-hdfs-results/plan.md`
- **Scope**: Phases 1–5 of 5
- **Date**: 2026-09-13
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical 2 warnings 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | WARNING |
| Safety & Quality | PASS |
| Architecture | WARNING |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — Staging inference cannot receive or probe the pinned F-03 catalog

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Architecture
- **Location**: `.railway/railway.ts:52-55`, `Dockerfile.inference:15`, `src/inference_service/main.py:42-60`
- **Detail**: Committed S-06 makes the catalog pair mandatory at inference startup (`settings.py:82-97`). Staging IaC still passes only the token and shared store; `Dockerfile.inference` copies `src/` only; `.dockerignore` excludes `artifacts/`; `deploy-plan.md:74-75` still says there is no Railway Volume. README rollout step 3 therefore cannot be followed on the existing topology. Missing env vars crash-loop the factory (`create_app` → `from_environment()`). If dummy env vars are set, `/health` still only checks the database and never opens the catalog, so Railway can mark the service ready and the first queued run fails `COMPLETENESS_CATALOG_UNAVAILABLE` after `queued → running`. Local subprocess coverage does not prove staging delivery. Public API still does not import `src.inference_service`.
- **Fix A ⭐ Recommended**: Keep the host-path loader for local/dev, and deliver the retained `manifest.json` plus sibling `selected-block-ids.txt` to staging through the existing private Bucket (or an equivalent sealed deploy copy), then set the two inference-only env vars to that reachable location. Update `.railway/railway.ts` and `context/deployment/deploy-plan.md` so the no-Volume contract stays honest.
  - Strength: Matches the current “no Volume, models already live in object storage” topology and keeps catalog bytes out of Git and the public API image.
  - Tradeoff: Needs a small loader/settings extension and a documented provision step for the catalog object prefix.
  - Confidence: HIGH — Bucket credentials are already on the inference service; the plan forbade Operator upload of the catalog, not deployer-provisioned object storage.
  - Blind spot: Exact object-key layout and whether checksum pinning should verify object bytes vs a mounted file have not been designed.
- **Fix B**: Attach a Railway Volume, copy the ignored F-03 artifact onto it at provision time, and add `INFERENCE_HDFS_COMPLETENESS_*` to inference env only.
  - Strength: Preserves the current Path-based loader with no inference-code change beyond IaC/docs.
  - Tradeoff: Contradicts the written no-Volume staging plan and still requires a manual copy that CI cannot see.
  - Confidence: MEDIUM — volumes work for a static file, but this repo already rejected them for models and logs.
  - Blind spot: Volume region/replica behavior if inference replicas increase later.
- **Decision**: FIXED via Fix A — object-store catalog key `hdfs/reference-catalog/manifest.json`; `/health` verifies the pin; Railway IaC and deploy-plan updated; host-path loader kept for local files.

### F2 — Uncommitted results-dialog polish is outside the S-06 plan

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Scope Discipline
- **Location**: `frontend/src/App.tsx`, `frontend/src/styles.css` (working tree vs `b9230da`)
- **Detail**: Committed Phase 4 matches the plan (heuristic labels, separate provisional panel, no scores, independent paging). The working tree additionally changes page size to 20, dual pagination, filename/datetime heading, a wider dialog, and a denser summary grid. Those edits are not in the plan and were kept out of the Phase 5 commit. `analyzer.db` is unrelated untracked runtime data sitting beside them.
- **Fix A ⭐ Recommended**: Leave the polish uncommitted for this change; land it as a separate follow-up after S-06 is archived.
  - Strength: Keeps the reviewed S-06 diff identical to the plan’s Phase 4 contract.
  - Tradeoff: Local UI remains dirty until a later commit.
  - Confidence: HIGH — operator already chose not to fold this into p5.
  - Blind spot: Easy to mix the files into an unrelated commit if they stay unstaged.
- **Fix B**: Document the polish as a plan addendum and commit it into this change.
  - Strength: One branch ships the operator-visible dialog they are already using.
  - Tradeoff: Mixes an unplanned UX pass into a contract/slice review.
  - Confidence: MEDIUM — the polish is compatible but it is not what Progress 4.x recorded.
  - Blind spot: Would need a fresh frontend lint/typecheck/build stamp on the expanded scope.
- **Decision**: PENDING

### F3 — Repo-root `analyzer.db` is untracked and not gitignored

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: `analyzer.db`, `.gitignore`
- **Detail**: Lesson “Keep generated runtime data out of Git” applies. `.gitignore` covers `.api/` and `artifacts/` but not a root `analyzer.db`. The file is untracked today; a later `git add .` would stage operator analysis data.
- **Fix**: Add `analyzer.db` (or a broader `*.db` / local SQLite pattern consistent with existing ignores) to `.gitignore` and keep the file untracked.
- **Decision**: PENDING

### F4 — Manual 5.5 full-corpus parity is operator-confirmed, not independently evidenced

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: `context/changes/separate-provisional-hdfs-results/plan.md:640`
- **Detail**: Automated Phase 5 checks were re-run for this review: `python -m pytest` → 223 passed, 2 skipped (Postgres unset); ruff, mypy, and frontend lint/typecheck/build passed during implementation. Progress 5.3–5.5 are `[x]` from operator confirmation of Phase 5. The 11,167,740-line notebook/parity release check is intentionally not CI and leaves no artifact in this diff. That is consistent with the plan’s sandbox note, not a failed automated gate.
- **Fix**: Skip if the Phase 5 confirmation stands; otherwise paste the `scripts/verify_hdfs_parity.py` outcome into `change.md` notes before archive.
- **Decision**: PENDING
