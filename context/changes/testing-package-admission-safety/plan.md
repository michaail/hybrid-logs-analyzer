# Package admission leftover-prefix safety Implementation Plan

## Overview

Prove a failed model-package admit leaves no usable object-store prefix
(test-plan risks #4–#5). Risk #4 is already covered by named §6.5 tests;
this change cites them. Risk #5 needs a product rollback on non-integrity
insert failure (S-02 F8) plus a Bucket `delete_objects` Errors raise
(S-02 F7), each with a Torch-free oracle against a real or FakeS3 store.

## Current State Analysis

Research (`context/changes/testing-package-admission-safety/research.md`)
is the baseline. There is no frame brief.

Admission is validate-in-temp → `put` declared files →
`database.create_model_version`. `delete_prefix` already runs on put
failure (`src/api/validation.py:238-247`) and on
`DatabaseIntegrityError` → HTTP **409** (`src/api/main.py:483-490`).
Ineligible ZIP never puts; duplicate 409 already lists filesystem keys
(`tests/test_api.py:1230-1240`, `:678-689`).

Residual: any other exception from `create_model_version` (including
`_insert_audit_event` after INSERT in the same session,
`src/api/storage.py:592-611`) rolls the DB back and leaves the prefix.
Bucket `delete_prefix` ignores boto3 `Errors` (`src/api/object_store.py:258-267`).
Dataset upload uses the same 409-only `except` (`src/api/main.py:751-756`);
this change documents that twin and does not widen it.

Risk #4: control plane does not import Torch; probe is a subprocess;
§6.5 tests stay the oracle. Spawn-env assertion is out of this plan.

## Desired End State

- A Publisher ZIP register that survives `put` and then hits a
  **non-integrity** insert failure returns FastAPI **5xx**, inserts **no**
  model row, and leaves **no** files under the object-store root (or only
  unrelated pre-existing keys). Duplicate register remains **409** with
  the first prefix kept.
- `BucketObjectStore.delete_prefix` raises when `delete_objects` returns a
  non-empty `Errors` list. FakeS3 covers that without MinIO.
- `context/foundation/test-plan.md` §6.5 names the new leftover-prefix
  tests, still cites the existing Torch/env-scrub/ineligible oracles, and
  states leftover-insert cleanup as shipped for **model register** only.
  Dataset 409-only cleanup remains a documented twin.

Verify with Torch-free pytest on `tests/test_api.py` and
`tests/test_object_store.py`.

### Key Discoveries:

- Integrity vs other failures must stay split: `except DatabaseIntegrityError`
  → 409 **before** a broader `except` that deletes and re-raises
  (`src/api/main.py:483-490`).
- Realistic F8 trigger already exists in tests: monkeypatch
  `ApiDatabase._insert_audit_event` (`tests/test_api.py:329-331`). Apply it
  **after** the `api` fixture bootstraps the admin, then `_register`.
- `_object_files` (`tests/test_api.py:182-187`) is the leftover oracle;
  the `api` fixture already uses a real `FilesystemObjectStore`.
- FakeS3 `delete_objects` always succeeds and pops keys
  (`tests/test_object_store.py:56-59`); F7 needs a variant that returns
  `Errors` **without** deleting.
- Lesson: roll back object storage after every failed admission
  (`context/foundation/lessons.md:18-24`).

## What We're NOT Doing

- New Torch, `@ml`, parity, or checksum tests; importing Torch in the
  API `not ml` job.
- Asserting `allowed_validator_environment` at spawn time.
- Widening dataset intake `except` or adding a second intake suite
  (§7 / user decision: package register only).
- Rewriting ineligible-ZIP or duplicate-409 tests.
- Frontend, Playwright, CI YAML, `requirements-macos-intel.lock.txt`.
- A production object-store list API (tests use filesystem `rglob`).
- Mapping non-integrity failures to 409 or a structured leftover body.
- Renumbering test-plan risks or rewriting §1–§2.

## Implementation Approach

Test-first on the HTTP leftover path, then the Bucket Errors contract,
then cookbook. Cost × signal: one FastAPI integration against the real
FS store; one FakeS3 unit test. Product changes are the minimum F8/F7
fixes so those oracles can pass. Keep risk #4 as citations only.

## Critical Implementation Details

Catch `DatabaseIntegrityError` first and keep the 409 mapping. A new
bare `except Exception` that runs first would turn duplicates into 5xx
and delete the first prefix. Monkeypatch `_insert_audit_event` only for
the register call, not during `bootstrap_administrator`. For F7, raise
when the `delete_objects` return mapping has a non-empty `Errors` list;
successful deletes (empty or missing `Errors`) stay silent.

## Phase 1: Failed-insert leftover prefix (F8)

### Overview

Prove a non-integrity insert failure after a successful `put` leaves no
usable model prefix, then make register delete and re-raise.

**Behavior asserted:** 5xx, empty model list, no leftover object files.

**Regression caught:** audit/connection failure after put orphans a
prefix another caller could hit.

**Research source:** F8; `src/api/main.py:483-490`;
`tests/test_api.py:329-331`, `:182-187`.

**Edge/error/boundary:** Duplicate 409 path unchanged; ineligible ZIP
still puts nothing.

**Anti-pattern avoided:** mocking `object_store` so cleanup is a no-op;
replacing `create_model_version` so `put` never runs.

### Changes Required:

#### 1. HTTP leftover-prefix oracle

**File**: `tests/test_api.py`

**Intent**: After a real admit `put`, force a non-`DatabaseIntegrityError`
from `create_model_version` (reuse `_fail_audit_event` on
`ApiDatabase._insert_audit_event`) and assert 5xx + empty list +
`_object_files == set()`.

**Contract**: Torch-free; use `api` fixture, Publisher `_register` of an
eligible v1 ZIP (`_zip_staged`). Monkeypatch after fixture setup. Do not
stub `FilesystemObjectStore`. Duplicate-409 assertions in
`test_model_publication_and_safe_analysis_run_lifecycle` must still pass.

#### 2. Register rollback on any insert failure

**File**: `src/api/main.py`

**Intent**: After a successful admit, delete the package (and bundle)
prefix when `create_model_version` fails for any reason other than
integrity conflict, then re-raise so FastAPI returns 5xx.

**Contract**: Keep `except DatabaseIntegrityError` → `delete_prefix` →
HTTP 409. Add a subsequent `except Exception` that `delete_prefix`s the
same prefixes and re-raises. Do not change dataset upload.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py -m "not ml"` passes, including the
  new leftover-prefix test and existing 409 / ineligible-ZIP key oracles
- `ruff check src/api/main.py tests/test_api.py` and `mypy` pass

#### Manual Verification:

- Confirm the new test observes `_object_files` (or equivalent rglob)
  and does not mock the object store; 409 still maps only integrity
  conflicts

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Bucket delete_objects Errors (F7)

### Overview

Make Bucket prefix cleanup fail loudly when S3 reports per-key Errors.

**Behavior asserted:** `delete_prefix` raises if `Errors` is non-empty;
sibling keys are untouched when the stub does not delete.

**Regression caught:** HTTP 200 + `Errors` list leaves orphans after 409
cleanup.

**Research source:** F7; `src/api/object_store.py:258-267`.

**Anti-pattern avoided:** live MinIO; treating FakeS3 happy-path delete
as proof of Error handling.

### Changes Required:

#### 1. FakeS3 Errors path + unit test

**File**: `tests/test_object_store.py`

**Intent**: Drive `BucketObjectStore.delete_prefix` with a client that
returns `{"Errors": [...]}` and does **not** remove keys; assert raise
and keys still present. Happy-path `test_bucket_put_and_delete_prefix`
stays.

**Contract**: No Torch, no network. Extend `FakeS3Client` or a small
subclass. Empty `Errors` / missing key remains success.

#### 2. Inspect delete_objects Errors

**File**: `src/api/object_store.py`

**Intent**: After each `delete_objects` batch, raise if the result mapping
contains a non-empty `Errors` list so 409/F8 cleanup cannot report
success while keys remain.

**Contract**: `delete_prefix` still lists with the existing prefix filter.
Do not change `FilesystemObjectStore`. No new public list API.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_object_store.py -m "not ml"` passes,
  including the new Errors test
- `ruff check src/api/object_store.py tests/test_object_store.py` and
  `mypy` pass

#### Manual Verification:

- Confirm F7 is unit/FakeS3 only — no MinIO and no HTTP register against
  Bucket in this change

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Cookbook for leftover-prefix tests

### Overview

Record how to add the next admission leftover-prefix test. Risk #4 tests
stay cited, not rewritten.

**Behavior asserted:** §6.5 tells a later agent to list object keys after
failed insert, keep 409 distinct from 5xx, and not mock the store.

**Regression caught:** a later admit path lands with HTTP status only.

**Research source:** this change’s Phase 1–2 tests; test-plan §6.5.

**Anti-pattern avoided:** file:line in §2; claiming env-scrub proves
orphans are gone; inventing an intake suite for the dataset twin.

### Changes Required:

#### 1. Update test-plan cookbook and ledger

**File**: `context/foundation/test-plan.md`

**Intent**: Mark leftover-insert cleanup as shipped for model register;
name the new tests; keep Torch/env-scrub/ineligible citations; note the
dataset twin is still 409-only. Bump header Last updated.

**Contract**:

- **§3 Phase 2** — Status `complete`; Change folder remains
  `testing-package-admission-safety`. Goal line unchanged.
- **§6.5** — No longer “leftover-prefix cleanup … pending.” Cite the new
  F8 HTTP test and F7 FakeS3 test by function name. Keep the four existing
  §6.5 names. One sentence: dataset upload still deletes only on
  integrity conflict; do not treat this phase as an intake program.
- **§6.6** — Short 2026-09-13 (or implementation date) note for this
  rollout.
- Do not edit §1–§2 risk wording. Do not add file:line to §2.

### Success Criteria:

#### Automated Verification:

- `context/foundation/test-plan.md` §6.5 no longer states leftover-prefix
  cleanup as pending for model register
- `python -m pytest tests/test_api.py tests/test_object_store.py -m "not ml"`
  still passes

#### Manual Verification:

- Read §6.5–§6.6: risk #4 tests still cited; dataset twin is explicit;
  no §2-style code anchors; Phase 2 ledger row is `complete`

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- Bucket `delete_prefix` with FakeS3 `Errors` (Phase 2).
- Do not unit-test membership or SQL as leftover proof.

### Integration Tests:

- HTTP register + real FS store + forced audit/insert failure → 5xx +
  empty keys (Phase 1).
- Existing 409 and ineligible-ZIP key oracles remain regression nets.

### Manual Testing Steps:

1. Skim the new HTTP test: store is real FS, oracle is leftover keys.
2. Skim F7: FakeS3 only, Errors non-empty raises.
3. Read §6.5: leftover-insert is documented as shipped for register only.

## Performance Considerations

None. Cleanup is on the failure path only.

## Migration Notes

Not applicable. Existing object prefixes from successful admits are
unchanged. No schema change.

## References

- Research: `context/changes/testing-package-admission-safety/research.md`
- Test plan: `context/foundation/test-plan.md` §3 Phase 2, §6.5, risk #4–#5
- S-02 F7/F8: `context/archive/2026-09-10-publish-hdfs-model-package/reviews/impl-review.md`
- Lesson: `context/foundation/lessons.md` (roll back object storage)
- Similar HTTP fixture: `tests/test_api.py:53-61`, `:182-187`, `:329-331`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Failed-insert leftover prefix (F8)

#### Automated

- [x] 1.1 `python -m pytest tests/test_api.py -m "not ml"` passes, including the new leftover-prefix test and existing 409 / ineligible-ZIP key oracles — c4d77bf
- [x] 1.2 `ruff check src/api/main.py tests/test_api.py` and `mypy` pass — c4d77bf

#### Manual

- [x] 1.3 Confirm the new test observes `_object_files` (or equivalent rglob) and does not mock the object store; 409 still maps only integrity conflicts — c4d77bf

### Phase 2: Bucket delete_objects Errors (F7)

#### Automated

- [x] 2.1 `python -m pytest tests/test_object_store.py -m "not ml"` passes, including the new Errors test — 7f5a12e
- [x] 2.2 `ruff check src/api/object_store.py tests/test_object_store.py` and `mypy` pass — 7f5a12e

#### Manual

- [x] 2.3 Confirm F7 is unit/FakeS3 only — no MinIO and no HTTP register against Bucket in this change — 7f5a12e

### Phase 3: Cookbook for leftover-prefix tests

#### Automated

- [x] 3.1 `context/foundation/test-plan.md` §6.5 no longer states leftover-prefix cleanup as pending for model register
- [x] 3.2 `python -m pytest tests/test_api.py tests/test_object_store.py -m "not ml"` still passes

#### Manual

- [x] 3.3 Read §6.5–§6.6: risk #4 tests still cited; dataset twin is explicit; no §2-style code anchors; Phase 2 ledger row is `complete`
