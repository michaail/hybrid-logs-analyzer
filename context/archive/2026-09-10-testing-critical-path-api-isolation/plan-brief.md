# Critical-path API isolation tests — Plan Brief

> Full plan: `context/changes/testing-critical-path-api-isolation/plan.md`
> Research: `context/changes/testing-critical-path-api-isolation/research.md`

## What & Why

The HTTP control plane already isolates projects, denies Operator
register/publish, and refuses ineligible ZIP / unpublished analysis. Tests do
not yet prove the full matrix or that Operator 403 leaves no row. This change
closes those gaps so a later route cannot ship as “logged in ⇒ allowed.”

## Starting Point

`tests/test_api.py` already covers foreign list-models 404, dataset IDOR,
Operator 403 *status*, ZIP 201/422, and unpublished analysis 409. Get/mutate
IDOR, foreign `model_version_id` on analyze, Operator “no row,” and
unauthenticated POST register are missing.

## Desired End State

Two-project pytest proves 404 (not another project’s data) on models, runs,
and results, including analyze-with-foreign-model-id. Operator 403 leaves an
empty model list / still-`eligible` version. Unauthenticated POST `/models`
is 401. The test-plan cookbook tells the next agent to copy that matrix.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Layer | HTTP TestClient only | Cheapest real signal; UI and Torch are later rollout phases | Research |
| Matrix width | Full member routes; skip admin audit and dataset IDOR | Dataset already tested; audit is a different 403 pattern | Plan |
| Operator 403 | GET empty / still eligible; no object-store check | Role gate runs before `put`; GET matches the 422 “no row” oracle | Plan |
| F6 missing-file 422 | Skip | ZIP content 422 already proves structured reject; F6 is not risk #3 | Plan |
| Unauthenticated | One POST `/models` → 401 | Shared `Depends(get_current_user)` | Plan |
| Unit tests of membership | Out of scope | Would mirror `require_project_role` | Research |
| Admin | Not a 403 case | Privileged bypass is intentional | Research |

## Scope

**In scope:**

- Cross-project 404 / IDOR / empty lists for models, analysis-runs, results
- Foreign `model_version_id` → analyze 404 + no run
- Operator register/publish 403 + no new row
- Unauthenticated POST models 401
- Cookbook §6.1 / §6.2 / §6.4

**Out of scope:**

- Product/UI/validator changes; risks #4–#6; F5/F6/F7/F8; `@ml` CI; e2e
- Rewriting existing ZIP 422 / unpublished 409 tests

## Architecture / Approach

Extend `tests/test_api.py` with the existing two-project helpers. Oracle is
HTTP status plus absence of foreign ids. Last phase only edits
`context/foundation/test-plan.md` §6.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Cross-project HTTP matrix | Member-route 404/IDOR + POST 401 | Collapsing 403 and 404 |
| 2. Operator 403 has no row | Empty list / still eligible | Status-only 403 slipping through |
| 3. Cookbook | §6 patterns for the next endpoint | Cookbook that re-anchors §2 |

**Prerequisites:** research.md complete; `tests/test_api.py` helpers already work.
**Estimated effort:** ~1 session across 3 phases (pytest, then cookbook).

## Open Risks & Assumptions

- CI already runs `test_api.py`; Phase 4 of the test-plan rollout is not required
  to “discover” these tests.
- Native `@ml` tests remain local-only; this plan never enables them on Ubuntu.

## Success Criteria (Summary)

- Other-project users get 404 (or empty own lists), never A’s payloads.
- Operator cannot create or publish a version row.
- 201 eligible still cannot start analysis (existing test kept).
