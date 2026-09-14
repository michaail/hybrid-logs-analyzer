# Split web control plane by domain Implementation Plan

## Overview

Move HTTP handlers out of [`src/api/main.py`](src/api/main.py) into one FastAPI router per existing OpenAPI tag, then move every screen/dialog out of [`frontend/src/App.tsx`](frontend/src/App.tsx) into `frontend/src/features/<domain>/` with shared primitives in `frontend/src/components/`. Product behavior, URLs, status codes, error details, Banner-on-403 copy, and CSS class names stay the same.

## Current State Analysis

[`src/api/main.py`](src/api/main.py) (~1141 lines) is a factory with **no** `APIRouter`. All 27 routes, nested JWT/RBAC, response mappers, CSP middleware, and SPA mount live in one file. Persistence, admission, and dispatch are already in sibling modules ([`storage.py`](src/api/storage.py), [`validation.py`](src/api/validation.py), [`inference_dispatch.py`](src/api/inference_dispatch.py)).

[`frontend/src/App.tsx`](frontend/src/App.tsx) (~2440 lines) is the entire UI. There is no `components/` directory. [`frontend/src/api.ts`](frontend/src/api.ts) stays unsplit. E2E is already modular.

HTTP tests import only `create_app` from main ([`tests/test_api.py`](tests/test_api.py)). Two tests monkeypatch `src.api.main.dispatch_analysis_run`. Vitest imports `ModelRegistrationDialog`, `PublishModelHarness`, and status helpers from `App.tsx`.

Odd boundary (already decided): `GET /projects/{project_id}/audit-events` is tagged `administration`, not `projects`.

## Desired End State

- `create_app` builds settings/DB/object store, attaches them on `app.state`, includes tagged routers, adds middleware, mounts the SPA **last**, and returns the app.
- `uvicorn src.api.main:create_app --factory` remains the public entry ([`scripts/e2e_serve.py`](scripts/e2e_serve.py), README).
- `App.tsx` is session/project orchestration plus view switching. Screens, dialogs, and primitives live in named modules.
- Existing pytest API suite, Vitest role-deny, and Playwright HDFS publish/deny specs still pass.

### Key Discoveries:

- OpenAPI tags already name the API domains; URL prefix is not the grouping rule for project-scoped audit.
- `require_project_access` / `require_project_role` are ordinary functions, not FastAPI `Depends`.
- Analysis tests monkeypatch `src.api.main.dispatch_analysis_run` and must follow the router import.
- `App.tsx` uses a module-level `ApiClient`; feature modules must share that instance.

## What We're NOT Doing

- Splitting [`src/api/storage.py`](src/api/storage.py), [`tests/test_api.py`](tests/test_api.py) (except monkeypatch + OpenAPI tag assertions), [`frontend/src/api.ts`](frontend/src/api.ts), or [`frontend/src/styles.css`](frontend/src/styles.css)
- New endpoints, datasets, React Router, CSS modules, or a file-length linter/Cursor rule
- Moving authorization into the browser
- Touching pipeline/notebook/inference-service god files
- Shipping `PublishModelHarness` as a production component

## Implementation Approach

API first, then frontend. Each side extracts shared infrastructure before moving the leaf handlers/screens so `create_app` / `App` keep working after every phase.

Authz invariants to preserve: missing membership → 404; wrong role → 403 `"Insufficient project role."`; Publisher satisfies Operator; control plane never deserializes `.pt`.

Admission order on register/upload stays: validate → write objects → create DB row last → delete prefix on failure (lessons.md).

## Critical Implementation Details

Routers must not close over `create_app` locals. Put `database`, `object_store`, and `settings` on `app.state` and read them in [`src/api/deps.py`](src/api/deps.py). `require_project_access` / `require_project_role` stay ordinary functions.

After analysis routes move, patch `src.api.routers.analysis.dispatch_analysis_run` (or whatever import the analysis router uses). Patching `src.api.main.dispatch_analysis_run` will no longer intercept the handler.

SPA catch-all must remain the last registered GET and must still refuse `admin/`, `auth/`, `health`, `projects/`, `users/` prefixes so API 404s are not masked.

Feature modules must share **one** `ApiClient` instance. Add a tiny [`frontend/src/session.ts`](frontend/src/session.ts) singleton; do not instantiate a second client inside a feature. Do not split `api.ts`.

Keep CSS class names unchanged so the unsplit stylesheet still applies.

Keep handler function names (`login`, `register_model_version`, `get_analysis_results`, …) so OpenAPI operationIds stay stable.

## Phase 1: API shared surface

### Overview

Extract identity, HTTP helpers, mappers, middleware, and SPA mount. Routes still decorate `app` inside `create_app` so the HTTP suite stays green before any path moves.

### Changes Required:

#### 1. Deps and identity

**File**: `src/api/deps.py` (new), `src/api/main.py`

**Intent**: Lift `CurrentUser`, `HTTPBearer`, `get_current_user`, `require_administrator`, `require_project_access`, `require_project_role`, and unauthorized / not-found helpers out of the factory.

**Contract**: Same 401 (`Authentication required.` + `WWW-Authenticate: Bearer`), 403, and membership-miss 404 behavior. `create_app` assigns `app.state.database` / `object_store` / `settings` even while routes still live in main.

#### 2. Response mappers

**File**: `src/api/responses.py` (new)

**Intent**: Move row → Pydantic helpers (`_user_response` through `_audit_response`, `_stored_results_summary`, `_NOT_IN_REFERENCE_CATALOG_REASON`).

**Contract**: Public mapper names can drop the leading underscore; output schemas unchanged.

#### 3. Middleware and SPA

**File**: `src/api/middleware.py` (new), `src/api/frontend_mount.py` (new)

**Intent**: CSP / nosniff / frame headers stay a single middleware; docs paths still skip CSP.

**Contract**: Header set and `/docs` `/openapi.json` `/redoc` exceptions unchanged.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py` passes (Torch-free; use a normal terminal if the sandbox hits SHM limits)
- `ruff check src/api tests/test_api.py`
- `mypy` on touched API modules

#### Manual Verification:

- `GET /health` and `GET /openapi.json` still work via `create_app`

---

## Phase 2: API domain routers

### Overview

One `APIRouter` per existing OpenAPI tag. `create_app` becomes settings → state → middleware → `include_router` → SPA mount.

### Changes Required:

#### 1. Router package

**File**: `src/api/routers/{health,authentication,users,administration,projects,models,analysis,datasets}.py`

**Intent**: Move handlers by **tag**, not URL prefix.

**Contract**: Freeze the OpenAPI tag map below. Keep each route's `tags=[...]`, `response_model`, status codes, and multipart shapes.

- `health`: `GET /health`
- `authentication`: `POST /auth/token`
- `users`: `GET /users/me`
- `administration`: `POST /admin/project-accounts`, `GET /admin/users`, `PATCH /admin/users/{user_id}/activation`, `GET /admin/audit-events`, `GET /projects/{project_id}/audit-events`
- `projects`: `GET|POST /projects`, members list/grant/patch/delete
- `models`: list, register (multipart), get, publish
- `analysis`: list, create (202 + `BackgroundTasks`), get run, results, provisional-results
- `datasets`: list, upload (multipart), get

#### 2. Thin factory

**File**: `src/api/main.py`

**Intent**: Factory only: construct resources, include routers, middleware, mount frontend last.

**Contract**: `from src.api.main import create_app` remains the only app import for tests and `scripts/e2e_serve.py`.

#### 3. Dispatch monkeypatch

**File**: `tests/test_api.py`

**Intent**: Retarget the two `dispatch_analysis_run` monkeypatches to the analysis router import path. Add path → methods → tags snapshot coverage if the existing OpenAPI test does not already assert tags.

**Contract**: Patch `src.api.routers.analysis.dispatch_analysis_run`.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py`
- OpenAPI JSON: same paths/methods/tags as the map above; still no `/register` `/signup` `/auth/register`
- `ruff check` + `mypy` on `src/api` and `tests/test_api.py`

#### Manual Verification:

- Interactive `/docs` lists the same eight tags
- SPA fallback still serves `frontend/dist` when present and does not swallow `/projects/...` 404s

---

## Phase 3: Frontend shared UI

### Overview

Pull reusable primitives and formatters out of `App.tsx` without moving screens yet.

### Changes Required:

#### 1. Components and formatters

**File**: `frontend/src/components/` (`Banner`, `Dialog`, `EmptyState`, `StatusBadge`, `MetricList`, `SummaryMetric`, `LoadingScreen`, `NavigationButton`, `NoProjectState`), `frontend/src/lib/format.ts`

**Intent**: Shared chrome and date/metric/id helpers become importable. `Banner` stays `role="alert"` for 403 copy.

**Contract**: Same props, same CSS class names. `App.tsx` only changes imports.

#### 2. Session singleton (prep)

**File**: `frontend/src/session.ts` (new)

**Intent**: Hold `tokenStorageKey` and the single `ApiClient` instance so Phase 4 screens do not fork clients.

**Contract**: Token still sessionStorage-only; no new persistence.

### Success Criteria:

#### Automated Verification:

- `npm --prefix frontend run typecheck`
- `npm --prefix frontend run lint`
- `npm --prefix frontend run test`

#### Manual Verification:

- Dev UI still looks and behaves the same (classes unchanged)

---

## Phase 4: Frontend feature screens

### Overview

Move every screen/dialog into `frontend/src/features/<domain>/`. `App.tsx` is shell + wiring. Relocate the Vitest harness into the test file. Playwright is the phase gate.

### Changes Required:

#### 1. Feature modules

**File**: `frontend/src/features/auth/LoginScreen.tsx`, `frontend/src/features/models/`, `frontend/src/features/runs/`, `frontend/src/features/results/`, `frontend/src/features/admin/`

**Intent**: Domain UI lives next to its API usage. Shell keeps the `useState` orchestration and view switch (`models` | `runs` | `administration`).

**Contract**: Operator still sees Register/Publish; 403 still renders `Banner` with API detail, not a hidden button. 401 still ends the session in the shell. Results vs provisional inspection UX unchanged.

#### 2. Shell and tests

**File**: `frontend/src/App.tsx`, `frontend/src/App.role-deny.test.tsx`

**Intent**: Default-export `App` only from `App.tsx`. Move `PublishModelHarness` into the Vitest file (or a test-only helper). Point Vitest imports at the models feature + harness in the test file.

**Contract**: Both role-deny tests still assert `role="alert"` contains `Insufficient project role.` and no success `role="status"`.

### Success Criteria:

#### Automated Verification:

- `npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend run test`
- `npm --prefix frontend run test:e2e` (existing HDFS publish + ineligible + operator-denied specs)

#### Manual Verification:

- Walk login → project → register/publish → dataset → run → results/provisional → administration; notices and 403 banners still match today

---

## Testing Strategy

### Unit Tests:

- Existing Vitest Register/Publish 403 Banner tests, retargeted to feature modules
- OpenAPI path/method/tag snapshot next to the existing administration OpenAPI test

### Integration Tests:

- Existing `tests/test_api.py` HTTP characterization suite (not split)
- Playwright HDFS publish, ineligible, and operator-denied specs as the Phase 4 gate

### Manual Testing Steps:

1. `GET /health` and `GET /openapi.json` through `create_app`
2. Confirm `/docs` still lists the eight OpenAPI tags
3. Confirm SPA fallback does not swallow `/projects/...` 404s
4. Walk the HDFS operator/publisher/admin UI path after the screen split

## Migration Notes

No data migration. Rollback is revert of the git commits per phase. Deploy entrypoint unchanged; Docker/Compose still call `create_app --factory`.

## References

- Thin-client / control-plane: `context/foundation/tech-stack.md`
- App.tsx monolith testing caveat: archived `testing-frontend-role-signals`
- Admission rollback: `context/foundation/lessons.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: API shared surface

#### Automated

- [x] 1.1 python -m pytest tests/test_api.py passes — 3aa8cdb
- [x] 1.2 ruff check src/api tests/test_api.py — 3aa8cdb
- [x] 1.3 mypy on touched API modules — 3aa8cdb

#### Manual

- [x] 1.4 GET /health and GET /openapi.json still work via create_app — 3aa8cdb

### Phase 2: API domain routers

#### Automated

- [x] 2.1 python -m pytest tests/test_api.py — 3aa8cdb
- [x] 2.2 OpenAPI JSON: same paths/methods/tags as the map above; still no /register /signup /auth/register — 3aa8cdb
- [x] 2.3 ruff check + mypy on src/api and tests/test_api.py — 3aa8cdb

#### Manual

- [x] 2.4 Interactive /docs lists the same eight tags — 3aa8cdb
- [x] 2.5 SPA fallback still serves frontend/dist when present and does not swallow /projects/... 404s — 3aa8cdb

### Phase 3: Frontend shared UI

#### Automated

- [x] 3.1 npm --prefix frontend run typecheck — 3aa8cdb
- [x] 3.2 npm --prefix frontend run lint — 3aa8cdb
- [x] 3.3 npm --prefix frontend run test — 3aa8cdb

#### Manual

- [x] 3.4 Dev UI still looks and behaves the same (classes unchanged) — 3aa8cdb

### Phase 4: Frontend feature screens

#### Automated

- [x] 4.1 npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend run test — 3aa8cdb
- [x] 4.2 npm --prefix frontend run test:e2e (existing HDFS publish + ineligible + operator-denied specs) — 3aa8cdb

#### Manual

- [x] 4.3 Walk login → project → register/publish → dataset → run → results/provisional → administration; notices and 403 banners still match today — 3aa8cdb
