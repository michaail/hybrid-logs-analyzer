<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Inspect HDFS analysis results

- **Plan**: context/changes/inspect-hdfs-analysis-results/plan.md
- **Scope**: Phases 1–3 of 3
- **Date**: 2026-09-13
- **Verdict**: APPROVED
- **Findings**: 0 critical, 3 warnings, 1 observation

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

### F1 — Result cursors are not bound to their analysis run

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/storage.py:1331, src/api/storage.py:1355
- **Detail**: Cursor payloads bind sort and filters but omit `analysis_run_id`. A valid cursor from
  one run can therefore be accepted for another run in the same project. SQL remains run-scoped,
  so this does not disclose data, but it can skip or empty pages and violates deterministic paging.
- **Fix**: Include `analysis_run_id` in cursor encoding, validate it during decode, and add a
  same-project cross-run cursor rejection test.
- **Decision**: FIXED

### F2 — Evidence expansion removes the response-size bound

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence
- **Location**: src/modules/hdfs_inference.py:405, src/api/main.py:923-940, src/api/hdfs_evidence.py:16-52
- **Detail**: The Phase 2 adaptation removes the 20-line stored-evidence cap, rereads and parses
  the full dataset for each result page, and may return every matching source line. This changes
  result production despite the plan's explicit non-goal, invalidates its page-size bound, and
  adds repeated object-store/CPU cost.
- **Fix A ⭐ Recommended**: Restore a bounded per-block evidence/response budget and return
  explicit truncation metadata; serve stored bounded context without full-dataset rereads.
  - Strength: Restores the approved contract and predictable resource use.
  - Tradeoff: Existing capped records remain capped unless a later migration/backfill is designed.
  - Confidence: HIGH — directly matches the plan's stated boundary.
  - Blind spot: Product requirements may genuinely require all block lines, which would need
    re-planning rather than an implementation adaptation.
- **Fix B**: Amend the plan and API contract for full evidence, then add a separately designed
  bounded retrieval mechanism.
  - Strength: Preserves the expanded evidence objective.
  - Tradeoff: Requires material re-planning and still cannot leave current unbounded reads.
  - Confidence: MEDIUM — product intent for full evidence is not established.
  - Blind spot: No performance measurements for large admitted datasets.
- **Decision**: FIXED via Fix A

### F3 — The score-order index does not match the requested ordering

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/migrations.py:228-235
- **Detail**: `idx_anomaly_results_run_score_desc` uses ascending `anomaly_score` and does not
  include the null-placement expression used by `score_desc`. It does not support the documented
  mixed-direction keyset ordering without an extra sort.
- **Fix**: Add a new forward-only migration with a sort-aligned expression index for SQLite and
  PostgreSQL, then update the migration tests to assert it.
- **Decision**: FIXED

### F4 — Completion status has not been advanced

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Scope Discipline
- **Location**: context/changes/inspect-hdfs-analysis-results/change.md:4, context/foundation/roadmap.md:67,216
- **Detail**: Every Progress item is checked, but the change and roadmap remain
  `implementing` / `in-progress`. This is expected until the phase closing and epilogue commits
  complete.
- **Fix**: Finish the implementation close-out ritual after review triage.
- **Decision**: FIXED
