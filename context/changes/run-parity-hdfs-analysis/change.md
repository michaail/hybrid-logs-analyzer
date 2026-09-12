---
change_id: run-parity-hdfs-analysis
title: Run parity hdfs analysis
status: impl_reviewed
created: 2026-09-11
updated: 2026-09-12
archived_at: null
---

## Notes

PRD US-03 / FR-012 / FR-013 and roadmap F-03 / S-06 (provisional vs finalized HDFS
block histories) are an intentional product-contract update recorded on 2026-09-12.
They are **not** implemented by this change; S-04 still scores every matched block as
anomaly or normal. Follow-up work belongs to `complete-hdfs-block-evaluation-data` and
`separate-provisional-hdfs-results`.

Accepted MVP risk: production inference deserializes checksum-bound Drain3
`drain_parser.bin` (jsonpickle) in the private service after Publisher-only admission.
Operators cannot admit a bundle. A format change is out of scope while notebook parity
depends on FilePersistence snapshots.
