# Narrow HDFS MVP Contract — Plan Brief

> Full plan: `context/changes/narrow-hdfs-mvp-contract/plan.md`

## What & Why

Active product docs still describe a generic `.pt` upload, an unnamed “every
metric / one percentage point” FR-011 rule, and an unresolved parity baseline.
The implemented gate and the approved Colab v3 release already exist. This
change rewrites the contract so later v1-retirement and Compose work have a
single source of truth.

## Starting Point

Archive evidence at
`context/archive/2026-09-11-run-parity-hdfs-analysis/baseline.md` pins the v3
release. `src/modules/hdfs_parity.py` already gates exact `best_threshold` and
test F1 / PR-AUC / ROC-AUC within `0.01`. The PRD, AGENTS.md, test-plan, and
roadmap still contradict that.

## Desired End State

A reader of foundation docs can name the v2+bundle package, the four FR-011
values, and the checksum-pinned baseline without opening the archive. M-1 is
closed. The running app may still admit v1 until `retire-v1`, and the documents
say so.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Package contract | `attribute-aware-gae-v2` + bundle only | No usable v1 models; no compatibility path | Alignment |
| FR-011 metric set | Exact threshold; F1 / PR-AUC / ROC-AUC ±0.01 | Matches the implemented gate; excludes precision/recall/`val_*` | Alignment |
| Evidence | Non-empty JSON attestation | Admission cannot prove “successful” evaluation | Alignment |
| Baseline file | Distill into `hdfs-parity-baseline.md` | Foundation needs an active pin; archive stays immutable | Plan |
| Implementation lag | State the target; name `retire-v1` | Avoid claiming the API already 422s v1 | Plan |
| Satellite docs | Also AGENTS, stack-assessment paste, deploy-plan FR-011 phrase | Those files currently restore the old rule | Plan |
| Leftover PRD Q1/Q4 | Resolve from existing roadmap answers | Already decided; do not rewrite Current System Overview | Plan |
| M-1 | Close; do not open M-2 | Every F/S item is `done`; follow-on lives in the alignment plan | Plan |

## Scope

**In scope:** PRD contract rewrite; distilled `hdfs-parity-baseline.md`;
AGENTS.md, stack-assessment paste, test-plan §1/§7, deploy-plan FR-011 phrase,
`configs/hdfs_baseline.yaml` pointer, M-1 close, alignment workstream stamp.

**Out of scope:** v1 code/fixtures/UI/README upload copy; validator service;
Compose; re-running full-corpus parity; committing binaries; opening a new
roadmap milestone; rewriting shape-notes / mvp-draft / Current System Overview.

## Architecture / Approach

Documentation-only. The PRD remains the product source of truth. The new
baseline file is the active evidence pin and points at the archive. Satellite
docs are updated only where they currently repeat the old FR-011 or baseline
sentences.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Product contract | Distilled baseline + rewritten PRD | Distill misses a checksum or over-claims that v1 is already rejected |
| 2. Satellite alignment | Synced agent/test/deploy/config docs; M-1 closed | Accidental M-2 open or README v1 rewrite slipping in |

**Prerequisites:** Alignment plan approved; archive baseline present.
**Estimated effort:** One session across two short docs phases.

## Open Risks & Assumptions

- Workspace `releases/` binaries stay gitignored; the foundation pin is
  checksums plus paths, not files.
- Closing M-1 will not be mistaken for “MVP fully proven”; remaining
  workstreams stay visible on `mvp-alignment-plan.md`.

## Success Criteria (Summary)

- PRD Q1–Q4 resolved; v2-only and four-value FR-011 are explicit.
- `hdfs-parity-baseline.md` exists and matches archive checksums/metrics.
- M-1 is `done` with no successor milestone opened in this change.
