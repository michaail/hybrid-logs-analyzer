---
change_id: test-plan-refresh-2026-09-13
title: Refresh the test plan after S-03 analysis and result slices
status: archived
created: 2026-09-13
updated: 2026-09-13
archived_at: 2026-09-13T21:43:15Z
---

## Notes

Open a change folder to refresh context/foundation/test-plan.md using the accepted refresh brief.

Fresh evidence:
- PRD: HDFS-only MVP; project isolation, terminal run states, and provisional-result semantics remain binding.
- Roadmap: S-04 analysis, S-05 results, and S-06 provisional results are complete.
- User concern: analysis-runner and configuration changes; additions after S-03 are under-tested.
- Hot spots: src/api (87 touches/30d), src/modules (61), frontend/src (36), src/inference_service (18).
- Existing test base: 15 Python test files plus Playwright E2E; no frontend component-test runner.

Refresh priorities:
1. Analysis-runner and immutable-configuration regressions.
2. Terminal-failure atomicity and truthful run status.
3. Cross-project denial for datasets, runs, and results.
4. Provisional versus heuristically-final HDFS outcome semantics.
5. Result paging, summaries, and UI error/success signals.

Do not add new ML-job, parity, checksum, or general model-compliance coverage. Preserve the non-negotiable untrusted-artifact boundary: uploaded `.pt` files must not be deserialized in the control plane.

Remain within the HDFS-only MVP. Do not add code anchors to the test plan; research must ground them. After creating the folder, follow the downstream continuation rule.
