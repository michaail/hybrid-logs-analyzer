<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Intake HDFS Dataset

- **Plan**: context/changes/intake-hdfs-dataset/plan.md
- **Scope**: Phase 1–3 of 3
- **Date**: 2026-09-10
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

### F1 — Unused workspace `validate_hdfs_log` after analyze-by-dataset_id

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: src/api/validation.py:312
- **Detail**: HTTP analyze no longer calls `validate_hdfs_log`. The helper still reads a trusted-workspace path and `report.pop("issues", None)` at line 320, so reviving it as an HTTP 422 would omit `issues` and render as `Request failed (422)`. `_trusted_file` and `_resolved_inside_workspace` are only used by this function. The plan did not require deletion. Lessons say delete unused code after impl-review with operator confirmation.
- **Fix**: After operator confirmation, delete `validate_hdfs_log` plus `_trusted_file` and `_resolved_inside_workspace` if they have no remaining callers.
- **Decision**: FIXED

### F2 — Sanitized dataset filename is not length-capped

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/validation.py:380
- **Detail**: `_dataset_log_filename` strips to a basename and `[A-Za-z0-9._-]`, and `dataset_object_key` reuses `_require_relative_posix`, so traversal is blocked (tested). Filename length is not capped; an extremely long `Content-Disposition` name could exceed an S3 1024-byte key and fail after a successful validate. Model ZIP relatives are bounded by zip-member rules. Admit still validates before put.
- **Fix**: Cap the sanitized last path segment (for example 128 characters) before `dataset_object_key`.
- **Decision**: FIXED
