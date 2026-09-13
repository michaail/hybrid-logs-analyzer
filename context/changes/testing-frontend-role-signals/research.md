---
date: 2026-09-14T01:19:02+02:00
researcher: michalklos
git_commit: f7070f405dce549f73886d1895270414c94801de
branch: feature/test-plan-refresh
repository: hybrid-logs-analyzer
topic: "Ground rollout Phase 3: frontend role signals (risk #6)"
tags: [research, codebase, frontend, react, fastapi, role-signals, component-tests]
status: complete
last_updated: 2026-09-14
last_updated_by: michalklos
---

# Research: Ground rollout Phase 3: frontend role signals (risk #6)

**Date**: 2026-09-14T01:19:02+02:00
**Researcher**: michalklos
**Git Commit**: f7070f405dce549f73886d1895270414c94801de
**Branch**: feature/test-plan-refresh
**Repository**: hybrid-logs-analyzer

## Research Question

Ground rollout Phase 3 of `context/foundation/test-plan.md` ("Frontend role signals").

Risk to verify:

- **#6:** The UI shows Register/Publish/Select as available or successful when the API would deny the action. Challenge: a disabled button means the client will not send the request. Avoid: browser e2e because it “feels safer”; screenshot snapshots.

For this risk: ground the live failure path, verify or correct the test-plan response guidance, locate existing tests, name the cheapest useful layer, and flag speculative risks or misleading hot-spot evidence.

## Summary

Risk #6 is a **real leftover**, not speculative. HTTP Operator deny is already proven (Phase 1). The SPA still offers Register and Publish to every project user, fires those requests, and has **no current-user project role** on `/users/me`. Success banners for register/publish/queue wait for the awaited 2xx. Select is **not an API**; it is local React state gated on `published`, not on role.

Response guidance is **half-right**:

- **Keep** “success copy only after an allowed 2xx” and “component tests with a fake API.”
- **Correct** “denied actions stay denied in the UI” — availability is not denied; only the success Banner is. S-02 deliberately left buttons visible.
- **Confirm** the must-challenge: a disabled Select does not fetch, but that gate is **lifecycle** (unpublished), not Operator deny. Do not treat disabled Select as the #6 oracle.
- **Do not** add Playwright Operator specs; existing e2e is Publisher publication only.
- **Cite, do not rewrite** Operator HTTP 403 tests.

Cheapest useful layer: **bootstrap Vitest + Testing Library** (no runner today) and drive `ModelsView` / register dialog / publish handler with a fake `ApiClient`. Assert: 403 shows Banner/`Insufficient project role.`, success Banner absent, `registerModel`/`publishModel` were called. Do not invent client-side role hiding as a security control (S-02 / risk #2).

`frontend/src` hot-spot churn is **partly misleading**: later slices added analysis-results UI. The failure for #6 still lives in `frontend/src/App.tsx` ModelsView + `api.ts` User shape.

## Detailed Findings

### SPA does not know operator vs publisher

`GET /users/me` maps to `User` with `is_administrator` only (`frontend/src/api.ts:12-17`, `:251-252`). Sidebar shows `"Administrator"` vs `"Project user"` (`frontend/src/App.tsx:350`). `Membership.role` exists (`frontend/src/api.ts:32-38`) but is loaded only for the Administration view (`frontend/src/App.tsx:154-161`). It is never passed into `ModelsView`.

Therefore the SPA **cannot** hide Register/Publish by project role without a product change (new field on `/users/me`, or a membership self-read). S-02 forbade inventing client-side role hiding as the security control.

### Register, Publish, and Select are three distinct controls

All three render in `ModelsView` (`frontend/src/App.tsx:567-655`):

| Control | Gate in UI | Network |
|---------|------------|---------|
| **Register trained model** | Always shown (`:591-593`); dialog submit (`:1319`) | `POST /projects/{id}/models` (`frontend/src/api.ts:267-284`) |
| **Publish version** | Shown when `status === "eligible"` (`:651-654`); no role check | `POST /projects/{id}/models/{id}/publish` (`:287-290`) |
| **Select model** | `disabled={!isPublished}` (`:643-649`) | **None** — `onSelectModel` is `setSelectedModelId` (`:40`, `:388`) |

Start analysis is a fourth action (`POST /projects/{id}/analysis-runs`, `frontend/src/api.ts:297-301`). Operators **are allowed** that route (`src/api/main.py` `require_project_role(..., {OPERATOR})`). Select merely feeds `model_version_id` into that POST.

Phase 3 goal “unauthorized publish or select” overloads **Select**. An Operator selecting a published model is allowed. The unauthorized analog is Register/Publish, not Select.

### Success copy waits for 2xx; 403 is shown, not ignored

Publish (`frontend/src/App.tsx:227-238`): `await api.publishModel` then `setNotice("… is now published.")`. Catch → `handleRequestError` → `pageError` Banner (`:377-378`).

Register (`:241-250`): success notice only after `await api.registerModel`. The dialog catches (`:1270-1274`) and shows a dialog Banner (`:1291`). App-level `registerModel` does not catch, so 403 stays in the dialog.

`handleRequestError` special-cases **401** (end session) and otherwise `setPageError(messageFor(error))` (`:219-225`). `ApiError` text comes from JSON `detail` (`frontend/src/api.ts:419-421`, `:481-512`). Operator 403 detail is `"Insufficient project role."` (`src/api/main.py:137-138`). Non-members get **404** `"Project was not found."` via `require_project_access` (`:117-125`), not 403.

There are no toasts. Success is `Banner tone="success"` (`App.tsx:377`).

### Disabled-button challenge is real — and easy to misuse

A disabled Select does not fire `onClick` (native `disabled`). That matches the must-challenge **for unpublished models**, not for Operators. Register and Publish stay **enabled** for Operators and **do send** fetch. A test that only clicks a disabled Select proves nothing about role.

### API contract the SPA actually hits

`require_project_role` (`src/api/main.py:127-138`): admin bypass; Publisher may use Operator-gated routes; otherwise **403** `"Insufficient project role."`

| SPA call | Operator | Non-member | Unauthenticated |
|----------|----------|------------|-----------------|
| `GET .../models` | 200 | 404 | 401 |
| `POST .../models` | **403** | 404 | 401 |
| `POST .../publish` | **403** | 404 | 401 |
| `POST .../analysis-runs` | allowed (202 if published + ready) | 404 | 401 |

The SPA calls **both** Operator-allowed list/start-analysis and Operator-denied register/publish. Empty-state copy says “A Publisher can upload…” (`App.tsx:599`) while the Register button remains for all project users.

### Existing tests to cite, not rewrite

HTTP (Phase 1):

- `test_authentication_roles_and_project_isolation` (`tests/test_api.py:435`) — Operator ZIP register **403** then list (`:461-476`).
- `test_model_publication_and_safe_analysis_run_lifecycle` (`tests/test_api.py:655`) — Operator publish **403**, still `eligible` (`:691-705`).

Playwright (Publisher only; **not** #6):

- `frontend/e2e/seed.spec.ts` — eligible register.
- `frontend/e2e/publish-eligible-hdfs-model.spec.ts` — publish success.
- `frontend/e2e/reject-ineligible-hdfs-model.spec.ts` — ineligible 422.

Default e2e role is publisher (`frontend/e2e/fixtures.ts`). Setup provisions a project-B operator; **no spec** uses that role for deny.

### Test stack: §4 is accurate

`frontend/package.json:6-31` has Vite/React 18, Playwright, no vitest/jest/RTL. Scripts: `dev`/`build`/`lint`/`typecheck`/`test:e2e*`. CI `frontend` job is `npm run build` only; `e2e` runs Playwright. No component-test job.

Cheapest layer for #6: add Vitest + Testing Library + jsdom (or happy-dom), fake `ApiClient`, assert Banner/error and that success notice is absent on 403. Do not add an Operator Playwright spec (anti-pattern in §2; §6.7 / §7).

Phase 4 in §3 is already `complete`. §5 still says frontend component tests are required after Phase 3 — wiring a new `npm test` CI step belongs in **this** phase’s cookbook, not a rewrite of the frozen Phase 4 row.

## Code References

- `frontend/src/api.ts:12-17` — `User` has `is_administrator`, no project role
- `frontend/src/api.ts:267-301` — register / publish / startAnalysis HTTP
- `frontend/src/api.ts:411-421`, `:481-512` — fetch; non-OK → `ApiError` from `detail`
- `frontend/src/App.tsx:219-238` — 401 vs page Banner; publish success after 2xx
- `frontend/src/App.tsx:241-250` — register success notice after 2xx
- `frontend/src/App.tsx:350` — identity is admin vs “Project user”
- `frontend/src/App.tsx:377-378` — success vs error Banners
- `frontend/src/App.tsx:591-655` — Register always; Select disabled unless published; Publish if eligible
- `frontend/src/App.tsx:1270-1291` — register dialog catches and shows Banner
- `src/api/main.py:96-138` — bearer 401; membership 404; role 403
- `src/api/main.py:419`, `:529` — register/publish require `PUBLISHER`
- `tests/test_api.py:461-476`, `:691-705` — Operator 403 oracles
- `frontend/package.json:6-31` — no component runner

## Architecture Insights

- **Thin client, server enforcement.** Register/Publish remaining visible is an intentional S-02 product decision, not an unfinished hide-the-button task. Phase 3 should prove **error vs success copy** and **request still fires**, not that Operators cannot see the buttons — unless the team explicitly reopens that UX.
- **Select ≠ authorize.** Published-only Select is a lifecycle gate (risk #3 adjacency). Role deny for “use this model” is Start analysis, which Operators may do.
- **Fake API is the independent oracle.** Asserting `disabled` on Select copies production branching. Asserting “Banner shows `Insufficient project role.` and notice is unset after a 403 stub” does not.
- **Cost × signal.** One RTL test of ModelsView + dialog with a stubbed `publishModel`/`registerModel` rejection beats a new Playwright Operator login flow.

## Historical Context (from prior changes)

- `context/archive/2026-09-10-publish-hdfs-model-package/research.md` — UI is a thin client; Operators see Register/Publish; API 403 is the control.
- `context/archive/2026-09-10-publish-hdfs-model-package/plan.md` — hiding buttons out of scope; “do not invent client-side role hiding.”
- `context/archive/2026-09-10-testing-critical-path-api-isolation/research.md` — risk #2 challenge; Phase 3 owns UI copy; Phase 1 HTTP-only.
- `context/archive/2026-09-10-testing-critical-path-api-isolation/plan.md` — excludes risk #6; success check: no UI hide added.
- `context/archive/2026-09-13-test-plan-refresh-2026-09-13/plan.md` — Playwright publication specs do not prove unauthorized-role UI; no component runner.
- `context/archive/2026-09-12-inspect-hdfs-analysis-results/` and `.../separate-provisional-hdfs-results/` — later `frontend/src` churn is results UI, not Models Register/Publish.

## Related Research

- `context/archive/2026-09-10-testing-critical-path-api-isolation/research.md` — Phase 1 isolation; defers this phase
- `context/archive/2026-09-10-publish-hdfs-model-package/research.md` — S-02 admission UI + 403
- `context/archive/2026-09-09-trusted-model-package-contract/plan.md` — first thin Register/Publish UI

## Open Questions

1. Should Phase 3 **only** prove 403 Banner + no success copy (buttons stay visible, matching S-02), or also add a current-user role to `/users/me` so the UI can hide Publisher actions? Recommendation: first option unless product wants the UX change; hiding is still not the security control.
2. Should the plan treat **Select** as in-scope? Recommendation: no as an API deny. Cover “Selected for analysis” as local state only if needed to stop agents from writing a fake select 403. Optional: Start analysis success copy after 2xx (Operator-allowed, not #6).
3. Does bootstrapping Vitest belong entirely in this change, including a CI `npm test` step, even though §3 Phase 4 is already `complete`? Recommendation: yes for the runner + one deny test; document the gate in §6.3; do not reopen Phase 4’s row.

## Backport notes for `/10x-test-plan`

- Risk #6 Source (`frontend/src`, interview Q4, sparse suite) is still the right **directory**; churn counts mix analysis-results work. No file:line belongs in §2.
- Response guidance should distinguish **availability** (buttons remain, requests fire) from **success copy** (Banner only after 2xx). Context needed: SPA `/users/me` has no project role; Select is local state.
- Must-challenge stands. Anti-pattern (Playwright / snapshots) stands. Likely cheapest layer stands once a runner is bootstrapped.
- No speculative-risk drop.
