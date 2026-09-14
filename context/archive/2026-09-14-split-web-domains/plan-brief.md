# Split web control plane by domain — Plan Brief

> Full plan: `context/changes/split-web-domains/plan.md`

## What & Why

`src/api/main.py` and `frontend/src/App.tsx` mix every domain in one file.
This change splits HTTP handlers by existing OpenAPI tags and UI screens by
feature so later HDFS work can land in the owning module without growing the
monoliths. Product behavior stays the same.

## Starting Point

`create_app` owns all 27 routes, nested JWT/RBAC, mappers, CSP middleware, and
SPA mount. `App.tsx` owns the shell, every screen/dialog, primitives, and
format helpers. `api.ts`, `styles.css`, `storage.py`, and `test_api.py` stay.

## Desired End State

`create_app` is a thin factory: state, middleware, tagged routers, SPA last.
`App.tsx` is session/project wiring. Screens live under
`frontend/src/features/<domain>/`; primitives under `frontend/src/components/`.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| -------- | ------ | ---------------- |
| Files in this change | `main.py` + `App.tsx` only | Longer SQL/test/CSS files are different seams |
| Route grouping | Existing OpenAPI tags | `GET /projects/{id}/audit-events` stays administration |
| Frontend depth | Every screen/dialog | Shell stays in `App.tsx` |
| Sequence | API first, then UI | Routers are the smaller, test-backed cut |
| Shared UI | `components/` + `features/` | Primitives are reused; screens are domains |
| Vitest imports | Point at new modules | Tests assert Banner-on-403, not the `App.tsx` path |
| Test harness | Stay in the Vitest file | `PublishModelHarness` is not a production component |
| Verification | Existing suites + OpenAPI tags + Playwright on the UI phase | Characterization, not a new test split |

## Scope

**In scope:** API deps/mappers/middleware/SPA helpers; one router per OpenAPI
tag; frontend components, format helpers, session singleton, feature screens.

**Out of scope:** `storage.py`, splitting `test_api.py`, `api.ts`, `styles.css`,
React Router, CSS modules, new endpoints, authz-in-the-browser.

## Architecture / Approach

Put DB, object store, and settings on `app.state`. Routers depend on
`deps.py` and map rows through `responses.py`. Feature screens share one
`ApiClient` from `session.ts`. CSS class names are unchanged.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| ----- | ---------------- | -------- |
| 1. API shared surface | Deps, mappers, middleware, SPA helper | Auth closures still bound to `create_app` |
| 2. API domain routers | Thin factory; tag snapshot; dispatch monkeypatch path | SPA catch-all registered before API routes |
| 3. Frontend shared UI | `components/`, `lib/format.ts`, `session.ts` | Class-name drift vs `styles.css` |
| 4. Frontend feature screens | `features/` + Vitest import move + Playwright | Second `ApiClient` instance dropping the token |

**Prerequisites:** Current HTTP and Vitest suites green on the branch.
**Estimated effort:** ~2–3 sessions across 4 phases.

## Open Risks & Assumptions

- Monkeypatching `src.api.main.dispatch_analysis_run` stops working once
  analysis imports dispatch in its router.
- Membership-miss stays 404; wrong role stays 403.

## Success Criteria (Summary)

- OpenAPI paths, methods, and tags match the frozen map.
- Register/Publish 403 still shows Banner copy, not success status.
- Playwright HDFS publish/deny specs still pass after the UI split.
