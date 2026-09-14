# Frontend role signals — Plan Brief

> Full plan: `context/changes/testing-frontend-role-signals/plan.md`
> Research: `context/changes/testing-frontend-role-signals/research.md`

## What & Why

An Operator can still click Register and Publish. The API returns 403
and HTTP tests already prove no row, but the SPA could show success
copy or never fire the request. This phase proves deny **copy** (alert,
no success Banner) with buttons left visible — S-02’s thin client.

## Starting Point

No Vitest. Playwright is Publisher publication only. `project-b-user`
is Operator on project B (404 on A, not 403). `User` has no project
role. Select is local published-only state.

## Desired End State

Fake-API tests and a same-project Operator browser spec both show
`Insufficient project role.` and no “registered/published” success
copy. `npm test` runs on the existing frontend CI job. §6.3 tells the
next agent how to add another deny-copy test.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| -------- | ------ | ---------------- | ------ |
| Product UI | Buttons stay visible | Hiding is not the security control | Research |
| Select | Out of role-deny scope | Local state, not an API 403 | Research / Plan |
| Test layers | Vitest fake API **and** Operator Playwright | User wanted shell proof; Playwright is Banner-only so pytest keeps no-row | Plan |
| Playwright actor | Same-project Operator | `project-b-user` would be 404 | Plan |
| Playwright oracle | Alert + no success status | Avoid duplicating HTTP isolation | Plan |
| CI | `npm test` on existing `frontend` job | §5 requires component tests after Phase 3; do not reopen Phase 4 | Research / Plan |

## Scope

**In scope:** Vitest + RTL; export Register/Publish Banner surfaces;
403 component tests; project-A Operator e2e account; Banner-only
Playwright spec; frontend CI `npm test`; §6.3/§4/§6.6/§6.7 cookbook.

**Out of scope:** Role hiding; `/users/me` role field; Select-as-403;
rewriting pytest 403; screenshot oracles; analysis/intake E2E; Phase 4
rewrite; §1–§2 edits.

## Architecture / Approach

Stub `ApiError` 403 in component tests (independent UI oracle). In the
browser, restore an Operator token on project A, click the same
controls, assert `role="alert"` vs `role="status"`. Do not GET models
after the click in Playwright.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| ----- | ---------------- | -------- |
| 1. Vitest + 403 component tests | Runner, exports, fake-API deny copy | Exporting ModelsView only and missing the page Banner |
| 2. Operator Playwright | Same-project 403 Banner spec | Using project-B token (404) |
| 3. CI + cookbook | `npm test` in Verify frontend; §6.3 | Reopening Phase 4 |

**Prerequisites:** Phase 1 HTTP 403 tests already on `feature/test-plan-refresh`.
**Estimated effort:** ~2–3 sessions across 3 phases.

## Open Risks & Assumptions

- Playwright for this risk overrides the test-plan “no extra e2e”
  cheapest-layer line; Banner-only keeps it from duplicating pytest.
- `App.tsx` is a monolith; publish 403 must be tested with Banner, not
  the card button alone.

## Success Criteria (Summary)

- 403 Register/Publish never show success copy in component tests or the Operator spec.
- HTTP tests remain the no-row oracle.
- §6.3 is a recipe, not TBD.
