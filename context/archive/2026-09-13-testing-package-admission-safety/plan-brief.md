# Package admission leftover-prefix safety — Plan Brief

> Full plan: `context/changes/testing-package-admission-safety/plan.md`
> Research: `context/changes/testing-package-admission-safety/research.md`

## What & Why

A failed model register can leave object-store files after `put` if the
database insert fails for any reason other than a duplicate identity.
This change proves leftover prefixes are gone (risk #5) and cites existing
Torch-free admission tests for risk #4.

## Starting Point

Validate → put → insert already cleans validation failure, put failure, and
duplicate **409**. Ineligible ZIP and 409 key oracles exist. Non-integrity
insert failure (F8) and Bucket `delete_objects` Errors (F7) do not.

## Desired End State

Register that fails after `put` returns **5xx**, inserts no row, and leaves
no usable prefix. Bucket cleanup raises on S3 `Errors`. The test-plan
cookbook names those oracles and still cites risk #4 tests.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Dataset twin | Package register only | Avoid a second intake suite; document 409-only dataset cleanup | Plan |
| F7 Bucket Errors | Raise + FakeS3 unit test | Risk #5 Source cites F7; no MinIO | Research / Plan |
| Risk #4 spawn-env test | Skip; cite §6.5 | Already proven; not the Phase 2 goal | Research / Plan |
| Non-integrity HTTP | Delete prefix, re-raise → 5xx | Do not invent a 4xx body; keep 409 for integrity only | Plan |
| F8 test trigger | Monkeypatch `_insert_audit_event` after fixture setup | Real put + DB rollback without mocking the store | Research / Plan |

## Scope

**In scope:** F8 handler + HTTP leftover-prefix test; F7 Errors raise +
FakeS3 test; §6.5/§6.6/§3 Phase 2 cookbook.

**Out of scope:** Dataset except widening; `@ml`/Torch/parity; spawn-env
contract; Playwright; CI YAML; §1–§2 rewrite.

## Architecture / Approach

HTTP integration against the real filesystem object store for F8. Adapter
unit test with FakeS3 for F7. Integrity `except` stays first so duplicates
cannot become 5xx.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. F8 leftover prefix | 5xx + empty keys after failed insert | Catching `Exception` before `DatabaseIntegrityError` |
| 2. F7 Bucket Errors | Raise on `Errors`; FakeS3 test | Treating happy-path FakeS3 delete as enough |
| 3. Cookbook | §6.5 shipped leftover-prefix pattern | Claiming dataset intake is done |

**Prerequisites:** research.md; Torch-free pytest as in Verify `python` job.
**Estimated effort:** ~1 session across 3 phases.

## Open Risks & Assumptions

- Audit-insert failure is a faithful stand-in for other non-integrity errors.
- Dataset leftover prefixes remain until a later change.

## Success Criteria (Summary)

- Failed register after put leaves no object files and no model row.
- Bucket `Errors` cannot look like a successful delete.
- Later agents copy §6.5 instead of inventing E2E or mocked-store tests.
