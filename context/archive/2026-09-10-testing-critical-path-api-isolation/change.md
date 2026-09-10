---
change_id: testing-critical-path-api-isolation
title: Critical-path API isolation tests
status: archived
created: 2026-09-10
updated: 2026-09-10
archived_at: 2026-09-10T18:51:57Z
---

## Notes

Open a change folder for rollout Phase 1 of context/foundation/test-plan.md: "Critical-path API isolation".
Risks covered: #1, #2, #3. Test types planned: unit + integration.
Risk response intent:
- #1: prove a user cannot observe or act on another project's models/logs/runs (404, not the other project's data).
- #2: prove Operator register/publish is 403 and creates no version row.
- #3: prove ineligible ZIP yields a structured reject with no row, and a registered-but-unpublished version cannot start analysis.
After creating the folder, follow the downstream continuation rule.
