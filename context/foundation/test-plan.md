# Test Plan

> Phased test rollout for this project. Strategy is frozen at the top
> (§1–§5); cookbook patterns at the bottom (§6) fill in as phases ship.
> Read before writing any new test.
>
> Refresh: re-run `/10x-test-plan --refresh` when stale (see §8).
>
> Last updated: 2026-09-10

## 1. Strategy

Tests follow three non-negotiable principles for this project:

1. **Cost × signal.** The cheapest test that gives a real signal for the
   risk wins. Do not promote to e2e because e2e "feels safer." Do not put a
   vision model on top of a deterministic visual diff that already catches
   the regression.
2. **User concerns are first-class evidence.** Risks anchored in "<the
   team is worried about X, and the failure would surface somewhere in
   <area>>" carry the same weight as PRD lines or hot-spot data.
3. **Risks are scenarios, not code locations.** This plan documents *what
   could fail* and *why we believe it's likely* — drawn from documents,
   interview, and codebase *signal* (churn, structure, test base). It does
   NOT claim to know which line owns the failure. That knowledge is
   produced by `/10x-research` during each rollout phase. If the plan and
   research disagree about where the failure lives, research is the
   ground truth.

Hot-spot scope used for likelihood weighting: `src/api`, `src/modules`,
`src/model_validator`, `frontend/src`.

Protect the HTTP isolation and model-lifecycle gates first. Add frontend
role-signal tests only after those gates have a regression net. Do not spend
rollout budget on notebooks, BGL, or `@ml` jobs on Ubuntu CI. Notebook
parity within one percentage point waits for S-04 and a trained baseline.

## 2. Risk Map

The top failure scenarios this project must protect against, ordered by
risk = impact × likelihood. Risks are failure scenarios in user / business
terms, not test names. The Source column cites the *evidence that surfaced
this risk* — never a specific file as "where the failure lives" (that is
research's job, see §1 principle #3).

| # | Risk (failure scenario) | Impact | Likelihood | Source (evidence — not anchor) |
|---|------------------------------------------|--------|------------|----------|
| 1 | A user can observe or act on another project's models, logs, runs, or results | High | High | interview Q1; PRD FR-008 / Access Control; hot-spot dir `src/api` (53 file-touches/30d); archive S-01/F-01 isolation |
| 2 | An Operator (or other unauthorized role) can register or explicitly publish a model | High | Medium | PRD US-01 acceptance; archive S-02 Operator 403; interview Q4 |
| 3 | An ineligible package becomes eligible, or a registered-but-unpublished version is used for analysis | High | Medium | interview Q3; PRD FR-002–FR-004; archive S-02; S-02 impl-review leftover F5/F6 |
| 4 | An uploaded `.pt` is deserialized in the control plane or in a process that holds app secrets | High | Medium | AGENTS.md untrusted-model rule; tech-stack “API never deserializes”; F-02 archive risk |
| 5 | A failed register leaves object-store leftovers another caller could hit if isolation slips | Medium | Medium | interview Q3; S-02 impl-review F7/F8; hot-spot dir `src/api` |
| 6 | The UI shows Register/Publish/Select as available or successful when the API would deny the action | Medium | High | interview Q4; hot-spot dir `frontend/src` (19 file-touches/30d); sparse suite (no frontend tests) |

### Risk Response Guidance

| Risk | What would prove protection | Must challenge | Context `/10x-research` must ground | Likely cheapest layer | Anti-pattern to avoid |
|------|-----------------------------|----------------|--------------------------------------|-----------------------|-----------------------|
| #1 | Same credentials cannot read or mutate another project's models/logs/runs (404, not the other project's data) | “Logged in” equals “authorized for this resource” | How membership is bound on list, get, and mutate | integration (two-project HTTP) | Happy-path 200 only; asserting the membership helper's internals |
| #2 | Operator register/publish is 403 and creates no version row | Hiding the button in the UI is sufficient | Role vs membership vs project on register/publish | integration HTTP | Frontend-only test that never hits the API |
| #3 | Ineligible ZIP → structured reject + no row; unpublished version cannot start analysis | HTTP 201 on upload means the version is usable | Eligibility vs publish vs analysis gate | integration (ZIP + status) | Snapshot of validator internals; expected `issues[]` copied from current code |
| #4 | Control plane admits/rejects without loading the `.pt`; validator environment has no app secrets | “Validator ran” means Torch in the API process is acceptable | Where the artifact is probed vs stored; env-scrub contract | integration / contract | Importing Torch in API tests “to be realistic” |
| #5 | Duplicate or failed insert leaves only the first declared prefix, or nothing | HTTP 409/5xx implies storage was cleaned | put vs insert vs delete-prefix; Bucket error list | integration against the store adapter | Mocking the store so cleanup never runs |
| #6 | Denied actions stay denied in the UI and the API error is shown; success copy only after an allowed 2xx | A disabled button means the client will not send the request | Which calls the UI makes per role; how 403/404 are shown | component tests with a fake API | Browser e2e because it “feels safer”; screenshot snapshots |

## 3. Phased Rollout

Each row is a discrete rollout phase that will open its own change folder
via `/10x-new`. Status moves left-to-right through the values below; the
orchestrator updates Status as artifacts appear on disk.

| # | Phase name | Goal (one line) | Risks covered | Test types | Status | Change folder |
|---|------------------------------|--------------------------------------------------|----------------|-------------------------------|-------------|---|
| 1 | Critical-path API isolation | Prove cross-project deny, Operator 403, and ineligible/unpublished gates at the HTTP boundary | #1, #2, #3 | unit + integration | change opened | testing-critical-path-api-isolation |
| 2 | Package admission safety | Prove untrusted `.pt` stays out of the control plane and failed admits leave no orphans | #4, #5 | integration + contract | not started | — |
| 3 | Frontend role signals | Prove the UI cannot look like a successful unauthorized publish or select | #6 | component (bootstrap runner if needed) | not started | — |
| 4 | Quality-gates wiring | Lock Phase 1–3 tests into CI without adding `@ml` on Ubuntu | cross-cutting | gates | not started | — |

## 4. Stack

The classic test base for this project. AI-native tools (if any) carry a
`checked:` date so future readers can see which lines need re-verification.
Recommendations in this section must be grounded in local manifests/configs
plus the MCP/tools actually exposed in the current session. If a useful docs
or search MCP such as Context7 or Exa.ai is not available, say that instead
of assuming access.

| Layer | Tool | Version | Notes |
|----------------------|----------------------------|---------|--------------------------------------|
| unit + integration | pytest | 9.1.1 | `tests/`; markers `ml` and `postgres`; FastAPI client via httpx 0.28.1 |
| lint + types | ruff, mypy | 0.16.5 / 2.3.1 | already required in `.github/workflows/verify.yml` |
| API runtime under test | FastAPI | 0.115.12 | control plane; do not load Torch in this process |
| frontend unit | none yet — see Phase 3 | — | React 18 + Vite; no test runner in `frontend/package.json` |
| e2e | none yet | — | not in this rollout; API isolation is cheaper |
| (optional) AI-native | cursor-ide-browser — checked: 2026-09-10 | n/a | manual smoke only; do not replace HTTP isolation tests |

**Stack grounding tools (current session):**
- Docs: none — Context7 / framework-docs MCP not available; checked: 2026-09-10
- Search: none as MCP — Exa.ai not available; checked: 2026-09-10
- Runtime/browser: cursor-ide-browser — possible UI smoke, not a substitute for API isolation tests; checked: 2026-09-10
- Provider/platform: none — no GitHub/Railway MCP; CI already lives in `verify.yml`; checked: 2026-09-10

Test-base profile: **sparse** — pytest configured, ~8 files clustered under `tests/`, frontend suite absent, CI skips `@ml`.

## 5. Quality Gates

The full set of gates that must pass before a change reaches production.
"Required for §3 Phase <N>" means the gate is enforced once that rollout
phase lands; before that, the gate is `planned`.

| Gate | Where | Required? | Catches |
|-------------------------------|-------------------|------------------------------|-----------------------------------------------|
| lint + typecheck | local + CI | required | syntactic / type drift |
| unit + integration (Torch-free) | local + CI | required after §3 Phase 1 | isolation, role, eligibility, unpublished-use regressions |
| frontend component tests | local + CI | required after §3 Phase 3 | UI success/deny copy that contradicts the API |
| CI pytest + frontend-test jobs | CI on PR | required after §3 Phase 4 | Phase 1–3 tests silently dropping out of Verify |

## 6. Cookbook Patterns

How to add new tests in this project. Each sub-section is filled in once
the relevant rollout phase ships; before that, the sub-section reads
"TBD — see §3 Phase <N>."

### 6.1 Adding a unit test

Do not prove project isolation with unit tests of membership helpers or
storage SQL. Those tests copy production branching and miss HTTP status
semantics (401 vs 403 vs 404). Isolation, role, and lifecycle oracles live
in HTTP integration tests — follow §6.2.

New tests go under `tests/` as pytest. For this control-plane surface, run:

`python -m pytest tests/test_api.py -m "not ml"`

### 6.2 Adding an integration test

Use the existing FastAPI `api` fixture and helpers in `tests/test_api.py`
(`_login`, `_create_project`, `_provision_project_account`, `_register`,
`_zip_staged`). Seed resources in project A with a Publisher; call as a
member of project B (or as a same-project Operator for role denies).

Oracle is HTTP status plus absence of foreign ids. Never assert membership
helper internals or storage SQL from tests.

Keep **401 / 403 / 404** distinct:

- **401** — no (or inactive) bearer. One unauthenticated
  `POST /projects/{id}/models` covers the shared bearer dependency for
  other verbs.
- **404** — not a member of the path project, or the resource id belongs to
  another project (IDOR). Non-members must not learn that the project exists.
- **403** — member of this project, wrong role (same-project Operator
  register/publish). Do not treat Admin 200/201 as an isolation failure.

Matrix for member routes (models, analysis-runs, results):

1. Foreign path: `GET/POST /projects/{A}/...` as a user of B → **404**.
2. IDOR: `GET/POST /projects/{B}/.../{id owned by A}` → **404**.
3. Own empty list: `GET /projects/{B}/...` while data exists only on A →
   **200** and `[]` (the list must not contain A's ids).
4. Analyze on B with A's `model_version_id` → **404** and B's run list
   stays `[]`.

Reference implementations in `tests/test_api.py` (function names, not
production logic):

- `test_cross_project_member_routes_return_404` — 404 / IDOR / empty-list /
  foreign-model analyze / unauthenticated POST 401.
- `test_authentication_roles_and_project_isolation` — foreign list 404;
  Operator ZIP register **403** then `GET .../models == []`.
- `test_model_publication_and_safe_analysis_run_lifecycle` — Operator
  publish **403** then GET still `eligible` (`published_at` absent).

Risk #3 oracles already exist; cite them, do not rewrite them:

- `test_registration_rejects_ineligible_zip_without_inserting` — ineligible
  ZIP **422** `{valid, issues[]}` and empty model list.
- `test_unpublished_eligible_model_cannot_start_analysis` — eligible
  unpublished analyze **409** and empty run list.

Do not duplicate dataset IDOR
(`test_dataset_reads_are_isolated_and_omit_rejected_inputs`). Do not hit
`/projects/{id}/audit-events` for member isolation (admin-only, different
403).

### 6.3 Adding a frontend component test

TBD — see §3 Phase 3 for denied Register/Publish/Select remaining denied, with API errors shown and no success copy on 403.

### 6.4 Adding a test for a new API endpoint

Before any happy-path 200/201/202 on a new project-scoped route:

1. Unauthenticated request → **401** (enough once if the route shares the
   bearer dependency).
2. Other-project member, foreign path → **404**.
3. Other-project member, own path + foreign resource id → **404**.
4. Other-project member, own collection while the only rows live on the
   other project → **200** + empty payload (or no foreign ids).
5. Same-project wrong role → **403**; other-project same action → **404**.
   Do not collapse these.
6. If the action creates or mutates a row, follow the GET-empty /
   status-unchanged oracle from §6.2 (Operator 403 must not insert
   `eligible` or flip `published`).

Then add the allowed-role happy path.

### 6.5 Adding a test for package admission

TBD — see §3 Phase 2 for control-plane-without-Torch, env-scrub, and leftover-prefix cleanup after failed insert.

### 6.6 Per-rollout-phase notes

**Critical-path API isolation (2026-09-10):** Operator **403** is not
enough — assert `GET .../models == []` after register and still-`eligible`
after publish. HTTP **201** means `eligible` only; analysis still requires
`published` (existing `test_unpublished_eligible_model_cannot_start_analysis`).

## 7. What We Deliberately Don't Test

Exclusions agreed during the rollout (Phase 2 interview, Q5). Future
contributors should respect these unless the underlying assumption changes.

- **R&D notebooks and BGL research paths** — they remain a separate comparison workflow, not the web MVP. Re-evaluate if notebooks become the production execution path. (Source: Phase 2 interview Q5.)
- **`@ml` jobs on Ubuntu CI** — native Intel Torch paths are local; Verify stays Torch-free. Re-evaluate when a Linux inference image is the CI target.
- **Notebook-parity within one percentage point** — High impact, Low likelihood until S-04 and a trained baseline exist. Re-evaluate when that slice opens.
- **Invalid HDFS dataset intake** — S-03 is not implemented; do not invent that path in this rollout. Re-evaluate when intake is planned.
- **Browser e2e and UI screenshot snapshots** — cost exceeds signal while the API remains the authorization boundary.

## 8. Freshness Ledger

- Strategy (§1–§5) last reviewed: 2026-09-10
- Stack versions last verified: 2026-09-10
- AI-native tool references last verified: 2026-09-10

Refresh (`/10x-test-plan --refresh`) when:

- a new top-3 risk surfaces from the roadmap or archive,
- a recommended tool's `checked:` date is older than three months,
- the project's tech stack changes (new framework, new test runner),
- §7 negative-space no longer matches what the team believes.
