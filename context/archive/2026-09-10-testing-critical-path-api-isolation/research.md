---
date: 2026-09-10T20:04:25+02:00
researcher: michalklos
git_commit: 43a16ed2eba306f2d6913ba693fcc14280a0c6fc
branch: module3
repository: hybrid-logs-analyzer
topic: "Ground rollout Phase 1: critical-path API isolation (risks #1–#3)"
tags: [research, codebase, fastapi, isolation, roles, model-package, pytest]
status: complete
last_updated: 2026-09-10
last_updated_by: michalklos
---

# Research: Ground rollout Phase 1: critical-path API isolation (risks #1–#3)

**Date**: 2026-09-10T20:04:25+02:00
**Researcher**: michalklos
**Git Commit**: 43a16ed2eba306f2d6913ba693fcc14280a0c6fc
**Branch**: module3
**Repository**: hybrid-logs-analyzer

## Research Question

Ground rollout Phase 1 of `context/foundation/test-plan.md` ("Critical-path API isolation").

Risks to verify:

- **#1:** prove a user cannot observe or act on another project's models, logs, runs, or results (404, not the other project's data). Challenge: “logged in” equals “authorized for this resource.” Avoid happy-path 200 only.
- **#2:** prove Operator register/publish is 403 and creates no version row. Challenge: hiding the UI button is sufficient.
- **#3:** prove ineligible ZIP yields a structured reject with no row, and a registered-but-unpublished version cannot start analysis. Challenge: HTTP 201 on upload means the version is usable.

For each risk: ground the live failure path, verify or correct the test-plan response guidance, locate existing tests, name the cheapest useful layer, and flag speculative risks or misleading hot-spot evidence.

## Summary

None of risks #1–#3 are speculative. The control plane already implements the intended HTTP matrix. Phase 1 is a **coverage gap**, not a missing product gate.

Login is not authorization. `get_current_user` only proves an active bearer (`src/api/main.py:71-86`). Project routes then call `require_project_access` / `require_project_role` (`src/api/main.py:93-114`). Non-members get **404** (“Project was not found.”), not an empty dump of another project. Wrong role after membership gets **403**. Resource IDs fetched from storage are compared to the path `project_id` before return or mutate.

Operator register/publish is denied **before** ZIP admit, object `put`, or `create_model_version` / publish CAS. Existing tests assert **403 only**, not “no new row.” The UI still shows Register/Publish to every project user; API 403 is the control (Phase 3 owns UI copy).

ZIP 201 creates only `eligible` rows. Ineligible ZIP is structured **422** `{valid, issues[]}` with empty model list. Analysis requires `status == published` and same-project model id (**409** / **404**). HTTP 201 does **not** mean usable. There is no persisted `ineligible` status.

Cheapest useful layer for all three risks remains FastAPI `TestClient` integration in `tests/test_api.py` (already in CI). Do not add unit tests that reimplement `require_project_role`. Do not start frontend or e2e in this phase. Do not absorb Risks #4/#5 (Torch-in-API, leftover objects) or `src/modules` / `src/model_validator` churn.

## Detailed Findings

### Auth vs project bind (shared)

- Unauthenticated or inactive token → **401** via `_unauthorized()` (`src/api/main.py:71-81`, `:874-878`).
- Administrator on a member route: `require_project_access` returns `None` and `require_project_role` returns without checking Publisher/Operator (`src/api/main.py:94-110`). This is a **privileged bypass**, not “any logged-in user.” Do not treat Admin 200/201 as a Risk #1/#2 failure unless product intent changes.
- Publisher implies Operator only when `OPERATOR` is in `allowed_roles` (`src/api/main.py:111-112`). Register/publish allow **only** `{PUBLISHER}`, so Operators are 403.
- Storage `get_model_version` / `get_dataset` / `get_analysis_run` are **id-only**. Isolation depends on the HTTP `row["project_id"] != path` check. Lists use `WHERE project_id = ?` (`src/api/storage.py:547-555` and the same pattern for datasets/runs).

### Risk #1 — Cross-project observe/act

**Failure path.** User of project B calls `/projects/{A}/...` → `get_membership(A, user)` is None → **404**. User of B calls `/projects/{B}/.../{id_owned_by_A}` → membership on B succeeds, then ownership compare → **404**. List under B with data only in A → **200** + `[]`.

**Routes that own this risk** (all in `src/api/main.py`):

| Surface | Bind | Foreign / IDOR |
|---------|------|----------------|
| `GET/POST /projects/{id}/models` | access / Publisher role | 404 / Operator 403 |
| `GET .../models/{mid}`, `POST .../publish` | access + `model["project_id"]` (`:453-456`, `:470-473`) | 404 |
| `GET/POST .../analysis-runs` | Operator role; create also checks model project (`:517-520`) | 404; unpublished 409 |
| `GET .../analysis-runs/{rid}`, `.../results` | Operator + `run["project_id"]` (`:622-627`) | 404 |
| `GET .../datasets`, `GET .../datasets/{did}` | Operator + dataset project (`:640-668`) | 404 or `[]` |

Project audit is **admin-only 403** (different status semantics). `/admin/audit-events` is cross-project by design but limited to `resource_type = 'user'`.

**Guidance vs code.** Response guidance is **correct**. Challenge holds: a valid JWT still 404s on another project's resources. Cheapest layer: two-project HTTP integration. Anti-pattern to keep: asserting `get_membership` internals.

**Existing tests.** `test_authentication_roles_and_project_isolation` (`tests/test_api.py:388-420`) — B operator GET A models **404**; A operator GET A models **200**. `test_dataset_reads_are_isolated_and_omit_rejected_inputs` (`:547-597`) — B list `[]`, B GET A's dataset id **404**, B GET A's dataset collection **404**. Revoke isolation in `test_project_account_lifecycle_isolation_and_audit` (`:676+`).

**Gaps to close in Phase 1 (HTTP, status + absence of foreign ids):**

- `GET` model by id (path A vs B, and path B + A's id)
- `POST` register / `POST` publish on foreign project (404, not 403)
- `GET/POST` analysis-runs and `GET` results cross-project / IDOR
- **`POST .../analysis-runs` with a foreign `model_version_id` under own path → 404** (implemented at `main.py:518-520`; promised in archived S-02 manual matrix; **no pytest**)
- Optional: unauthenticated 401 on one register/publish/analyze path (currently asserted mainly on `GET /projects`)

### Risk #2 — Operator register/publish

**Failure path.** First statement in register and publish is `require_project_role(..., {PUBLISHER})` (`src/api/main.py:388`, `:470`). Operator → **403** `"Insufficient project role."` before `admit_uploaded_zip_package` (the only `object_store.put` site in admission) and before `create_model_version` / `publish_model_version`. A 403 cannot insert `eligible` or flip `published` through these handlers.

**Other actors.** Non-member (including Publisher of another project) → **404**. Unauthenticated → **401**. Admin → allowed (bypass).

**UI.** `ModelsView` always renders Register and Publish for `eligible` (`frontend/src/App.tsx:565-619`). Archive S-02 rejected hiding buttons as the security control. Phase 3 owns UI; Phase 1 proof stays on HTTP.

**Guidance vs code.** **Correct**, with one test-gap: “creates no version row” is **not** asserted today. Challenge “UI hide is enough” is already false in the product.

**Existing tests.** Operator ZIP register 403 (`tests/test_api.py:413-420`); Operator publish 403 (`:457-464`). Contrast: ineligible ZIP already uses GET models `== []` (`:926-936`).

**Gaps:** after Operator register 403, `GET .../models == []` (and optionally empty object store); after Operator publish 403, GET still `eligible`. Do not require a frontend test here.

### Risk #3 — Ineligible ZIP / unpublished analysis

**Register.** Multipart `package` ZIP only. After Publisher gate: `admit_uploaded_zip_package`; `report.valid` false → **422** `detail=report.model_dump()` (`src/api/main.py:407-411`). Insert is hardcoded `'eligible'` (`src/api/storage.py:498-503`). Invalid path never reaches insert or object `put`. Schema allows only `eligible` | `published` (`src/api/schemas.py:29-33`). **No `ineligible` row.**

**422 envelopes.** ZIP content failures use `{valid, issues[]}`. Missing `package` file never enters the handler — FastAPI default 422 (S-02 leftover **F6**). Phase 1 must not treat “any 422” as the structured envelope. JSON `package_reference` POST is already status-only (`tests/test_api.py:600-623`).

**503** (validator unavailable) also inserts nothing (`tests/test_api.py:1033-1048`). That is fail-closed availability (Risk #4 / F5), not ineligibility. Do not absorb Torch-in-API into Phase 1.

**Publish.** Only `eligible` → `published` (`src/api/main.py:474-478`). No auto-publish on 201.

**Analysis.** Same-project + `status == published` (`src/api/main.py:517-525`). Eligible unpublished → **409** `"Only published model versions can start analysis."` and no run row. After publish, valid HDFS still terminates `not_supported` (`:574-592`). Publishing does not unlock inference.

**Guidance vs code.** **Correct.** Challenge “201 ⇒ usable” is false in product: 201 means `eligible` only.

**Existing tests.** ZIP 201 declared-files-only (`:909-923`); ineligible 422 + empty list + empty object store (`:926-936`, `:939+`); unpublished analysis 409 + empty runs (`:1069-1095`); published → 202 `not_supported` (`:423-544`). Library ZIP caps live in `tests/test_model_package.py` (not HTTP auth).

**Gaps:** foreign `model_version_id` on analyze → 404 (also listed under #1). Do not snapshot full `issues[].reason` from the validator. Optional: document that missing-file 422 is FastAPI-shaped (F6), without expanding Phase 1 into envelope rewriting.

### Misleading hot-spots and out-of-scope leftovers

- **`src/api/` owns #1–#3.** `src/modules/model_package.py` is ZIP library only. `src/model_validator/` is the isolated Torch probe (Risk #4). `frontend/src` is Risk #6 / Phase 3.
- **F5** (staging 503 without Torch validator), **F7/F8** (Bucket delete errors / leftover prefix on non-409 insert) are Phase 2 (risks #4/#5). Duplicate 409 cleanup is already asserted in the lifecycle test (`tests/test_api.py:444-455`); do not reopen it here.

## Code References

- `src/api/main.py:71-114` — `get_current_user`, `require_project_access`, `require_project_role` (401 / 404 / 403)
- `src/api/main.py:376-440` — ZIP register; Publisher gate before admit/insert
- `src/api/main.py:442-490` — get model + publish; project_id compare; eligible-only publish
- `src/api/main.py:511-525` — analysis: same-project model + published gate
- `src/api/storage.py:498-503` — insert status always `eligible`
- `src/api/storage.py:547-555` — list models `WHERE project_id = ?`
- `src/api/schemas.py:22-33` — roles; model statuses `eligible`/`published` only
- `tests/test_api.py:53-140` — `api` fixture, `_login`, two-project helpers, `_register`
- `tests/test_api.py:388-420` — isolation list 404 + Operator register 403
- `tests/test_api.py:423-544` — Operator publish 403; published analysis `not_supported`
- `tests/test_api.py:547-597` — dataset IDOR / empty foreign list
- `tests/test_api.py:909-936` — ZIP 201 vs ineligible 422 + no row
- `tests/test_api.py:1069-1095` — unpublished analysis 409 + empty runs
- `.github/workflows/verify.yml:28` — CI runs `test_api.py` (and package/object/artifacts) with `-m "not ml"`

## Architecture Insights

- **Two layers:** membership on path `project_id` (hide existence with 404) then **resource ownership** (id belongs to that project). Lists never query without `project_id`.
- **401 vs 404 vs 403:** unauthenticated; not a member / wrong project / missing resource; member with insufficient role. Tests must not collapse 403 and 404.
- **Eligibility is not publication.** 201 is an audited `model.registered` eligible version. Analysis and Select require `published`.
- **Admin is outside the member matrix.** Plans should say so rather than inventing an Admin 403.
- **Oracle:** assert HTTP status plus absence of foreign ids / empty lists / unchanged `eligible`. Do not copy validator `reason` strings or reimplement membership SQL.

## Historical Context (from prior changes)

- `context/archive/2026-09-09-provision-project-accounts/plan.md` — keep 401/403/404; mixed roles across two projects; revoke/deactivate.
- `context/archive/2026-09-09-shared-durable-runtime-state/plan.md` — cross-project dataset GET **404**; 201/202/403/404/409 remain.
- `context/archive/2026-09-10-publish-hdfs-model-package/plan.md` — Publisher ZIP 201; ineligible 422 + empty list; Operator ZIP 403; unpublished analysis 409; published still `not_supported`. Manual: cross-project model id cannot start analysis (**404**) — still untested in pytest.
- `context/archive/2026-09-10-publish-hdfs-model-package/research.md` — UI is a thin client; hiding Register/Publish is not a security control.
- `context/archive/2026-09-10-publish-hdfs-model-package/reviews/impl-review.md` — F6 missing-file 422 envelope (Phase 1: do not conflate); F5/F7/F8 belong to later phases.

## Related Research

- `context/archive/2026-09-10-publish-hdfs-model-package/research.md`
- `context/archive/2026-09-09-provision-project-accounts/` (account 401/403/404)
- `context/archive/2026-09-09-shared-durable-runtime-state/` (dataset isolation)

## Open Questions

None that block `/10x-plan`. Product behavior is settled.

Optional plan notes (not research blockers):

- Whether to assert object-store emptiness after Operator register 403 (defense in depth; handler never calls `put`).
- Whether to add one missing-file 422 assertion that the body is **not** `{valid, issues[]}` (documents F6 without fixing it).

## Test-plan corrections (for a later `/10x-test-plan` backport)

No §2 risk should be dropped. Response guidance for #1–#3 is still right.

- Likelihood for #1–#3 is **`src/api`**, not `src/modules` / `src/model_validator`.
- #2 “no version row” is a **test gap**, not a missing gate.
- #3 has no `ineligible` status; reject means no row.
- Cross-project analyze-by-foreign-model-id is implemented and **untested**.
