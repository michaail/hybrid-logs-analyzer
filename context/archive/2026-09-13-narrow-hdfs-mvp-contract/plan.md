# Narrow HDFS MVP Contract Implementation Plan

## Overview

Make the active product contract match the approved alignment: v2-only model
packages, a checksum-pinned FR-011 baseline, and attestation-only external
evidence. This change is documentation only. The running app still admits v1
until a later change.

## Current State Analysis

`context/foundation/mvp-alignment-plan.md` already settled the product
decisions. The first workstream (`prd-parity-contract`) is this change.

The PRD is still `status: draft` and internally inconsistent with the
implemented gate:

- Open Question 2 names a generic `.pt` ZIP, not `attribute-aware-gae-v2` plus
  a required preprocessing bundle.
- Open Question 3 still asks which notebook/config is the parity baseline,
  even though `context/archive/2026-09-11-run-parity-hdfs-analysis/baseline.md`
  already pins `hdfs_gae_20260829_104013_baseline`,
  `src/notebooks/6_GAE_Training_Colab.ipynb`, and `configs/hdfs_baseline.yaml`.
- FR-011 and the compatibility section still require “every evaluation metric
  reported by the agreed notebook baseline” within one percentage point.
  `src/modules/hdfs_parity.py` gates only exact `best_threshold` and
  `test_f1` / `test_pr_auc` / `test_roc_auc` within `0.01`. Ablation
  `metrics.json` also writes `test_precision`, `test_recall`, and `val_*`.
- US-01 / FR-002 still say “evidence of successful external evaluation.”
  Admission only requires a non-empty JSON object
  (`src/modules/model_package.py` `_validate_evidence_file`). FR-003 already
  says eligibility is not a quality judgement.
- Open Questions 1 and 4 are still open even though
  `context/foundation/roadmap.md` already recorded the answers (Python
  notebooks + local artifacts; one user / owner).

`context/foundation/hdfs-parity-baseline.md` does not exist.
`configs/hdfs_baseline.yaml` still points at
`context/changes/run-parity-hdfs-analysis/baseline.md`, which is gone.

Satellite contract docs still use the old FR-011 sentence: `AGENTS.md`,
`context/foundation/stack-assessment.md` (ready-to-paste pipeline rule),
`context/foundation/test-plan.md` §1 and §7 (“waits for S-04”), and the
closing paragraph of `context/deployment/deploy-plan.md`.

Roadmap M-1 is `READY_TO_CLOSE`: every F-NN / S-NN item is `done`, but
`milestone_status` is still `open`. S-04 unknowns and Open Roadmap Question 4
still say the baseline will be trained later.

README still documents v1 as an upload format. That copy is owned by the
follow-on `retire-v1` workstream, not this change.

### Key Discoveries:

- Alignment workstream `prd-parity-contract` is docs-only; v1 code, validator,
  and Compose are later workstreams
  (`context/foundation/mvp-alignment-plan.md`).
- Archive baseline is the approved evidence pack, including SHA-256 table and
  waived Colab commit/runtime versions
  (`context/archive/2026-09-11-run-parity-hdfs-analysis/baseline.md`).
- Lesson: do not commit generated binaries; pin ignored paths and SHA-256
  values (`context/foundation/lessons.md`).
- Prior PRD pattern: resolve numbered Open Questions in place (Q2 from
  publish-hdfs); put a durable pin in a sibling foundation file when the
  answer is an evidence pack.
- `/10x-roadmap` close procedure: `milestone_status: done`, charter Status
  `done`, append `## Milestone History`. Do not open M-2 in this change.

## Desired End State

A reader of active foundation docs can state, without opening the archive:

- The only accepted Publisher package is `attribute-aware-gae-v2` bound to an
  immutable HDFS preprocessing bundle. v1 is not a supported contract.
  `feature_contract: notebook_raw_v1` is feature semantics, not a package
  format.
- External-evaluation evidence is a required non-empty JSON attestation. The
  service does not verify that an external evaluation succeeded.
- FR-011 is the controlled labelled release gate: exact `best_threshold` and
  absolute `0.01` tolerance on test F1, PR-AUC, and ROC-AUC. Operator uploads
  are not FR-011 proof.
- `context/foundation/hdfs-parity-baseline.md` is the active pin (checksums,
  identities, metric table, verify command). The archive file remains the
  immutable evidence source.
- PRD Open Questions 1–4 are resolved; PRD `status` is `approved`; version
  bumps because the contract changed.
- M-1 is closed. Follow-on alignment stays in
  `context/foundation/mvp-alignment-plan.md`. No new milestone is opened.

The running app may still admit v1 until `retire-v1`. The documents name that
follow-on instead of claiming the upload gate already rejects v1.

## What We're NOT Doing

- Changing package validation, admission, fixtures, E2E, or UI.
- Deleting persisted v1 rows or adding a cleanup script.
- Adding the private model-validator HTTP service or Compose stack.
- Rewriting README v1 upload copy (follow-on `retire-v1`).
- Rewriting `shape-notes.md`, `mvp-draft.md`, or PRD Current System Overview.
- Re-running `scripts/verify_hdfs_parity.py` or committing `releases/` /
  `data/` / `artifacts/` binaries.
- Opening a new `/10x-roadmap` milestone after M-1 close.
- Broad Railway/Compose truthfulness edits beyond the FR-011 phrase in
  `deploy-plan.md`.

## Implementation Approach

Distill the archived baseline into an active foundation pin, then rewrite the
PRD so it is the source of truth. Sync the satellite contract docs that
currently repeat the old FR-011 / baseline sentences. Close M-1 because every
roadmap slice is already `done`; keep later alignment on the existing
alignment plan rather than inventing M-2 here.

## Critical Implementation Details

Do not copy Colab path noise or change-local frontmatter into the foundation
baseline. The new file must include the SHA-256 table for the v3 package,
bundle, corpus, labels, and test-block IDs, plus the four gated metric values,
and must point back at the archive file as immutable evidence.

Name `retire-v1` wherever the PRD states v2-only so an implementer does not
treat the current 409-on-analysis-without-bundle behavior as the finished
contract.

Closing M-1 must not start the `/10x-roadmap` “open next milestone” loop.
Record closure only.

## Phase 1: Product contract

### Overview

Create the active parity pin and rewrite the PRD so the accepted package,
FR-011 metric set, evidence rule, and resolved open questions are explicit.

### Changes Required:

#### 1. Distilled HDFS parity baseline

**File**: `context/foundation/hdfs-parity-baseline.md`

**Intent**: Promote an active, checksum-pinned baseline that a later
implementer can trust without mining the archive. Keep generated artefacts
out of Git.

**Contract**: New foundation file with: provenance (notebook
`src/notebooks/6_GAE_Training_Colab.ipynb`, config
`configs/hdfs_baseline.yaml`, run `hdfs_gae_20260829_104013_baseline`);
resolved training/graph config including `feature_contract: notebook_raw_v1`;
SHA-256 table copied from the archive (v3 ZIPs, corpus, labels, test block
IDs, expected.json path); FR-011 gate (exact threshold
`0.1922733336687088`; test F1 / PR-AUC / ROC-AUC values and `0.01`
tolerance); explicit exclusion of `test_precision`, `test_recall`, and
`val_*`; waived Colab commit/runtime; pointer to
`context/archive/2026-09-11-run-parity-hdfs-analysis/baseline.md`;
`scripts/verify_hdfs_parity.py` command with ignored workspace paths. Do not
embed binary contents.

#### 2. PRD contract rewrite

**File**: `context/foundation/prd.md`

**Intent**: Make the PRD match the implemented and approved product contract,
and say that v1 runtime retirement is a follow-on change.

**Contract**: Touch Success Criteria Guardrails, US-01 Given, US-01/FR-002
evidence wording, FR-002/FR-003 package format, FR-011 plus Socrates note,
Constraints & Compatibility, Data migration (no v1 compatibility; leftover
v1 rows are deleted in follow-on `retire-v1`), Business Logic Changes, Open
Questions 1–4, and frontmatter (`status: approved`, bump `version`,
`updated: 2026-09-13`). State that the only accepted format is
`attribute-aware-gae-v2` plus its immutable preprocessing bundle; v1 is
unsupported; `notebook_raw_v1` is a feature contract. Evidence is a
non-empty JSON attestation, not proof of successful evaluation. FR-011 is
the controlled labelled release gate with the four named values. Resolve Q1
and Q4 from the existing roadmap answers; resolve Q2 to v2+bundle; resolve
Q3 by pointing at `hdfs-parity-baseline.md`. Do not rewrite Current System
Overview. Do not claim the running API already returns 422 for v1.

### Success Criteria:

#### Automated Verification:

- `test -f context/foundation/hdfs-parity-baseline.md` succeeds
- `rg -n "Open Question 3" -n context/foundation/prd.md` shows Q3 resolved
  and pointing at `hdfs-parity-baseline.md`
- `rg -n "every evaluation metric reported by the agreed notebook baseline" context/foundation/prd.md` has no matches
- `rg -n "evidence of successful external evaluation" context/foundation/prd.md` has no matches
- `rg -n "attribute-aware-gae-v2" context/foundation/prd.md` matches
- `rg -n "retire-v1" context/foundation/prd.md` matches (follow-on named)

#### Manual Verification:

- Owner confirms the distilled checksum table and metric values match the
  archive baseline, and that Q1–Q4 read as resolved without reopening Current
  System Overview

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase. Phase
blocks use plain bullets — the corresponding `- [ ]` checkboxes for these
items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Satellite alignment and milestone close

### Overview

Repeat the same contract in the satellite sources of truth, retarget the
stale config pointer, close M-1, and mark the alignment workstream done.

### Changes Required:

#### 1. Agent and stack contract paste

**File**: `AGENTS.md`

**Intent**: Stop instructing agents to enforce “every reported metric within
one percentage point.”

**Contract**: Rewrite the Critical Boundaries notebook-baseline sentence to
the four-value FR-011 gate and point at
`context/foundation/hdfs-parity-baseline.md`.

#### 2. Stack-assessment ready-to-paste rule

**File**: `context/foundation/stack-assessment.md`

**Intent**: Keep the compensation paste in sync with the PRD so later agent
onboarding does not restore the old rule.

**Contract**: In the “Pipeline structure and compatibility” paste block,
replace “every agreed evaluation metric must remain within one percentage
point” with the same four-value gate and baseline pointer.

#### 3. Test-plan freshness

**File**: `context/foundation/test-plan.md`

**Intent**: Stop saying notebook parity is waiting on S-04 and a trained
baseline.

**Contract**: Update §1 strategy closing sentence and §7 “Notebook-parity
within one percentage point” exclusion: the agreed gate exists; it is a
manual/labelled release command, not default Ubuntu CI, and not an Operator
upload. Bump the freshness ledger date.

#### 4. Deploy-plan FR-011 phrase

**File**: `context/deployment/deploy-plan.md`

**Intent**: Align the leftover “one percentage point” sentence without
rewriting Railway vs Compose policy.

**Contract**: Change only the closing “HDFS notebook-parity checks within
one percentage point…” sentence to the four-value labelled release gate.
Leave the rest of the Railway staging procedure for `compose-acceptance`.

#### 5. Baseline config pointer

**File**: `configs/hdfs_baseline.yaml`

**Intent**: Point at a file that still exists.

**Contract**: Header comment must cite
`context/foundation/hdfs-parity-baseline.md`, not
`context/changes/run-parity-hdfs-analysis/baseline.md`.

#### 6. Close M-1 and refresh stale roadmap questions

**File**: `context/foundation/roadmap.md`

**Intent**: Record that the first publish-and-analyze milestone is complete.
Do not open a successor milestone in this change.

**Contract**: Set frontmatter `milestone_status: done`, bump `updated` and
`prd_version` to match the rewritten PRD. Flip the `## Milestone` Status
line to `done`. Append a `## Milestone History` closure entry for M-1.
Clear S-04 **Unknowns** (baseline is no longer a blocker). Rewrite Open
Roadmap Questions 3 and 4 to the v2+bundle contract and the foundation
baseline pin. Leave F-NN / S-NN item statuses `done`. Do not add new
slices. Do not start `/10x-roadmap` next-milestone intake.

#### 7. Alignment workstream stamp

**File**: `context/foundation/mvp-alignment-plan.md`

**Intent**: Show that the product-contract workstream is the one this change
closes.

**Contract**: Mark workstream `prd-parity-contract` `done`. Leave
`retire-v1`, `isolated-validator`, `compose-acceptance`, and
`verify-evidence` pending.

### Success Criteria:

#### Automated Verification:

- `rg -n "one percentage point" AGENTS.md context/foundation/stack-assessment.md context/foundation/test-plan.md context/deployment/deploy-plan.md` has no matches in the FR-011 sentences this phase rewrites
- `rg -n "hdfs-parity-baseline.md" configs/hdfs_baseline.yaml` matches
- `rg -n "context/changes/run-parity-hdfs-analysis/baseline.md" configs/hdfs_baseline.yaml` has no matches
- `rg -n "milestone_status: done" context/foundation/roadmap.md` matches
- `rg -n "prd-parity-contract" -A2 context/foundation/mvp-alignment-plan.md` shows status `done`

#### Manual Verification:

- Owner confirms M-1 history records closure without a new open milestone,
  and that README still documenting v1 upload is acceptable until `retire-v1`

---

## Testing Strategy

### Unit Tests:

- None. No production code changes.

### Integration Tests:

- None.

### Manual Testing Steps:

1. Read `context/foundation/hdfs-parity-baseline.md` against the archive
   checksum and metric tables.
2. Skim PRD Open Questions: all four resolved; v2-only and follow-on
   `retire-v1` are both visible.
3. Confirm roadmap M-1 is closed and `mvp-alignment-plan.md` still lists the
   remaining four workstreams as pending.

## Performance Considerations

None. Documentation only.

## Migration Notes

No database or object-store migration in this change. Documents now say v1
is unsupported; leftover v1 rows remain until `retire-v1`. Do not delete
them here.

## References

- Alignment source: `context/foundation/mvp-alignment-plan.md`
- Immutable evidence: `context/archive/2026-09-11-run-parity-hdfs-analysis/baseline.md`
- Gate implementation: `src/modules/hdfs_parity.py` (`METRIC_NAMES`,
  `METRIC_TOLERANCE`)
- Milestone close rules: `.cursor/skills/10x-roadmap/references/milestone-state.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Product contract

#### Automated

- [x] 1.1 `test -f context/foundation/hdfs-parity-baseline.md` succeeds — fa30eab
- [x] 1.2 `rg -n "Open Question 3"` shows Q3 resolved and pointing at `hdfs-parity-baseline.md` — fa30eab
- [x] 1.3 `rg -n "every evaluation metric reported by the agreed notebook baseline" context/foundation/prd.md` has no matches — fa30eab
- [x] 1.4 `rg -n "evidence of successful external evaluation" context/foundation/prd.md` has no matches — fa30eab
- [x] 1.5 `rg -n "attribute-aware-gae-v2" context/foundation/prd.md` matches — fa30eab
- [x] 1.6 `rg -n "retire-v1" context/foundation/prd.md` matches (follow-on named) — fa30eab

#### Manual

- [x] 1.7 Owner confirms the distilled checksum table and metric values match the archive baseline, and that Q1–Q4 read as resolved without reopening Current System Overview — fa30eab

### Phase 2: Satellite alignment and milestone close

#### Automated

- [x] 2.1 `rg -n "one percentage point"` has no matches in the FR-011 sentences this phase rewrites — edb206e
- [x] 2.2 `rg -n "hdfs-parity-baseline.md" configs/hdfs_baseline.yaml` matches — edb206e
- [x] 2.3 `rg -n "context/changes/run-parity-hdfs-analysis/baseline.md" configs/hdfs_baseline.yaml` has no matches — edb206e
- [x] 2.4 `rg -n "milestone_status: done" context/foundation/roadmap.md` matches — edb206e
- [x] 2.5 `rg -n "prd-parity-contract"` in `mvp-alignment-plan.md` shows status `done` — edb206e

#### Manual

- [x] 2.6 Owner confirms M-1 history records closure without a new open milestone, and that README still documenting v1 upload is acceptable until `retire-v1` — edb206e
