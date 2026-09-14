---
date: 2026-09-13T23:48:08+02:00
researcher: michalklos
git_commit: 4fc806ef2d97445633aed874756fdaa61b440df2
branch: feature/test-plan-refresh
repository: hybrid-logs-analyzer
topic: "Ground rollout Phase 2: package admission safety (risks #4–#5)"
tags: [research, codebase, fastapi, object-store, model-validator, leftover-prefix, pytest]
status: complete
last_updated: 2026-09-13
last_updated_by: michalklos
---

# Research: Ground rollout Phase 2: package admission safety (risks #4–#5)

**Date**: 2026-09-13T23:48:08+02:00
**Researcher**: michalklos
**Git Commit**: 4fc806ef2d97445633aed874756fdaa61b440df2
**Branch**: feature/test-plan-refresh
**Repository**: hybrid-logs-analyzer

## Research Question

Ground rollout Phase 2 of `context/foundation/test-plan.md` ("Package admission safety").

Risks to verify:

- **#4:** prove the control plane admits/rejects without loading the `.pt`, and the validator environment has no app secrets. Challenge: “validator ran” means Torch in the API process is acceptable. Avoid importing Torch in API tests “to be realistic.”
- **#5:** prove a duplicate or failed insert leaves only the first declared prefix, or nothing. Challenge: HTTP 409/5xx implies storage was cleaned. Avoid mocking the store so cleanup never runs.

For each risk: ground the live failure path, verify or correct the test-plan response guidance, locate existing tests, name the cheapest useful layer, and flag speculative risks or misleading hot-spot evidence.

## Summary

Neither risk is speculative. Hot-spot `src/api` is the right place.

**Risk #4 is already protected.** The API never imports Torch. Register unpacks to a temp dir, probes in an isolated subprocess (`run_private_package_validator`), then `put`s declared bytes. Torch-free AST/import tests plus `test_scrub_environment_removes_application_secrets` already exist; a real `python -m src.model_validator` path exists under `@ml`. Phase 2 should **cite these, not rewrite them**. Optional leftover: assert `allowed_validator_environment` at spawn time (Torch-free contract). Do not add Torch to the `not ml` API job.

**Risk #5 is a real leftover, not a blank suite.** Admission is validate → put → insert. Cleanup already runs on (a) validation before put, (b) put/materialize failure, (c) duplicate insert **409**. Tests already list filesystem keys for ineligible ZIP (empty store) and duplicate 409 (first prefix only). The residual is **S-02 F8**: `delete_prefix` runs only on `DatabaseIntegrityError`. A non-integrity insert failure after put leaves the prefix. **S-02 F7** is still open: Bucket `delete_objects` ignores per-key `Errors`. Proving the Phase 2 goal therefore needs a **product rollback** plus an integration oracle against the real `FilesystemObjectStore` — not a mock, and not treating 409/ineligible tests as enough.

## Detailed Findings

### Risk #4 — Torch and secrets stay out of the control plane

Admission HTTP documents the contract and never deserializes:

```418:431:src/api/main.py
        """Admit a Publisher ZIP upload. Never loads the artifact in this process."""
        ...
            report, admitted = admit_uploaded_zip_package(
```

Probe vs store (`src/api/validation.py`):

1. Unpack ZIP to a temp directory (no object-store write).
2. Spawn `settings.model_validator_command` or `(sys.executable, "-m", "src.model_validator")` with `env=allowed_validator_environment(...)` (`src/api/validation.py:100-120`). Docstring: “Never load the artifact here.”
3. Invalid report → return, **put nothing**.
4. Valid → SHA-256 re-read, then `object_store.put` declared files only (`src/api/validation.py:196-216`, cleanup on put failure `238-247`).

`torch.load` for admission lives only in `src/model_validator/runtime.py:69-77` (`weights_only=True`). `src/api/`, `src/api/object_store.py`, and `src/modules/model_package.py` do not import Torch. Research `src/modules/model.py` still has `weights_only=False`; that is **not** the register path.

Child process also calls `scrub_environment()` (`src/model_validator/__main__.py`). Parent already filters env before spawn.

**Existing oracles (cite, do not rewrite):**

| Test | Layer | What it actually proves |
|------|--------|-------------------------|
| `test_model_package_and_api_sources_do_not_import_torch` | Torch-free AST | `model_package.py`, `inference_bundle.py`, `api/main.py`, `api/validation.py` have no `import torch` (`tests/test_model_validator.py:21-35`) |
| `test_object_store_source_does_not_import_torch` | Torch-free AST | `object_store.py` (`tests/test_object_store.py:69-79`) |
| `test_scrub_environment_removes_application_secrets` | Torch-free unit | `scrub_environment()` drops JWT/Azure/AWS/store keys (`tests/test_model_validator.py:55-76`). Does **not** assert spawn `env=` |
| `test_registration_rejects_ineligible_zip_without_inserting` | HTTP + real FS store | 422, empty model list, **no object files** (`tests/test_api.py:1230-1240`) |
| `test_http_admission_uses_real_validator_probe` | `@ml` HTTP | Real `python -m src.model_validator`; dummy/pickle → 422; valid `torch.save` → 201 (`tests/test_api.py:1283+`) |

Default API fixture uses stub `files_only_validator.py` — stubbed HTTP is not the real probe. The `@ml` test already covers the lesson “exercise real isolated subprocesses.”

**Response-guidance correction:** cheapest remaining #4 work is an optional Torch-free assertion that `allowed_validator_environment` strips secrets **before** `subprocess.run`. Importing Torch in `not ml` API tests would destroy the signal. Do not expand the `@ml` / parity / checksum suites in this phase.

### Risk #5 — leftover prefixes after failed insert

**Sequence:** validate in temp → `put` declared objects → `database.create_model_version`. Prefixes: `projects/<project>/models/<model_id>/<version>` (`src/api/object_store.py:51-52, ~89-92`).

**Cleanup callers today:**

| When | Where |
|------|--------|
| Put/materialize failure | `src/api/validation.py:238-247` — deletes package + bundle prefixes |
| Duplicate identity | `src/api/main.py:483-490` — `except DatabaseIntegrityError` only, then HTTP 409 |
| Dataset duplicate | `src/api/main.py:751-756` — same integrity-only pattern |

There is **no** `except Exception` around insert that deletes then re-raises. A connection loss or other operational error after put leaves objects. That matches archived **F8** (`context/archive/2026-09-10-publish-hdfs-model-package/reviews/impl-review.md:111-119`) and `lessons.md` “Roll back object storage after every failed admission.”

**Bucket F7:** `BucketObjectStore.delete_prefix` lists keys then calls `delete_objects` and **does not inspect** the returned `Errors` list (`src/api/object_store.py:258-267`). boto3 can return HTTP 200 with per-key errors; 409 cleanup can “succeed” while keys remain. `FakeS3Client.delete_objects` in tests returns `{}` and never simulates Errors.

**Already handled (do not re-test as new work):**

- Oversize / unpack / ineligible ZIP: no put. HTTP 422 + empty store: `test_registration_rejects_ineligible_zip_without_inserting`.
- Duplicate register 409: second prefix deleted; first declared files remain (`tests/test_api.py:678-689`; v2 snapshot `:1428-1434`).
- ZIP member named `leftover.bin`: never put (declared-files-only) — **different meaning** of leftover (`:1213-1227`).

**Not covered:** no test forces a **non-integrity** insert failure after a successful put and lists `_object_files`. Helper already exists (`tests/test_api.py:182-187`). API tests use a **real** `FilesystemObjectStore` under `tmp_path` (`:53-61`); do not mock it for this oracle.

**Response-guidance correction:** the challenge “HTTP 409/5xx implies storage was cleaned” is **half-true**. 409 is cleaned and tested. 5xx after put is **not** cleaned in product code. Phase 2 must prove the failed-insert case, not treat 409 as the whole risk.

Dataset intake shares the same integrity-only `delete_prefix` (`src/api/main.py:751-752`). HDFS-only MVP, but it is not the §3 Phase 2 goal. Note the twin; do not turn this change into a second intake suite unless the same `except` is widened.

### Existing tests vs cookbook §6.5

§6.5 is accurate: Torch/env-scrub/ineligible ZIP exist; leftover-prefix after failed insert is still pending. Isolation Phase 1 deferred F7/F8 on purpose (`context/archive/2026-09-10-testing-critical-path-api-isolation/research.md`).

## Code References

- `src/api/main.py:409-491` — register: admit, 422/503 mapping, insert, 409-only `delete_prefix`
- `src/api/main.py:751-756` — dataset twin: 409-only `delete_prefix`
- `src/api/validation.py:100-120` — isolated validator, filtered env, no Torch in API
- `src/api/validation.py:196-247` — put after valid report; delete prefixes on put failure
- `src/api/object_store.py:42-52` — Protocol: put/get/`delete_prefix` (no public list)
- `src/api/object_store.py:258-267` — Bucket delete ignores `Errors` (F7)
- `src/model_validator/runtime.py:69-77` — only admission `torch.load(..., weights_only=True)`
- `tests/test_api.py:182-187` — `_object_files` oracle for leftover keys
- `tests/test_api.py:678-689` — duplicate 409 keeps first prefix only
- `tests/test_api.py:1230-1240` — ineligible ZIP: 422, no row, no files
- `tests/test_model_validator.py:21-76` — Torch-free sources + `scrub_environment`
- `tests/test_object_store.py:69-79` — object-store AST Torch ban
- `context/foundation/lessons.md:18-24` — rollback after every failed admission
- `context/foundation/lessons.md:26-31` — real `@ml` subprocess, already present for validator

## Architecture Insights

- **Validate before durable writes; DB last.** Put happens only after a valid isolated report. That is why ineligible ZIP cannot orphan prefixes — there is nothing to delete.
- **409 is not “any insert failure.”** Unique `(project_id, model_identifier, version)` maps to `DatabaseIntegrityError`. Other insert failures skip cleanup.
- **ObjectStore has no list in the protocol.** Tests observe leftovers via the filesystem root (`rglob`), which is the cheap independent oracle. Do not add a production list API just to test.
- **Cost × signal:** one FastAPI integration that stubs `create_model_version` (or the session) to raise a non-integrity error after a real put, then asserts `_object_files` empty / unchanged, is cheaper than Playwright or `@ml`. A separate unit test on `BucketObjectStore.delete_prefix` that feeds `Errors` covers F7 without MinIO.
- **This phase is not tests-only if the goal is protection.** A leftover-prefix test against current `except DatabaseIntegrityError` will fail until `delete_prefix` runs on a broader except (F8 fix), then re-raises. Plan should make that product change explicit so `/10x-implement` is not surprised.

## Historical Context (from prior changes)

- `context/archive/2026-09-10-publish-hdfs-model-package/reviews/impl-review.md` — F7 PENDING (S3 `Errors`); F8 PENDING (non-409 insert). F3 FIXED was only the duplicate-409 *test*.
- `context/archive/2026-09-10-testing-critical-path-api-isolation/research.md` — explicitly deferred risks #4/#5 and F7/F8 to Phase 2; duplicate 409 already asserted.
- `context/archive/2026-09-13-test-plan-refresh-2026-09-13/plan.md` — leftover-prefix cleanup remains pending; do not claim Phase 2 complete from env-scrub or ineligible ZIP.
- `context/archive/2026-09-09-trusted-model-package-contract/plan.md` — F-02 Torch isolation (API process vs validator). Not leftover prefixes.

## Related Research

- `context/archive/2026-09-10-testing-critical-path-api-isolation/research.md` — Phase 1 isolation; defers this phase
- `context/archive/2026-09-10-publish-hdfs-model-package/research.md` — S-02 admission product path

## Open Questions

1. Should dataset intake’s identical 409-only `except` be widened in the same change, or only documented as a twin for a later test? Recommendation: if the handler `except` is copied, cover dataset with one sibling HTTP + `_object_files` assertion; do not invent a new intake program.
2. Is F7 in scope? Risk #5 Source cites F7/F8. Recommendation: yes — one Bucket unit test that fails until `Errors` raises; keep it off the Torch-free HTTP fixture (FakeS3 only).
3. Should the optional `allowed_validator_environment` spawn-env test land here? Recommendation: only if it stays a few lines of Torch-free contract; it is not the Phase 2 goal.

## Backport notes for `/10x-test-plan`

- §2 Source (`src/api`, F7/F8) is not misleading.
- Risk #4 response guidance stays valid; research adds “already proven — cite §6.5.”
- Risk #5 “must challenge” is confirmed for 5xx, not for 409.
- No speculative-risk drop. No file:line belongs in §2.
