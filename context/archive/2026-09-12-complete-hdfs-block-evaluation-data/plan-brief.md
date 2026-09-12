# Complete HDFS block evaluation data — Plan Brief

> Full plan: `context/changes/complete-hdfs-block-evaluation-data/plan.md`

## What & Why

Create durable, reproducible HDFS evaluation datasets from complete source histories
for an explicitly selected, ordered set of block IDs. The current parity gate already
does this only in temporary files; this change makes it a reusable, inspectable
foundation so line-prefix samples cannot be mistaken for anomaly-quality evidence.

## Starting Point

`src/modules/hdfs_parity.py` scans the full checksum-pinned source corpus, then writes
temporary shards with every selected block's first-match source lines. It has no public
artifact contract, while its label parsing silently permits duplicate or unrecognised
values. Frozen inference already caps a shard at 100,000 lines and 25,000 blocks.

## Desired End State

An explicit CLI produces an atomically published workspace artifact containing an
ordered selected-ID copy, bounded source-order HDFS shards, and a detailed manifest.
The manifest proves which corpus, labels, IDs, limits, and produced shard bytes were
used; it records timestamp issues as warnings without reordering or discarding source
history. The parity release gate uses the same construction code.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Completeness scope | Complete within the approved immutable corpus | Full-corpus projection is evidence the repository can prove; lifecycle completion belongs to S-06. |
| Block identity | First `blk_*` match owns a line | Retains established model and baseline semantics. |
| Labels | Exactly one binary label per selected ID | Prevents corrupt labels from silently changing quality metrics. |
| Event order | Raw source-file order is canonical | Preserves capture evidence; timestamp faults are visible manifest warnings. |
| Artifact form | Manifest, selected-ID copy, and bounded log shards | Directly supports inspection and existing frozen scoring limits. |
| Entry point | Dedicated explicit-path CLI | Avoids notebook state and never selects a source/split implicitly. |
| Verification | Focused tests plus opt-in corpus release gate | Provides fast regression feedback without making local data/ML a default test dependency. |

## Scope

**In scope:**

- Typed complete-history materialization and strict evaluation-input validation.
- Checksum-bound atomic workspace artifacts built from an approved corpus, labels, and
  ordered ID file.
- Shared parity-gate integration, targeted tests, and controlled-run documentation.

**Out of scope:**

- Operator-upload lifecycle completion, provisional classifications, result counts, or UI.
- New log sources, a browser full-corpus upload, model/scoring changes, or split regeneration.

## Architecture / Approach

A shared `src/modules/hdfs_evaluation_data.py` streams the source corpus twice: first
to validate/count selected histories and collect timestamp warnings, then to write
whole-block shards. The CLI invokes it through an `ArtifactStore` stage whose
configuration includes full input SHA-256 values; `hdfs_parity` delegates its
temporary sharding to the same shared logic while retaining frozen-parser and metric
checks.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Materialization contract | Typed validation, manifest, and complete bounded shards | Accidentally retaining permissive labels or splitting a block |
| 2. Workflow consolidation | Explicit CLI and parity integration | Diverging from the approved parity gate |
| 3. Evidence and guidance | Regression coverage and recorded full-corpus proof | Overstating evaluation completeness as live lifecycle completion |

**Prerequisites:** Approved immutable corpus, labels, and selected ID list available
under the local workspace; normal local terminal for full-corpus ML/release verification.
**Estimated effort:** ~2–3 sessions across 3 phases, plus one controlled full-corpus run.

## Open Risks & Assumptions

- The generated data is complete only relative to the checksum-pinned corpus, not the
  real-world lifecycle of an ordinary uploaded log.
- Timestamp warnings preserve raw source evidence but cannot guarantee an
  independently chronological capture.
- The full LogHub corpus is ignored workspace data, so its release check cannot run in
  default CI.

## Success Criteria (Summary)

- Selected blocks contain all and only their first-match source lines, in raw source
  order, without crossing shard boundaries.
- The manifest and `_SUCCESS.json` atomically expose reproducible checksum evidence.
- The approved HDFS release keeps its existing threshold and metric parity after the
  shared builder replaces private temporary-shard logic.
