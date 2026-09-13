# Test-plan refresh after S-04–S-06 Implementation Plan

## Overview

Reconcile `context/foundation/test-plan.md` with the shipped HDFS
analysis/result product. The guide’s ledger, stack, negative space, and
cookbook still describe a pre-S-04 world, so they cannot tell what S-04–S-06
already protect from the remaining admission-safety and frontend-role-signal
gaps. This change edits that one guide. It does not add tests, CI jobs, or a
new isolation program.

## Current State Analysis

Frame brief
(`context/changes/test-plan-refresh-2026-09-13/frame.md`) is
authoritative. There is no `research.md`.

The test-plan skill freezes §1–§5 until `--refresh`. Completing S-04–S-06
updated `roadmap.md` and `context/archive/`; it did not rewrite the guide.
Phase 1 isolation is archived with all Progress `[x]`, but §3 still says
`change opened`. Risks #1–#6 never named analysis-runner, terminal-status,
or provisional-versus-final failures. Many of those oracles already exist
in pytest and are unnamed in §6.

**Hypothesis Investigation (from frame):**

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| Strategy freeze: no FR-006 / FR-007 / FR-012 rows | `test-plan.md:33-55`; `prd.md:124-136`; `roadmap.md:68-70` | STRONG |
| Stale bookkeeping: §3/§4/§7 still pre-S-03 | Phase 1 `change opened` (`test-plan.md:74`) vs archived isolation change; §4 `~8` files / CI skips `@ml` (`:103`) vs 15 `test_*.py` and `verify.yml:30-44`; §7 S-03 unimplemented / parity waits for S-04 (`:253-255`) | STRONG |
| Cookbook lag: tests exist, §6 unnamed | Result/provisional/dispatch tests in `tests/test_api.py`, `tests/test_inference_service.py`, `tests/test_shared_state_repository.py`; §6.3/§6.5 TBD | STRONG |
| Unfinished Phases 2–4 occupy §3 | `test-plan.md:75-77` `not started`; no live `testing-*` folders | STRONG |

**Narrowing signals (from frame):** the mismatch is ledger/cookbook, not a
blank suite; dataset/run/result isolation is already claimed; analysis-runner,
terminal status, and provisional/result semantics are the leading *unlisted*
risks.

**Convention:** archive close-out checks Progress, sets `status: archived`,
and marks the roadmap `done`. §3 status vocabulary ends at `complete`.
Cookbook names shipped patterns; it does not duplicate test bodies. §2
numbers are append-only.

## Desired End State

A later agent reading `context/foundation/test-plan.md` can:

- See risks #1–#6 unchanged in number, plus appended risk #7 for analysis
  execution and result semantics (FR-006 / FR-007 / FR-012), with a response
  row.
- Treat Phase 1 as `complete` (`testing-critical-path-api-isolation`) and
  Phase 4 as `complete` (existing Verify jobs, including the split Torch-free
  API job and Ubuntu `@ml` inference job).
- Treat Phase 2 as `not started` with a *narrowed* leftover-admission goal,
  and Phase 3 as `not started` component tests for unauthorized
  Register/Publish/Select copy.
- Follow §6 recipes that name existing dispatch, queued/failed, paging, and
  provisional oracles — and still follow the Phase 1 401/403/404 matrix
  without re-testing it.
- Trust §4/§5/§7: S-03 and S-04 have shipped; parity/checksum/ML-job
  *expansion* stays excluded; Verify is not “Torch-free everywhere.”

Verify by reading the eight sections in order and by running the existing
Torch-free API pytest command (no new tests).

### Key Discoveries:

- `--refresh` may rewrite §1–§5 only through this change folder; §2 rewrite
  is allowed because the user explicitly directed appending one combined
  risk (schema: never renumber; append at the bottom).
- Isolation of models, runs, results, and datasets is already in §6.2 and
  `tests/test_api.py` (`test_cross_project_member_routes_return_404`,
  `test_dataset_reads_are_isolated_and_omit_rejected_inputs`). Do not plan
  it as new coverage.
- Dispatch/terminal/paging/provisional oracles already exist: e.g.
  `test_published_v2_model_queues_and_schedules_dispatch`,
  `test_exhausted_dispatch_preserves_queued_run`,
  `test_result_pages_expose_empty_queued_and_failed_run_states`,
  `test_result_pages_are_typed_project_scoped_and_keep_run_wide_summaries`,
  `test_provisional_pages_are_typed_project_scoped_and_exclude_scores`,
  `test_mixed_run_persists_exclusive_heuristic_and_provisional_outcomes`.
- Admission *boundary* tests exist (`test_registration_rejects_ineligible_zip_without_inserting`,
  `test_model_package_and_api_sources_do_not_import_torch`,
  `test_scrub_environment_removes_application_secrets`). Phase 2 stays
  pending for residual leftover-prefix cleanup (risk #5), not as an empty
  green field.
- Playwright publication specs do not prove unauthorized-role UI. Phase 3
  remains a component-test bootstrap. `frontend/package.json` has no
  component runner.
- `.github/workflows/verify.yml` already has `python` (`-m "not ml"`),
  `inference` (`-m ml`), `frontend` build, and `e2e`. Phase 4 is
  documentation of that split, not new YAML.
- Commit `381b057` bumped “Last updated” without fixing §7 S-03/S-04 claims
  — date stamps are not evidence of strategy review.

## What We're NOT Doing

- Adding or rewriting product tests, fixtures, or Playwright specs.
- Editing `.github/workflows/verify.yml`, `pyproject.toml`, or
  `frontend/package.json`.
- Bootstrapping a frontend component runner (that is future Phase 3).
- A new cross-project isolation workstream (Phase 1 / §6.2 already claims it).
- New ML-job, notebook-parity, checksum, catalog-integrity, or
  model-compliance suites.
- Renumbering risks #1–#6 or inventing new §3 status literals.
- Inventing a §3 change folder for S-04–S-06 product slices.
- File:line failure anchors in §2 Source (principle #3).
- In-place guide edits outside this change.
- `AGENTS.md` / Cursor-rule changes.
- Regenerating `requirements-macos-intel.lock.txt`.
- Broadening MVP beyond HDFS.

## Implementation Approach

Sequential prose edits to one file, `context/foundation/test-plan.md`, in
two content phases then a schema/truthfulness check. Ground every factual
claim in the frame, roadmap Done rows, archived Phase 1 plan, and the
named existing tests. Cost × signal: name oracles that already fail for the
right reason; do not add tautological tests whose expected values are
copied from current code.

## Critical Implementation Details

§3 **Status** cells must use only `not started`, `change opened`,
`researched`, `planned`, `implementing`, or `complete`. Phase 1’s Change
folder stays `testing-critical-path-api-isolation` (archived on disk; the
id is the ledger key). Do not add a fake testing-* folder for risk #7;
coverage lives in §6. Append risk #7 after #6; do not reorder. Fill §6
cookbook in the second content phase so §3/`§6` do not disagree mid-edit.
Bump header **Last updated** and §8 dates only after the §7 S-03/S-04
wording is actually corrected.

## Phase 1: Reconcile strategy, ledger, stack, and gates

### Overview

Rewrite the frozen strategy sections so they describe the post-S-04
product without turning this refresh into five new test programs. Append
one combined analysis/result risk. Close Phase 1 and Phase 4 on evidence.
Narrow Phase 2; keep Phase 3 pending for unauthorized-role UI.

### Changes Required:

#### 1. Strategy and risk map

**File**: `context/foundation/test-plan.md`

**Intent**: Keep principles #1–#3 verbatim. Update the short §1 closing
paragraph: isolation and model-lifecycle gates remain first; frontend
role-signal tests remain after those gates; do not spend *new* rollout
budget on notebooks, BGL, or additional `@ml` jobs on the Torch-free API
CI job; notebook-parity expansion stays excluded even though S-04 shipped.
Add `src/inference_service` to the hot-spot scope list (refresh scan;
likelihood evidence, not an anchor). Append risk #7 and one Risk Response
Guidance row.

**Contract**: Risks #1–#6 rows stay the same numbers and failure scenarios.
New row #7 (failure scenario, not a test name): an Operator can treat an
analysis as successful or heuristically final when the run is still queued
or has failed, when admitted inputs were not the ones used, or when
provisional block histories are scored or counted as anomalies. Impact
High, Likelihood Medium/High. Source evidence only: refresh interview Q3/Q4;
PRD FR-006 / FR-007 / FR-012; roadmap S-04–S-06; hot-spot dirs `src/api`
and `src/inference_service` with the refresh 30-day touch counts. No
file:line, function names, or schema names in Source.

Response guidance for #7:

- **Prove**: queued/failed runs are readable without fake anomaly pages;
  exhausted dispatch stays queued; provisional pages omit score/threshold
  and do not change heuristically-final counts.
- **Challenge**: HTTP 200 on a result page means the run succeeded; catalog
  membership means every block is scored.
- **Context to ground later**: run status vs result vs provisional
  collections; immutable admitted inputs vs live settings; heuristic
  catalog vs lifecycle proof.
- **Cheapest layer**: existing HTTP/integration tests (name them in §6,
  do not add new ones in this change).
- **Anti-pattern**: parity checksums as oracles; browser e2e; copying
  current scorer output as the expected value.

§3 **Risks covered** cells: Phase 1 remains #1–#3; Phase 2 #4–#5; Phase 3
#6; Phase 4 cross-cutting. Do not claim Phase 1 covers #7.

#### 2. Rollout ledger

**File**: `context/foundation/test-plan.md` (§3 table)

**Intent**: Make the orchestrator table match archive and CI reality so
`/10x-test-plan` resumes at the first truly pending phase (narrowed
Phase 2).

**Contract**:

- Phase 1: Status `complete`; Change folder
  `testing-critical-path-api-isolation`; Goal unchanged.
- Phase 2: Status `not started`; Change folder `—`; Goal narrowed to prove
  remaining package-admission *leftovers* (failed insert leaves no usable
  orphan prefix / risk #5), while control-plane-without-Torch and env-scrub
  are documented as existing oracles in Phase 2 of *this* plan (§6.5) — do
  not mark Phase 2 `complete`.
- Phase 3: Status `not started`; Change folder `—`; Goal unchanged
  (component tests for unauthorized Register/Publish/Select; API error
  shown; no success copy on 403). Test types stay `component (bootstrap
  runner if needed)`.
- Phase 4: Status `complete`; Change folder `—` (no testing-* folder was
  opened; completion is evidenced by `verify.yml` jobs already present).
  Goal restated: lock Phase 1–3 tests into CI *as they exist*, documenting
  the Torch-free `python` job vs the separate Ubuntu `inference` `@ml` job
  — not “without adding `@ml` on Ubuntu.”

Do not add a fifth §3 row for risk #7.

#### 3. Stack and quality gates

**File**: `context/foundation/test-plan.md` (§4, §5)

**Intent**: Replace false test-base and CI sentences with the current
manifest/CI facts. Frontend component runner remains “none yet — see
Phase 3.”

**Contract**:

- §4 profile: pytest configured; 15 `tests/test_*.py` files; frontend
  component suite absent; Verify `python` job uses `-m "not ml"`;
  Verify `inference` job runs `tests/test_inference_service.py` and
  `tests/test_hdfs_inference_parity.py` with `-m ml`. Do not say “CI skips
  `@ml`.”
- Stack table: keep pytest/ruff/mypy/FastAPI/Playwright rows. Optionally
  add one line that the inference service is tested in a separate CI job —
  no CI YAML pasted. Refresh `checked:` dates on stack-grounding tools to
  the implementation date; Docs/Search still “not available in current
  session” unless the implementer re-inspects session tools and records
  what they actually see.
- §5: lint+typecheck required; Torch-free unit+integration required (Phase
  1 complete); frontend component tests still `required after §3 Phase 3`;
  Playwright publication E2E required; CI pytest + inference + frontend
  build + e2e jobs required (Phase 4 complete). Catch column for the CI
  row: silent drop of named API files from the `python` job, or of the
  `inference` job, — not “frontend-test jobs” that do not exist. Do not
  describe all Verify jobs as Torch-free.

### Success Criteria:

#### Automated Verification:

- `context/foundation/test-plan.md` §2 contains risks #1–#6 with those
  numbers unchanged and an appended risk #7 plus a matching Risk Response
  Guidance row
- §3 Phase 1 Status is `complete` and Change folder is
  `testing-critical-path-api-isolation`; Phase 4 Status is `complete`;
  Phase 2 and Phase 3 Status are `not started`
- §4 no longer claims `~8` test files or that CI skips `@ml`
- §5 distinguishes the Torch-free API pytest job from the Ubuntu inference
  `@ml` job
- Section headings remain §1 through §8 in that order; §3 Status values are
  only the schema literals

#### Manual Verification:

- Read §1–§5: isolation is not described as new work; §2 Source has no
  file:line or function-name anchors; Phase 2 goal is leftover admission
  safety, not a blank suite; Phase 3 still requires unauthorized-role UI
  signals rather than existing Publisher Playwright specs

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Update cookbook and negative space

### Overview

Name the S-04–S-06 oracles that already exist so “under-tested after S-03”
is not confused with “no tests.” Correct §7 triggers that still speak as if
S-03/S-04 were future work. Keep ML/parity/checksum expansion excluded.

### Changes Required:

#### 1. Cookbook oracles

**File**: `context/foundation/test-plan.md` (§6)

**Intent**: Extend §6 so a later agent adding analysis/result tests copies
existing HTTP oracles instead of inventing e2e or parity jobs. Do not
rewrite the Phase 1 isolation matrix as if it were new.

**Contract**:

- **§6.2**: Keep the 401/403/404 matrix and named isolation tests. After
  that block, add a short “already shipped — cite, do not rewrite” list for
  analysis/result/provisional behavior, referencing tests by **function
  name** (cookbook may name tests; §2 may not). Minimum names:
  `test_published_v2_model_queues_and_schedules_dispatch`,
  `test_exhausted_dispatch_preserves_queued_run`,
  `test_result_pages_expose_empty_queued_and_failed_run_states`,
  `test_result_pages_are_typed_project_scoped_and_keep_run_wide_summaries`,
  `test_provisional_pages_are_typed_project_scoped_and_exclude_scores`,
  `test_provisional_pages_are_empty_for_queued_and_failed_runs`.
  Patterns to state in prose: queued dispatch is non-terminal; exhausted
  activation preserves queued; result reads of queued/failed stay 200 with
  empty pages and zero summaries; cursor pages are project-scoped and
  keep run-wide summaries; provisional uses a separate page, omits
  score/threshold, does not change heuristically-final counts.
- **§6.3**: Remain TBD for Phase 3 (unauthorized Register/Publish/Select
  with API error, no success copy). Explicitly: existing
  `frontend/e2e/publish-eligible-hdfs-model.spec.ts` and
  `reject-ineligible-hdfs-model.spec.ts` are Publisher publication paths,
  not this oracle.
- **§6.5**: Replace the full TBD. Document control-plane-without-Torch and
  env-scrub via `test_model_package_and_api_sources_do_not_import_torch`
  / `test_object_store_source_does_not_import_torch` /
  `test_scrub_environment_removes_application_secrets`, and ineligible ZIP
  → 422 + no row (`test_registration_rejects_ineligible_zip_without_inserting`).
  State that leftover-prefix cleanup after failed insert remains the
  pending Phase 2 rollout (risk #5); do not claim it complete.
- **§6.6**: Keep the 2026-09-10 isolation note. Append notes that S-04–S-06
  tests landed with product slices, not a test-plan rollout folder, and
  that risk #7 is protected by the named §6.2 oracles.
- **§6.7**: Keep publication-only Playwright scope. Do not add analysis
  E2E.

No test code blocks. No CI YAML.

#### 2. Negative space and freshness

**File**: `context/foundation/test-plan.md` (§7, §8, header)

**Intent**: Align exclusions with the refresh interview and shipped slices
without expanding ML/parity/checksum work.

**Contract**:

- Keep notebooks/BGL exclusion.
- Reword `@ml` on Ubuntu: do not add *new* ML jobs to the Torch-free
  `python` Verify job; a dedicated `inference` job already runs `@ml`.
  Re-evaluate if that split is removed.
- Reword notebook-parity: still do not spend refresh/rollout budget on
  expanding the one-percentage-point parity or checksum suite (refresh
  interview Q5), even though S-04 shipped a release gate. Re-evaluate if
  the team wants parity in the Torch-free API job.
- Remove “S-03 is not implemented.” Intake exists; do not invent a new
  intake test program in this rollout. Invalid whole-dataset reject
  remains covered by existing HTTP tests — cite by name only if needed in
  §6, not as new work.
- Keep browser e2e outside publication (analysis/intake/snapshots out).
- §8: set Strategy / Stack reviewed dates to the implementation date after
  these edits; AI-native `checked:` dates follow whatever the implementer
  actually re-verified.
- Header `Last updated` matches that date.

### Success Criteria:

#### Automated Verification:

- §6.2 names the dispatch, queued/failed, paging, and provisional test
  functions listed in this phase’s Contract (by exact function name)
- §6.3 still TBD for unauthorized-role UI and does not treat Playwright
  publication specs as that oracle
- §6.5 no longer reads only “TBD — see §3 Phase 2” and still states
  leftover-prefix cleanup as pending
- §7 no longer claims S-03 is unimplemented or that notebook-parity waits
  until S-04 opens
- §6.2 isolation matrix and named Phase 1 tests remain (not deleted or
  replaced by a new isolation program)

#### Manual Verification:

- A new analysis/result test recipe is copy-pasteable from §6 without
  implying new ML, parity, or checksum work
- §7 still forbids expanding those suites; remaining Phase 2/3 work is
  obvious from §3 + §6.3/§6.5

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Verify the guide as an orchestrator artifact

### Overview

Prove the file is still a valid `/10x-test-plan` state machine and that this
change did not alter product code or CI. First pending §3 row after this
refresh must be Phase 2 (narrowed admission leftovers).

### Changes Required:

#### 1. Consistency check

**File**: `context/foundation/test-plan.md` (read/confirm; edit only if a
prior phase left a schema break)

**Intent**: Catch orchestrator-breaking drift (bad status strings, missing
§3 columns, §2 anchors, section reorder) before archive.

**Contract**: §3 table still has columns `# | Phase name | Goal | Risks
covered | Test types | Status | Change folder`. Status cells are only
schema literals. First non-`complete` row is Phase 2. Risk #7 is not given
a new §3 phase. No fenced test-code or workflow YAML in the guide. Product
tree under `src/`, `tests/`, `frontend/`, and `.github/workflows/` has no
edits from this change.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py tests/test_inference_dispatch.py tests/test_model_package.py tests/test_object_store.py tests/test_model_validator.py -m "not ml"`
  still passes (no product-test edits)
- `git diff --stat` for this change lists `context/foundation/test-plan.md`
  (and this change folder) only — not `src/`, `tests/`, `frontend/`, or
  `.github/workflows/`
- `rg -n 'file:line|src/[a-z_]+/[a-z_]+\.py:[0-9]+' context/foundation/test-plan.md`
  finds no §2-style code anchors (cookbook may still name `tests/test_api.py`
  and test function identifiers)

#### Manual Verification:

- Read the whole guide once: §3 would send `/10x-test-plan` to narrowed
  Phase 2 next; risk #7 is visible in §2 and mapped to named §6 tests;
  dates in the header and §8 match the reconciled content, not a stale
  E2E-only bump

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- None. This change is the test-plan document.

### Integration Tests:

- Re-run the existing Torch-free tests named in Phase 3 to prove the
  refresh did not touch them. Do not add tests whose expected values are
  copied from current implementation.

### Manual Testing Steps:

1. Read §3 as the orchestrator would: first pending phase is 2, not 1.
2. Confirm §2 risk #7 has evidence-only Source and a response row.
3. Confirm §6 recipes for dispatch/queued/failed/paging/provisional and
  that isolation/Playwright sections were not turned into new programs.
4. Confirm §7 exclusions match the refresh Q5 (no new ML/parity/checksum
  suites) without claiming S-03/S-04 never shipped.

## Performance Considerations

None. Documentation-only.

## Migration Notes

Not applicable. No schema or API change. After this lands, `/10x-test-plan`
(without `--refresh`) should open or resume **testing-** Phase 2 (narrowed
package-admission leftovers), not isolation.

## References

- Frame brief: `context/changes/test-plan-refresh-2026-09-13/frame.md`
- Guide: `context/foundation/test-plan.md`
- Schema: `.cursor/skills/10x-test-plan/references/test-plan-schema.md`
- Roadmap Done: `context/foundation/roadmap.md` (S-03–S-06)
- Phase 1 archive: `context/archive/2026-09-10-testing-critical-path-api-isolation/`
- S-04–S-06 archives: `context/archive/2026-09-11-run-parity-hdfs-analysis/`,
  `context/archive/2026-09-12-inspect-hdfs-analysis-results/`,
  `context/archive/2026-09-13-separate-provisional-hdfs-results/`
- CI: `.github/workflows/verify.yml:14-82`
- Lessons: leftover-prefix cleanup; real subprocess `@ml` tests; no
  untrusted `.pt` in the control plane — do not expand those suites here

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Reconcile strategy, ledger, stack, and gates

#### Automated

- [x] 1.1 `context/foundation/test-plan.md` §2 contains risks #1–#6 with those numbers unchanged and an appended risk #7 plus a matching Risk Response Guidance row — 2891b79
- [x] 1.2 §3 Phase 1 Status is `complete` and Change folder is `testing-critical-path-api-isolation`; Phase 4 Status is `complete`; Phase 2 and Phase 3 Status are `not started` — 2891b79
- [x] 1.3 §4 no longer claims `~8` test files or that CI skips `@ml` — 2891b79
- [x] 1.4 §5 distinguishes the Torch-free API pytest job from the Ubuntu inference `@ml` job — 2891b79
- [x] 1.5 Section headings remain §1 through §8 in that order; §3 Status values are only the schema literals — 2891b79

#### Manual

- [x] 1.6 Read §1–§5: isolation is not described as new work; §2 Source has no file:line or function-name anchors; Phase 2 goal is leftover admission safety, not a blank suite; Phase 3 still requires unauthorized-role UI signals rather than existing Publisher Playwright specs — 2891b79

### Phase 2: Update cookbook and negative space

#### Automated

- [x] 2.1 §6.2 names the dispatch, queued/failed, paging, and provisional test functions listed in this phase’s Contract (by exact function name)
- [x] 2.2 §6.3 still TBD for unauthorized-role UI and does not treat Playwright publication specs as that oracle
- [x] 2.3 §6.5 no longer reads only “TBD — see §3 Phase 2” and still states leftover-prefix cleanup as pending
- [x] 2.4 §7 no longer claims S-03 is unimplemented or that notebook-parity waits until S-04 opens
- [x] 2.5 §6.2 isolation matrix and named Phase 1 tests remain (not deleted or replaced by a new isolation program)

#### Manual

- [x] 2.6 A new analysis/result test recipe is copy-pasteable from §6 without implying new ML, parity, or checksum work
- [x] 2.7 §7 still forbids expanding those suites; remaining Phase 2/3 work is obvious from §3 + §6.3/§6.5

### Phase 3: Verify the guide as an orchestrator artifact

#### Automated

- [ ] 3.1 `python -m pytest tests/test_api.py tests/test_inference_dispatch.py tests/test_model_package.py tests/test_object_store.py tests/test_model_validator.py -m "not ml"` still passes (no product-test edits)
- [ ] 3.2 `git diff --stat` for this change lists `context/foundation/test-plan.md` (and this change folder) only — not `src/`, `tests/`, `frontend/`, or `.github/workflows/`
- [ ] 3.3 `rg -n 'file:line|src/[a-z_]+/[a-z_]+\.py:[0-9]+' context/foundation/test-plan.md` finds no §2-style code anchors (cookbook may still name `tests/test_api.py` and test function identifiers)

#### Manual

- [ ] 3.4 Read the whole guide once: §3 would send `/10x-test-plan` to narrowed Phase 2 next; risk #7 is visible in §2 and mapped to named §6 tests; dates in the header and §8 match the reconciled content, not a stale E2E-only bump
