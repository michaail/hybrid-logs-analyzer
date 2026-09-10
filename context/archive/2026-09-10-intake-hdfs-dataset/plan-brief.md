# Intake HDFS Dataset — Plan Brief

> Full plan: `context/changes/intake-hdfs-dataset/plan.md`

## What & Why

An Operator still cannot admit HDFS logs from the browser. Analysis today
requires a trusted-workspace path, so a remote Operator on Railway has no intake.
This slice adds whole-dataset accept/reject as its own action, then lets the
Operator select that stored dataset to start analysis.

## Starting Point

F-01 already has a project-owned `datasets` table (GET only). S-02 already
admits model ZIPs into the object store. Analyze still regex-validates a
workspace `log_reference` and upserts a workspace dataset as a side effect.
Drain3 is notebook/pipeline-only; the GAE package does not include a parser.

## Desired End State

An Operator uploads a UTF-8 HDFS log (≤ 32 MiB). Invalid files get a 422 and no
row. Valid files become object-kind datasets. The analyze dialog selects from
that list by `dataset_id`. Inference stays `not_supported`. S-04 will load a
static Drain3 snapshot rather than fitting or uploading a parser.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| --- | --- | --- |
| Parser | Static Drain3 at analysis (S-04); not in S-03 | Re-fit would retokenize `cluster_id`s and break FR-011 vs a published GAE |
| Enrichment | Skip at analysis; freeze the template set | The HDFS template set already covers the tested dataset |
| Admit surface | POST `/datasets` + analyze by `dataset_id` only | FR-005 is accept/reject, not “validate while starting a run” |
| Transport | Same-origin multipart, 32 MiB cap | Matches S-02; LogHub-scale files are out of browser scope |
| Workspace path | Drop public `log_reference` | Railway has no usable trusted workspace for Operators |
| Duplicates | New row every successful upload | Identity is the object pointer, not a content hash |
| Accept result | 201 `DatasetResponse` only; report on 422 | Rejection needs the report; acceptance is the listable row |
| Upload UI | Panel upload; dialog select | Intake and analyze stay two Operator actions |

## Scope

**In scope:** multipart HDFS admit, whole-file regex validation, object persist
with checksum, 422-without-row, analyze by `dataset_id`, datasets-panel upload,
analyze-dialog select, docs plus S-04 Drain3 handoff.

**Out of scope:** Drain3 upload/fit/load, enrichment, GB-scale upload, presigned
PUT, dataset delete, BGL, inference, auto-publish, lockfile regeneration.

## Architecture / Approach

Browser file → FastAPI (Operator) → UTF-8 + HDFS regex → put
`projects/<project-id>/datasets/<dataset-id>/<name>` → insert object-kind row.
Analyze loads that row, requires a published same-project model, copies the
object key into `log_reference`, and still finishes `not_supported`. FastAPI does
not import Drain3 or Torch.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Admission helper | Keys + validate-then-put, 32 MiB | Persisting before validate would leave orphans |
| 2. Operator HTTP | POST datasets; analyze `dataset_id` | Path-based tests and OpenAPI must invert cleanly |
| 3. UI and docs | Panel upload, dialog select, Drain3 note | 422 must include `issues[]` or the Banner stays generic |

**Prerequisites:** F-01, S-01, S-02 object store; inference stays later.
**Estimated effort:** ~2–3 sessions across 3 phases.

## Open Risks & Assumptions

- 32 MiB is enough for thesis samples; `HDFS_full.log` will not go through this
  path.
- HTTP no longer creates `analysis.rejected` runs for bad logs; S-05 “rejected
  outcomes” must not assume intake still writes those rows.
- Frozen Drain3 + `drain.ini` will exist as S-04 configuration; this slice only
  documents that contract.

## Success Criteria (Summary)

- Operator upload yields a listable object-kind dataset or a clear 422 with no
  row.
- Analyze starts only from a selected same-project dataset and still ends
  `not_supported`.
- Parser configuration is not an Operator upload; S-04 is instructed to load
  static Drain3 and skip enrichment.
