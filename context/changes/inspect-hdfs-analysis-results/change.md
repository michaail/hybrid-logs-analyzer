---
change_id: inspect-hdfs-analysis-results
title: Inspect HDFS analysis results
status: implementing
created: 2026-09-12
updated: 2026-09-12
archived_at: null
---

## Notes

Adapted during Phase 2: persist the full scored source sequence for each detected
anomaly instead of capping stored evidence at 20 lines, and expand already-stored
capped rows from the admitted dataset log at read time. The per-line 500-character
cap is unchanged. Existing completed runs show the full sequence after the API is
reloaded; they do not need to be re-analyzed.

