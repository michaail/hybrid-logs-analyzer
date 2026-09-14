---
change_id: add-remove-operations
title: Add remove operations for models and datasets
status: archived
created: 2026-09-14
updated: 2026-09-14
archived_at: 2026-09-14T13:28:44Z
---

## Notes

Expose user-facing remove so a Publisher can delete an unused HDFS model version
(eligible or published) and an Operator can delete an unused uploaded dataset.
This completes CRUD for those two persisted item types without cascading analysis
history. Referenced analysis runs stay fail-closed; runs themselves are not deleted.
