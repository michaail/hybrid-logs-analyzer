---
change_id: inspect-hdfs-analysis-results
title: Inspect HDFS analysis results
status: impl_reviewed
created: 2026-09-12
updated: 2026-09-13
archived_at: null
---

## Notes

Review remediation: source evidence remains capped at 20 scored lines per anomalous
block, with each raw line capped at 500 characters. The public result route returns
only the safely projected stored context and never reloads the admitted dataset to
expand evidence.

