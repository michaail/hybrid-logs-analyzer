# Frontend role signals Implementation Plan

## Overview

Prove an Operator cannot look like a successful Register or Publish:
component tests with a fake API, plus a same-project Operator Playwright
spec that asserts the error Banner only. Buttons stay visible. Select
stays out of role-deny scope.

## Current State Analysis

Research (`context/changes/testing-frontend-role-signals/research.md`)
is the baseline. There is no frame brief.

`ModelsView` always shows Register and Publish-when-eligible
(`frontend/src/App.tsx:591-655`). `/users/me` has `is_administrator`
only (`frontend/src/api.ts:12-17`). Operator `POST .../models` and
`POST .../publish` are **403** `"Insufficient project role."`
(`src/api/main.py:127-138`, `:419`, `:529`). Success Banners run only
after awaited 2xx (`App.tsx:227-250`). Error Banner uses `role="alert"`;
success uses `role="status"` (`App.tsx:2121-2131`). Register 403 is
caught in `ModelRegistrationDialog` (`:1270-1291`); publish 403 is
caught in `App.publishModel` (`:227-238`).

Select is local `setSelectedModelId`, disabled unless `published`.
Start analysis is Operator-allowed. HTTP oracles already exist
(`tests/test_api.py:461-476`, `:691-705`). Playwright specs are
Publisher-only. `E2ERole` is `"publisher" | "project-b-user"`
(`frontend/e2e/helpers/accounts.ts:17`). Project-B is an Operator on
**B**, so using that token on A is **404**, not 403. No Vitest/RTL.
Verify `frontend` job is `npm run build` only.

S-02 left buttons visible on purpose. This change does not hide them.

## Desired End State

- A fake-API component test: Register and Publish still invoke the
  stub; 403 shows `Insufficient project role.`; success Banner is
  absent.
- A same-project Operator Playwright spec: click Register and/or
  Publish; `role="alert"` shows that detail; no `role="status"` success
  copy. Pytest remains the no-row / still-eligible oracle.
- Vitest runs in the existing Verify `frontend` job. §6.3 names the
  new tests and the HTTP citations. §3 Phase 4 is not reopened.

### Key Discoveries:

- Publish 403 Banner lives in `App`, not `ModelsView`. Export a
  harness that includes Banner + the publish try/catch, not only the
  card button (`frontend/src/App.tsx:227-238`, `:567-655`).
- Register 403 Banner lives in `ModelRegistrationDialog` (`:1248-1291`).
- `project-b-user` is the wrong actor for risk #6 (`auth.setup.ts:25-32`).
- User overrode cheapest-layer-only: Playwright is in scope as a
  Banner oracle, not a persistence oracle (`.cursor/rules/40-e2e.mdc`).

## What We're NOT Doing

- Hiding Register/Publish by role, or adding project role to `/users/me`.
- Treating disabled Select as the Operator-deny oracle.
- Rewriting HTTP 403 tests or Publisher publication specs.
- Playwright that re-checks models list empty / still eligible.
- Screenshot snapshots as the oracle.
- Analysis, intake, or cross-project (Test C) E2E.
- Reopening §3 Phase 4. Do not edit §1–§2 (already backported).
- Torch, `@ml`, Python lockfile, notebooks, BGL.

## Implementation Approach

Bootstrap Vitest so the independent UI oracle is cheap, then add a
same-project Operator browser spec that only checks Banner copy, then
wire `npm test` into the existing frontend CI job and fill §6.3.

## Critical Implementation Details

Register 403 appears on the **dialog** alert; publish 403 appears on
the **page** alert. Do not assert the wrong Banner. Seed the Playwright
publish case with a Publisher-created eligible version (UI or API),
then restore the Operator token — do not use `project-b-user` for 403.

## Phase 1: Vitest runner and 403 component tests

### Overview

Add a component runner and prove Register/Publish deny copy against a
fake API.

**Behavior asserted:** stub `registerModel` / `publishModel` reject
with `ApiError` 403 `"Insufficient project role."`; alert shows that
text; success status Banner is absent; the stub was called.

**Regression caught:** success copy rendered on reject, or tests that
never call the stub (disabled-button theater).

**Research source:** `research.md` SPA Banner vs 2xx; `App.tsx:227-250`.

**Edge/error/boundary:** dialog vs page Banner; 401 still must not be
treated as the 403 oracle.

**Anti-pattern avoided:** Playwright in this phase; asserting Select
`disabled`; hiding buttons.

### Changes Required:

#### 1. Vitest + Testing Library

**File**: `frontend/package.json`, `frontend/package-lock.json`,
`frontend/vite.config.ts` (or `frontend/vitest.config.ts`)

**Intent**: Add a Vite-native unit runner with React Testing Library
and a DOM environment so Phase 1 tests run without Chromium.

**Contract**: Script `test` (e.g. `vitest run`). React 18 + Vite 6
compatible `vitest`, `@testing-library/react`, `@testing-library/user-event`,
`jsdom` or `happy-dom`. Include `*.test.ts(x)` under `frontend/src/`.
Do not add Playwright deps.

#### 2. Export Register/Publish deny surfaces

**File**: `frontend/src/App.tsx`

**Intent**: Make the Register dialog and the Publish path (including
page Banner + notice sequencing) importable so tests do not mount the
whole shell.

**Contract**: Named-export `ModelRegistrationDialog`. For publish,
export a small harness (or the existing `Banner` plus the same
try/catch/notice sequencing `App.publishModel` uses). `ModelsView`
alone is not enough for publish 403. Keep default `App` export. Do not
add client-side role hiding.

#### 3. Fake-API deny tests

**File**: `frontend/src/` (new `*.test.tsx` next to the harness)

**Intent**: Drive Register and Publish with a stub that throws
`ApiError(403, "Insufficient project role.")`.

**Contract**: Torch-free. Assert `role="alert"` text, no
`role="status"` success copy (`was registered as eligible` /
`is now published`), and that the stub was invoked. Use
`frontend/src/api.ts` `ApiError`. Do not mock `fetch` so cleanup
never runs — there is no object store here; stub the client methods.

### Success Criteria:

#### Automated Verification:

- `npm --prefix frontend test` passes, including Register and Publish
  403 tests
- `npm --prefix frontend run typecheck` and `npm --prefix frontend run lint`
  pass

#### Manual Verification:

- Confirm tests stub `registerModel`/`publishModel` (or equivalent),
  assert alert + no success status, and do not treat Select disabled as
  the oracle

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Same-project Operator Playwright spec

### Overview

Prove the real shell shows the 403 alert for a same-project Operator.

**Behavior asserted:** Operator clicks Register and Publish; alert
shows `Insufficient project role.`; no success status copy.

**Regression caught:** UI claims registered/published while the API
returned 403.

**Research source:** `research.md` actor matrix; `40-e2e.mdc`.

**Edge/error/boundary:** same-project 403 vs project-B 404; dialog
alert vs page alert.

**Anti-pattern avoided:** screenshots as oracle; re-checking empty
model list; using `project-b-user` as the 403 actor.

### Changes Required:

#### 1. Provision Operator on project A

**File**: `scripts/e2e_serve.py`, `frontend/e2e/helpers/accounts.ts`,
`frontend/e2e/auth.setup.ts`, `frontend/e2e/fixtures.ts`

**Intent**: Seed and restore a same-project Operator token the way
Publisher is restored today.

**Contract**: Extend `E2ERole` (e.g. `"operator"`). Add credentials
alongside `publisherA` in `accounts.json`. `ensureProjectAccount` on
project A with role `"operator"`. `writeAuthToken` / fixture `role`
option. Keep `project-b-user` unchanged. Do not log in through the UI
inside the deny spec (`40-e2e.mdc`).

#### 2. Banner-only deny spec

**File**: `frontend/e2e/` (new spec; reuse `helpers/publication.ts`
locators)

**Intent**: After a Publisher-created eligible version (and for
Register, an eligible ZIP), act as Operator, click, wait for the POST,
assert alert and no success status.

**Contract**: `getByRole('alert')` / `getByRole('status')` — no CSS
oracles, no screenshot oracles. `waitForResponse` on register/publish
POST. Do not assert models list `[]` or still-`eligible` (pytest).
Publisher publication specs stay untouched. Unique package identity
(`helpers/packages.ts`). Harmless ZIP via `e2e_package.py`.

### Success Criteria:

#### Automated Verification:

- `npm --prefix frontend run test:e2e` passes, including the new
  Operator deny spec and existing Publisher specs

#### Manual Verification:

- Confirm the spec uses a same-project Operator token, asserts Banner
  copy only, and does not use `project-b-user` or screenshots as the
  oracle

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Phase 3: CI and cookbook

### Overview

Lock the new tests into the existing frontend CI job and record how to
add the next role-signal test.

**Behavior asserted:** §6.3 names the Vitest functions and the
Playwright spec; HTTP 403 tests stay cited; Select is local state;
Phase 4 row stays `complete`.

**Regression caught:** a later UI change ships with HTTP 403 only.

**Research source:** this change’s Phase 1–2 tests; test-plan §6.3, §4.

**Anti-pattern avoided:** file:line in §2; claiming Publisher E2E
proves Operator deny; reopening Phase 4.

### Changes Required:

#### 1. Verify frontend job runs unit tests

**File**: `.github/workflows/verify.yml`

**Intent**: Run `npm test` on the existing `frontend` job before or
after build so deny-copy tests gate PRs.

**Contract**: Same Node 22 / `frontend/` defaults. Do not add a fourth
job. Do not change `python`, `inference`, or `e2e` jobs. Do not mark
§3 Phase 4 incomplete.

#### 2. Update test-plan cookbook and stack

**File**: `context/foundation/test-plan.md`

**Intent**: Fill §6.3; name new tests; cite HTTP oracles; note Select
is not a role 403; bump header Last updated; set §3 Phase 3 Status
`complete`.

**Contract**:

- **§3 Phase 3** — Status `complete`; Change folder remains
  `testing-frontend-role-signals`. Goal line unchanged.
- **§4** — frontend unit row: Vitest + RTL (versions as installed);
  note Verify `frontend` runs `npm test`. Do not rewrite Playwright
  publication notes.
- **§6.3** — How to add a component deny test (fake `ApiError` 403,
  alert + no success status, stub called). Name the new test file /
  functions. Keep the two Publisher e2e names as **not** the HTTP
  isolation oracle; add the Operator Banner spec as the shell check.
  Cite `test_authentication_roles_and_project_isolation` and
  `test_model_publication_and_safe_analysis_run_lifecycle`. One
  sentence: Select is published-only local state; do not assert
  `disabled` as Operator deny. Buttons stay visible.
- **§6.6** — Short 2026-09-14 note for this rollout.
- **§6.7** — Mention the Operator Banner spec as Banner-only; do not
  turn it into Test C or analysis E2E.
- Do not edit §1–§2. Do not add file:line to §2.

### Success Criteria:

#### Automated Verification:

- `context/foundation/test-plan.md` §6.3 no longer reads TBD for
  denied Register/Publish copy
- `npm --prefix frontend test` still passes

#### Manual Verification:

- Read §6.3–§6.7: HTTP 403 tests still cited; Select is explicit;
  Operator Playwright is Banner-only; Phase 3 ledger row is `complete`;
  Phase 4 still `complete`

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- Register dialog 403 → dialog alert, stub called, no success status.
- Publish harness 403 → page alert, stub called, no success status.

### Integration Tests:

- Cite existing Operator HTTP 403 tests; do not rewrite.
- Playwright: same-project Operator Banner-only (Phase 2).

### Manual Testing Steps:

1. Skim component tests: fake API, alert, stub called, no Select oracle.
2. Skim Operator spec: role token is project A Operator; Banner only.
3. Read §6.3: leftover “hide the button” is not the recipe.

## Performance Considerations

None. Vitest is local/CI Node. One extra Playwright spec on the
existing Chromium job.

## Migration Notes

Not applicable. No schema change. E2E accounts gain a same-project
Operator; isolated `.e2e/` DB is wiped each suite start.

## References

- Research: `context/changes/testing-frontend-role-signals/research.md`
- Test plan: `context/foundation/test-plan.md` §3 Phase 3, §6.3, risk #6
- E2E rules: `.cursor/rules/40-e2e.mdc`
- HTTP oracles: `tests/test_api.py` Operator register/publish 403
- Similar publication helpers: `frontend/e2e/helpers/publication.ts`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Vitest runner and 403 component tests

#### Automated

- [x] 1.1 `npm --prefix frontend test` passes, including Register and Publish 403 tests — feca89c
- [x] 1.2 `npm --prefix frontend run typecheck` and `npm --prefix frontend run lint` pass — feca89c

#### Manual

- [x] 1.3 Confirm tests stub `registerModel`/`publishModel` (or equivalent), assert alert + no success status, and do not treat Select disabled as the oracle — feca89c

### Phase 2: Same-project Operator Playwright spec

#### Automated

- [x] 2.1 `npm --prefix frontend run test:e2e` passes, including the new Operator deny spec and existing Publisher specs — 6b3b4d4

#### Manual

- [x] 2.2 Confirm the spec uses a same-project Operator token, asserts Banner copy only, and does not use `project-b-user` or screenshots as the oracle — 6b3b4d4

### Phase 3: CI and cookbook

#### Automated

- [x] 3.1 `context/foundation/test-plan.md` §6.3 no longer reads TBD for denied Register/Publish copy
- [x] 3.2 `npm --prefix frontend test` still passes

#### Manual

- [x] 3.3 Read §6.3–§6.7: HTTP 403 tests still cited; Select is explicit; Operator Playwright is Banner-only; Phase 3 ledger row is `complete`; Phase 4 still `complete`
