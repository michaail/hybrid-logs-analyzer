<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Run parity-preserving HDFS analysis

- **Plan**: context/changes/run-parity-hdfs-analysis/plan.md
- **Scope**: Phases 1–5 of 5 (Phase 1.3 still open; includes uncommitted follow-up work)
- **Date**: 2026-09-12
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical 5 warnings 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | WARNING |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | WARNING |

## Findings

### F1 — Phase 5 is marked complete while baseline provenance is still incomplete

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Plan Adherence
- **Location**: context/changes/run-parity-hdfs-analysis/plan.md:585
- **Detail**: Phase 1.3 remains unchecked because the selected Colab run did not capture a code commit or runtime versions (`baseline.md:22`, `:26`, `:152` still say these are required before declaring FR-011). Ordered block IDs, checksums, threshold, and core metrics are filled, and `releases/hdfs/v3/parity-report.json` exists with `passed: true` (exact F1, exact threshold, PR-AUC/ROC-AUC deltas far below 0.01). Despite that, Progress still marks 5.3 and 5.4 complete, and 5.4’s title is “before claiming FR-011”. That re-opens the previous F5 contradiction: the metric gate ran, but the plan’s “no placeholders / exact code commit” contract is unmet.
- **Fix A ⭐ Recommended**: Keep 1.3 open; uncheck or reword 5.4 so it records the metric-gate report without claiming FR-011; leave FR-011 open until commit and runtime are recovered or explicitly waived.
  - Strength: Matches `baseline.md`’s own remaining prerequisites and the plan’s pause note.
  - Tradeoff: FR-011 stays unclaimed even though the numerical gate already passed.
  - Confidence: HIGH — the baseline file still lists commit/runtime as required.
  - Blind spot: The Colab output may never regain those fields.
- **Fix B**: Close 1.3 with an explicit exception that commit/runtime were unrecoverable, and treat 5.4 as metric-gate approval only.
  - Strength: Stops blocking S-04 on provenance the training environment never wrote down.
  - Tradeoff: Weakens the “immutable exact commit” contract the plan required.
  - Confidence: MEDIUM — depends on whether FR-011 is defined as metrics-only or full reproducibility.
  - Blind spot: Future re-exports cannot prove they used the same code revision.
- **Decision**: FIXED — Fixed via Fix B; 1.3 closed with commit/runtime unrecovered-by-exception; 5.4 is metric-gate approval only

### F2 — Colab workspace binaries are committed to git

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Scope Discipline
- **Location**: artifacts_colab/
- **Detail**: Phase 1 committed three Colab folders, including two non-selected runs and two 86,261-line `test_component_scores.csv` files. The plan called for an ignored workspace release directory; `.gitignore` already ignores `artifacts/`, `data/`, `models/hdfs/`, and `releases/`, but not `artifacts_colab/`. Checksums already live in `baseline.md`. This fights AGENTS.md’s repo-vs-workspace-data boundary and bloats the slice (~180k insertions).
- **Fix A ⭐ Recommended**: Add `artifacts_colab/` to `.gitignore` and stop tracking the committed folders; keep SHA-256 values in `baseline.md`.
  - Strength: Restores the ignored-workspace contract; checksums remain the oracle.
  - Tradeoff: Git no longer carries the raw Colab `.pt`/metrics files (they remain on disk locally).
  - Confidence: HIGH — selected hashes are already recorded.
  - Blind spot: History still contains the blobs unless a later history rewrite is chosen (out of scope here).
- **Fix B**: Keep only the selected run’s `metrics.json` (small text) and gitignore binaries, figures, and the other two runs.
  - Strength: Leaves a readable metric source next to the checksum table.
  - Tradeoff: Still a special-case workspace path in git.
  - Confidence: MEDIUM — `metrics.json` is already checksummed and quoted in `baseline.md`.
  - Blind spot: Someone may still treat the git copy as the mutable oracle.
- **Decision**: FIXED — Fixed via Fix A; gitignored artifacts_colab/ and untracked committed Colab folders

### F3 — Uncommitted PRD and roadmap add a later product slice to this change

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Scope Discipline
- **Location**: context/foundation/prd.md:95
- **Detail**: The working tree adds US-03, FR-012, FR-013, roadmap F-03, S-06, and stream D (provisional vs finalized HDFS block histories). None of that is in this plan, and the analysis implementation still scores every matched block as anomaly or normal. These edits change the product contract and the open milestone while S-04 is in-progress.
- **Fix A ⭐ Recommended**: Revert the PRD/roadmap provisional-result edits from this change and land them as a separate shaping/roadmap update.
  - Strength: Keeps this slice’s source-of-truth aligned with what was implemented.
  - Tradeoff: The incomplete-block insight has to be recaptured in a later change.
  - Confidence: HIGH — the new FRs are unimplemented and blocked on an owner decision.
  - Blind spot: Other in-flight docs may already assume the new FRs.
- **Fix B**: Keep the foundation edits as an intentional product-contract update, clearly not as S-04 implementation.
  - Strength: Records a real evaluation finding while it is fresh.
  - Tradeoff: Reviewers of this change must ignore new must-have FRs that this code does not satisfy.
  - Confidence: MEDIUM — useful only if the owner already wants that next slice queued.
  - Blind spot: `/10x-status` and later reviews may treat FR-012/013 as in-scope for S-04.
- **Decision**: FIXED — Fixed via Fix B; PRD/roadmap provisional-result FRs kept as a queued product-contract update, explicitly out of S-04

### F4 — Drain snapshot load is jsonpickle in the secret-bearing inference process

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/modules/parser/drain_parser.py:263
- **Detail**: Production scoring calls `DrainParser.load` on admitted `drain_parser.bin` (`hdfs_inference.py:133`). Drain3 `TemplateMiner.load_state` reconstructs objects via jsonpickle. The isolated validator checksums those bytes and never deserializes them. First load happens in the inference process, which has `DATABASE_URL` and object-store keys. A provisioned Publisher who can admit a v2 bundle can therefore execute code on the worker. Operators cannot hit this path. The plan required frozen Drain snapshots, so this is a planned hazard, not accidental drift. `.pt` uses `weights_only=True` and NPZ uses `allow_pickle=False`; the snapshot is the remaining executable-shaped artifact.
- **Fix A ⭐ Recommended**: Document this as an accepted trusted-Publisher risk for MVP (checksum-bound Drain3 FilePersistence, Publisher-only admission).
  - Strength: Matches the planned Drain contract and avoids a parity-breaking format change.
  - Tradeoff: The inference process remains a deserialization sink with data-store credentials.
  - Confidence: HIGH — admission is already Publisher-gated and checksum-bound.
  - Blind spot: Validator isolation does not constrain a malicious Publisher.
- **Fix B**: Deserialize `drain_parser.bin` in a subprocess that has no database or object-store environment, then pass only parsed templates/cluster IDs back.
  - Strength: Aligns with the “inference process has no application secrets” isolation rule.
  - Tradeoff: Extra process boundary and a new failure mode; Drain3 still executes in-process somewhere.
  - Confidence: MEDIUM — Drain3 load is tightly coupled to `TemplateMiner` construction.
  - Blind spot: Have not measured whether jsonpickle can be replaced with a non-object snapshot without breaking parity.
- **Decision**: FIXED — Fixed via Fix A; documented as accepted trusted-Publisher Drain3 jsonpickle risk

### F5 — A killed inference replica can leave a run stuck in `running`

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/inference_service/runner.py:42
- **Detail**: CAS `queued → running` is correct, duplicate execute is a no-op, and dispatch retries never write terminal state. `_fail_run` only runs if the process is still alive. Railway inference is a single replica with `sleepApplication: true`. If that replica is OOM-killed or replaced after claiming the run, the Operator UI can poll `running` forever. Scoring uses `batch_size=1` for up to 25,000 blocks, which makes mid-run death more plausible than a tiny fixture suggests.
- **Fix A ⭐ Recommended**: Add a stale-`running` age threshold that CAS-transitions to `failed` with public `INFERENCE_FAILED` (on a later dispatch, health check, or create path — not a polling worker loop).
  - Strength: Preserves the plan’s “service owns terminal state / dispatch is non-terminal” rule while making death visible.
  - Tradeoff: A slow legitimate run could be failed if the timeout is too aggressive.
  - Confidence: HIGH — there is currently no reclaim path at all.
  - Blind spot: No measured wall-clock for the 25k-block service envelope on staging hardware.
- **Fix B**: Allow an authorized re-dispatch that CAS-moves stale `running` back to `queued` and invokes the private service again.
  - Strength: Recovers work instead of only failing it.
  - Tradeoff: Needs an Operator/API action and care that a still-living worker cannot complete the old claim.
  - Confidence: MEDIUM — requires a generation/lease on the claim, which this schema does not have.
  - Blind spot: Two workers could overlap if the original replica was only slow, not dead.
- **Decision**: FIXED — Fixed via Fix A; stale running claims CAS-fail with INFERENCE_FAILED after 30 minutes on execute or health

### F6 — Unused `public_error_codes()` helper

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: src/inference_service/runner.py:339
- **Detail**: Nothing in the repository calls `public_error_codes()`. It only re-exports `SAFE_MESSAGES`. `InferenceExecutionError` already maps codes in `errors.py`. Project lesson: delete unused code after impl-review, with operator confirmation.
- **Fix**: After operator confirmation, delete `public_error_codes()` and the unused `SAFE_MESSAGES` import in `runner.py`.
- **Decision**: FIXED — deleted unused public_error_codes() and SAFE_MESSAGES import

## Verification

- Git scope: `8e59962^..HEAD` plus uncommitted working-tree edits. Implementation files map to the five planned phases. Justified extras: `src/modules/hdfs_inference.py`, `src/modules/hdfs_parity.py`, `src/inference_service/errors.py`, dispatcher/parity tests, mypy/CI target expansion.
- Prior review findings F1 (manifest/DB binding), F2 (100k/25k caps), F3 (Publisher bundle upload), F4 (mypy + Linux inference CI job), and F6 (shared Railway token) were re-checked in the working tree and remain fixed. Prior F5 is only partially fixed and is restated as F1 above.
- Automated (2026-09-12, `.venv` Python 3.11 / pytest 9.1.1):
  - `ruff check src tests scripts run_ablation.py`: pass
  - `mypy`: pass (69 files, including `src/inference_service` and `scripts/verify_hdfs_parity.py`)
  - `pytest tests/test_api.py tests/test_inference_dispatch.py tests/test_model_package.py tests/test_inference_bundle.py tests/test_object_store.py tests/test_shared_state_repository.py tests/test_migrations.py tests/test_model_validator.py -m "not ml"`: 118 passed, 2 skipped (`TEST_DATABASE_URL` unset)
  - `pytest tests/test_pipeline_smoke.py tests/test_inference_service.py tests/test_hdfs_inference_parity.py`: 42 passed (21 ml + 21 not ml)
  - `npm --prefix frontend run build`: pass
  - Torch-import guard: `tests/test_api.py` asserts the API process does not import `torch`; no `import torch` under `src/api/`
  - Railway IaC CLI: unavailable in this environment (not re-run)
  - Full-corpus parity command: not re-executed; existing `releases/hdfs/v3/parity-report.json` shows `passed: true` with the recorded checksums, exact threshold, exact test F1, and sub-0.01 PR-AUC/ROC-AUC deltas
- Manual Progress:
  - 1.3 still `[ ]` — consistent with missing commit/runtime; not rubber-stamped
  - 2.4, 3.4, 4.3 marked complete on implementation commits; staging cold-start in 4.3 was not independently observed in this review
  - 5.4 marked complete with owner approval of the gitignored parity report; that report exists and matches `baseline.md` numbers

## Triage

- **F1**: FIXED via Fix B
- **F2**: FIXED via Fix A
- **F3**: FIXED via Fix B
- **F4**: FIXED via Fix A
- **F5**: FIXED via Fix A
- **F6**: FIXED

