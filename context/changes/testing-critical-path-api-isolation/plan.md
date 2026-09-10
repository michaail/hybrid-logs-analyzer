# Critical-path API isolation tests Implementation Plan

## Overview

Close pytest gaps for test-plan risks #1–#3 at the existing FastAPI HTTP
boundary. The product already 404s cross-project access, 403s Operator
register/publish before insert, and 422/409s ineligible ZIP / unpublished
analysis. This change adds assertions for the untested matrix and Operator
side effects, then writes the cookbook so later endpoints copy the same
pattern.

## Current State Analysis

Research (`context/changes/testing-critical-path-api-isolation/research.md`)
is the baseline. There is no frame brief.

Login is not authorization. `get_current_user` only proves an active bearer
(`src/api/main.py:71-86`). Project routes then call `require_project_access` /
`require_project_role` (`src/api/main.py:93-114`). Non-members get **404**.
Wrong role after membership gets **403**. Resource fetches are id-only in
storage; HTTP compares `row["project_id"]` to the path.

Existing coverage: foreign **list models 404** and Operator register **403
status** (`tests/test_api.py:388-420`); Operator publish **403 status**
(`:457-464`); dataset IDOR (`:547-597`); ZIP 201 / ineligible 422 + empty
list (`:909-936`); unpublished analysis 409 + empty runs (`:1069-1095`).

Gaps: get/register/publish on a foreign project; analysis-run list/create/get
and results IDOR; analyze with a foreign `model_version_id` (code at
`src/api/main.py:518-520`, no pytest); Operator 403 without “no new row”;
unauthenticated POST register 401.

## Desired End State

A two-project Operator/Publisher graph in `tests/test_api.py` proves:

- A logged-in user of project B cannot observe or mutate project A’s models,
  runs, or results (404, or 200 + `[]` on B’s own empty lists). Foreign ids
  under B’s path 404. Analyze on B with A’s `model_version_id` 404s and
  creates no run.
- Operator register/publish is 403 and leaves no new eligible/published row.
- Unauthenticated `POST /projects/{id}/models` is 401.
- ZIP 422 / unpublished 409 tests remain the #3 oracle; they are not rewritten.

`context/foundation/test-plan.md` §6.1, §6.2, and §6.4 describe how to add
the next isolation test without reimplementing membership helpers.

### Key Discoveries:

- Membership miss is 404, not empty foreign data (`src/api/main.py:93-100`).
- Operator 403 runs **before** ZIP admit / insert (`src/api/main.py:388`, `:470`).
- 201 means `eligible` only; analysis needs `published` + same project
  (`src/api/main.py:517-525`).
- Admin bypasses the Publisher set (`src/api/main.py:94-110`) — not a 403 case.
- Dataset IDOR is already tested; do not duplicate (`tests/test_api.py:547-597`).
- CI already runs `tests/test_api.py` with `-m "not ml"`
  (`.github/workflows/verify.yml:28`).

## What We're NOT Doing

- Product changes to `src/api/`, frontend, object store, or the validator.
- Frontend Register/Publish visibility (test-plan Phase 3 / risk #6).
- Risks #4/#5: Torch in the API process, env scrub, leftover prefixes (F5/F7/F8).
- Rewriting FastAPI missing-file 422 to `{valid, issues[]}` (S-02 F6).
- Unit tests that reimplement `require_project_role` / membership SQL.
- Copying validator `issues[].reason` strings as oracles.
- Treating Admin 200/201 as an isolation failure.
- Collapsing 403 (wrong role, same project) with 404 (other project).
- Dataset intake (S-03), notebook parity, `@ml` on Ubuntu CI, browser e2e.
- Replacing existing ZIP 201 / ineligible 422 / unpublished 409 tests.

## Implementation Approach

HTTP integration only, using the existing `api` fixture and helpers
(`_login`, `_create_project`, `_provision_project_account`, `_register`,
`_zip_staged`) in `tests/test_api.py`. Oracle: status plus absence of
foreign ids / empty lists / unchanged `eligible`. Cost × signal: one
unauthenticated POST covers `Depends(get_current_user)` for other verbs.

## Critical Implementation Details

Keep **401 / 403 / 404** distinct. Same-project Operator register is 403;
other-project Operator register is 404. Do not assert Admin 403 on
register/publish. Do not call `get_membership` or inspect storage helpers
from tests — only HTTP.

## Phase 1: Cross-project HTTP matrix

### Overview

Prove risk #1: a logged-in user cannot observe or act on another project’s
models, runs, or results. Also prove unauthenticated register is 401.

**Behavior asserted:** foreign path 404; IDOR (own path + other project’s
id) 404; own-project lists do not contain the other project’s ids (200 +
`[]` when empty); analyze with a foreign `model_version_id` 404 and no run
row; unauthenticated POST models 401.

**Regression caught:** a new get/mutate route that uses `get_current_user`
without `require_project_*`, or that returns another project’s row by id.

**Research source:** `research.md` Risk #1 gaps; `src/api/main.py:93-114`,
`:442-525`, `:611-638`.

**Boundary cases:** member of B + path A vs member of B + path B + A’s id;
Operator vs Publisher of the other project (both 404); 401 vs 404 vs 403.

**Anti-pattern avoided:** happy-path 200 only; asserting membership helper
internals; treating Admin bypass as a leak.

### Changes Required:

#### 1. Two-project isolation tests

**File**: `tests/test_api.py`

**Intent**: Add (or extend) TestClient cases for the full member-route
matrix on models, analysis-runs, and results. Reuse existing two-project
helpers. Seed resources in project A with a Publisher; callers under test
are Operators (and a Publisher of B for foreign register/publish 404).

**Contract**: For project A resources and a user who is only a member of B:

- `GET /projects/{A}/models/{id}` → 404
- `GET /projects/{B}/models/{A's id}` → 404
- `POST /projects/{A}/models` (ZIP) as B’s Publisher → 404; A’s model list
  unchanged
- `POST /projects/{A}/models/{id}/publish` as B’s Publisher → 404; A’s
  version stays `eligible` until A’s Publisher publishes
- `GET /projects/{A}/analysis-runs` → 404
- `GET /projects/{B}/analysis-runs` while runs exist only on A → 200 + `[]`
- `POST /projects/{A}/analysis-runs` → 404
- `POST /projects/{B}/analysis-runs` with A’s published `model_version_id`
  → 404; B’s run list still `[]`
- `GET` run and results for A’s run under path A as B → 404
- `GET` A’s run id under path B → 404
- Unauthenticated `POST /projects/{A}/models` with a ZIP → 401

Do not duplicate dataset IDOR. Do not hit `/projects/{id}/audit-events`.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py -m "not ml"` passes, including the new
  cross-project matrix and unauthenticated POST 401
- `ruff check tests/test_api.py` and `mypy` pass

#### Manual Verification:

- Scan the new tests: 403 never used where the contract says 404; no Admin
  403 case; no `get_membership` / SQL assertions

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Operator 403 creates no version row

### Overview

Prove risk #2 at the API: Operator register/publish is 403 **and** no
lifecycle row appears. UI visibility is out of scope.

**Behavior asserted:** Operator ZIP register → 403 then `GET .../models ==
[]`. After a Publisher 201 `eligible`, Operator publish → 403 then GET
still `eligible` (`published_at` absent / status unchanged).

**Regression caught:** role check moved after `create_model_version` or
publish CAS.

**Research source:** `research.md` Risk #2; `src/api/main.py:388`, `:470`.

**Boundary cases:** same-project Operator is 403, not 404; do not require
object-store emptiness (put is not reached).

**Anti-pattern avoided:** frontend-only tests; status 403 without side-effect
check.

### Changes Required:

#### 1. Operator side-effect assertions

**File**: `tests/test_api.py`

**Intent**: Strengthen the existing Operator 403 cases so they match the
ineligible-ZIP “no row” pattern (`tests/test_api.py:926-936`).

**Contract**: After Operator register 403, `GET /projects/{id}/models` as
Publisher or Operator is `[]`. After Operator publish 403, `GET` that model
is still `status == "eligible"`. Prefer extending
`test_authentication_roles_and_project_isolation` and
`test_model_publication_and_safe_analysis_run_lifecycle` over parallel
tests that only re-assert 403.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py -m "not ml"` passes, including Operator
  register 403 + empty list and Operator publish 403 + still eligible
- `ruff check tests/test_api.py` and `mypy` pass

#### Manual Verification:

- Confirm no frontend test or UI hide was added; API 403 remains the control

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Cookbook patterns for isolation tests

### Overview

Record how to add the next isolation test. Risk #3 ZIP 422 / unpublished
409 already exist; this phase does not rewrite them.

**Behavior asserted:** §6 tells a later agent to use two-project HTTP
integration, 404 vs 403 vs 401, and GET-empty oracles — not membership
unit tests.

**Regression caught:** a later endpoint lands with only a happy-path 200 test.

**Research source:** test-plan §6 placeholders; this change’s Phase 1–2
tests as the reference.

**Anti-pattern avoided:** file:line anchors in test-plan §2; cookbook that
says “cover the module.”

### Changes Required:

#### 1. Fill test-plan cookbook

**File**: `context/foundation/test-plan.md`

**Intent**: Replace §6.1, §6.2, and §6.4 TBD placeholders with the patterns
this rollout shipped. Optionally append a short §6.6 note. Do not edit §1–§5
risk wording (backport those later via `/10x-test-plan` if desired). Bump
the header “Last updated” date.

**Contract**:

- **§6.1** — Isolation proofs are not membership-helper unit tests. Point
  at §6.2. Location remains `tests/` pytest; run
  `python -m pytest tests/test_api.py -m "not ml"`.
- **§6.2** — Two-project HTTP: foreign path 404; IDOR 404; empty own list;
  never assert helper internals. Reference the new/extended tests in
  `tests/test_api.py` by path (not a dump of production logic).
- **§6.4** — New project-scoped route: before happy-path 200, add the
  same-project vs other-project matrix (404 vs empty other-project
  payload) and the role 403 vs other-project 404 split.
- **§6.6** — One note: Operator 403 must include GET-empty / still-eligible;
  201 eligible is not usable for analysis (existing unpublished 409 test).

### Success Criteria:

#### Automated Verification:

- `context/foundation/test-plan.md` §6.1, §6.2, and §6.4 no longer read
  “TBD — see §3 Phase 1”
- `python -m pytest tests/test_api.py -m "not ml"` still passes

#### Manual Verification:

- Read §6: no `file:line` failure anchors; 401/403/404 distinction is
  explicit; risk #3 tests are cited as already present, not re-specified

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- None for membership helpers. Do not add tests whose expected value is
  copied from `require_project_role`.

### Integration Tests:

- Two-project matrix (Phase 1)
- Operator 403 + no row (Phase 2)
- Keep existing ZIP 422 + unpublished 409 (risk #3)

### Manual Testing Steps:

1. Confirm new tests use 404 for other-project and 403 only for same-project
   Operator register/publish.
2. Confirm no UI or validator/Torch tests were added.
3. Skim §6 cookbook for copy-pasteable next-endpoint guidance.

## Performance Considerations

None. Tests use the in-memory/SQLite `api` fixture already used by
`tests/test_api.py`.

## Migration Notes

Not applicable. No schema or API contract change.

## References

- Related research: `context/changes/testing-critical-path-api-isolation/research.md`
- Test plan: `context/foundation/test-plan.md` (rollout Phase 1, risks #1–#3)
- Isolation helpers: `src/api/main.py:71-114`
- Existing tests: `tests/test_api.py:388-420`, `:547-597`, `:909-936`, `:1069-1095`
- CI: `.github/workflows/verify.yml:28`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Cross-project HTTP matrix

#### Automated

- [x] 1.1 `python -m pytest tests/test_api.py -m "not ml"` passes, including the new cross-project matrix and unauthenticated POST 401 — ea2b22c
- [x] 1.2 `ruff check tests/test_api.py` and `mypy` pass — ea2b22c

#### Manual

- [x] 1.3 Scan the new tests: 403 never used where the contract says 404; no Admin 403 case; no `get_membership` / SQL assertions — ea2b22c

### Phase 2: Operator 403 creates no version row

#### Automated

- [ ] 2.1 `python -m pytest tests/test_api.py -m "not ml"` passes, including Operator register 403 + empty list and Operator publish 403 + still eligible
- [ ] 2.2 `ruff check tests/test_api.py` and `mypy` pass

#### Manual

- [ ] 2.3 Confirm no frontend test or UI hide was added; API 403 remains the control

### Phase 3: Cookbook patterns for isolation tests

#### Automated

- [ ] 3.1 `context/foundation/test-plan.md` §6.1, §6.2, and §6.4 no longer read “TBD — see §3 Phase 1”
- [ ] 3.2 `python -m pytest tests/test_api.py -m "not ml"` still passes

#### Manual

- [ ] 3.3 Read §6: no `file:line` failure anchors; 401/403/404 distinction is explicit; risk #3 tests are cited as already present, not re-specified
