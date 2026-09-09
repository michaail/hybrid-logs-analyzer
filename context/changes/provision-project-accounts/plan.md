# Provision project-authorized accounts Implementation Plan

## Overview

Complete S-01 by turning the existing API-level identity foundation into a safe,
administrator-operated workflow. An administrator will provision a non-administrator
account with an initial Operator or Publisher membership, manage its project access,
and retain an auditable, project-isolated record of every privileged change.

## Current State Analysis

FastAPI already provides administrator-only user creation, password/JWT sign-in, and
project membership authorization. These parts do not yet compose into the S-01
workflow: account creation and membership grant are separate requests and transactions,
the React Administration view has no account-management controls, and the membership
upsert does not distinguish a new grant from a role change.

The access-control model is intentionally project-local: the `memberships` primary key
allows one role per `(project_id, user_id)`, while a Publisher implicitly satisfies
Operator authorization. The existing per-request database lookup means revoking a
membership or deactivating an account can invalidate a still-held bearer token
immediately, without changing JWT issuance or lifetime.

## Desired End State

An authenticated Administrator can, from the selected project's Administration view,
create an active lowercase-username account and its initial Operator or Publisher
membership as one atomic action. The same view lets the Administrator inspect members,
grant an existing account access, change its role, revoke its project membership, and
deactivate or reactivate a non-administrator account.

Every successful administrative mutation commits with an audit event or leaves no
mutation behind. Project-related account actions appear in the selected project's audit
trail, and account provisioning and activation state are available in a separate
Administrator-only system audit view. Existing public-sign-in behavior remains absent.

### Key Discoveries:

- `POST /admin/users` creates a user separately from
  `POST /projects/{project_id}/members`, so neither the initial role nor audit record is
  transactionally coupled to the account today: `src/api/main.py:152-249` and
  `src/api/storage.py:101-163`.
- The current `memberships` schema already supports a different role per project, which
  must remain the authorization source of truth: `src/api/migrations.py:31-36`.
- Authentication reads the user database record for every protected request, and
  Publisher already includes Operator privileges: `src/api/main.py:59-102`.
- The React client has a selected-project Administration view and project audit trail,
  but no account or membership API methods or controls: `frontend/src/App.tsx:672-795`
  and `frontend/src/api.ts:110-170`.

## What We're NOT Doing

- Public registration, invitation emails, password reset, MFA, SSO, or social sign-in.
- Browser-based creation of peer Administrators; the first Administrator remains a
  deployment-time, CLI-only bootstrap operation.
- Deleting accounts, memberships, or audit records. Revocation/deactivation preserves
  history and related model/run foreign keys.
- Changing model admission, artifact loading, HDFS dataset intake, inference, notebook
  behavior, or adding any log source other than HDFS.
- Building a second authorization implementation in the React client; FastAPI remains
  authoritative.

## Implementation Approach

Evolve the current FastAPI/SQLite-and-PostgreSQL repository and thin React client in
place. Because this has not been deployed and its local metadata is disposable, replace
the unreleased initial user schema rather than introduce a compatibility migration.
Centralize account/membership mutations in transaction-scoped repository methods that
write their audit event before committing; then expose narrow Administrator-only API
contracts and bind them to the existing selected-project Administration view.

The web provisioning endpoint will require a project and initial role, rather than
leaving the existing two-step account-creation workflow exposed. Later project access
for an existing account remains an explicit membership grant. Role changes and
revocations get distinct endpoints and audit actions rather than retaining the current
ambiguous upsert.

## Critical Implementation Details

### State sequencing

For every account or membership mutation, persist the domain record and the audit event
through the same `ApiDatabase.session()` scope, then return the committed state. A
failure creating the audit event, including a uniqueness conflict detected during the
transaction, must roll back the user, account state, or membership change rather than
returning a failure after changing access.

## Phase 1: Account persistence and transactional audit

### Overview

Make the stored identity and membership lifecycle explicit, portable across SQLite and
PostgreSQL, and safe to audit atomically.

### Changes Required:

#### 1. Unreleased initial account schema

**File**: `src/api/migrations.py`

**Intent**: Amend the unreleased initial schema so new local and deployed metadata
stores record active account state and enforce canonical lowercase usernames from the
first migration. Do not modify unrelated HDFS model/run tables.

**Contract**: `users.username` stores only the lowercase normalized username and remains
uniquely constrained; `users.is_active` is non-null and defaults to active. Remove any
existing disposable local API metadata database and rerun the initial migration before
using this branch. The first Railway deployment applies this initial shape to an empty
database, so no username backfill, collision remediation, rolling upgrade, or
backward-compatible schema period is required.

#### 2. Transaction-scoped identity and membership repository methods

**File**: `src/api/storage.py`

**Intent**: Replace independent write-and-commit helpers for account creation and
membership updates with lifecycle-specific methods that persist the mutation and its
audit event in one transaction.

**Contract**: Provide typed repository operations for: provisioning a non-administrator
user with its required initial membership; listing users and their active state; setting
a non-administrator account active/inactive; creating a project; creating a missing
membership; updating an existing membership role; and deleting a membership. Each write
records its immutable audit event inside the same session, includes actor, target,
project where applicable, and includes prior/new role or active state when it changes.
A returned membership must continue to be unique per `(project_id, user_id)`.

#### 3. Canonical identity helpers and bootstrap parity

**Files**: `src/api/schemas.py`, `src/api/security.py`, `src/api/bootstrap.py`

**Intent**: Apply one validation and lowercase-normalization rule consistently to
browser login, administrator provisioning, and first-administrator bootstrap so no
account can be created that the login API cannot recognize.

**Contract**: Usernames remain 3–64 characters matching the existing permitted
character set; normalize to lowercase before lookup and persistence. Bootstrap uses the
same validation/normalization path, creates only an active Administrator, and writes
its bootstrap audit record transactionally. Password hashing, JWT algorithm, and the
30-minute default lifetime remain unchanged.

### Success Criteria:

#### Automated Verification:

- Focused migration tests prove the fresh initial schema is idempotent, initializes
  active state, accepts normalized lowercase identities, and rejects duplicate names.
- Focused repository tests prove each account/membership mutation rolls back when its
  audit insert fails.
- `ruff check src/api tests/test_api.py` and `mypy` pass.

#### Manual Verification:

- Remove a disposable local API metadata database, rerun migrations, and confirm the
  bootstrapped Administrator and provisioned users can sign in using case-insensitive
  input.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that the manual migration checks succeeded before
proceeding.

---

## Phase 2: Administration API contract

### Overview

Expose precise, Administrator-only HTTP contracts for the agreed account lifecycle while
preserving project isolation, anti-enumeration behavior, and absent public sign-up.

### Changes Required:

#### 1. Account and membership request/response schemas

**File**: `src/api/schemas.py`

**Intent**: Define explicit validated contracts for provisioning a project account,
account state changes, account listings, membership details with user state, and
role-changing requests.

**Contract**: The provision request requires `username`, `password`, `project_id`, and
one `ProjectRole`; it has no `is_administrator` input. Membership detail responses
provide the associated non-secret user identity and active state needed by the
Administrator UI. Activation input is a boolean state transition; role update input is
exactly `operator` or `publisher`; unspecified fields remain rejected. Account-list
responses contain only `id`, canonical `username`, `is_active`, and `created_at`.

#### 2. Protected lifecycle routes and authorization guards

**File**: `src/api/main.py`

**Intent**: Replace the incomplete two-step provisioning surface with the atomic
project-account endpoint and add endpoints for discovery, membership lifecycle,
account activation, and system audit review.

**Contract**: Require the existing Administrator dependency for every new or changed
administration route. Remove `POST /admin/users` and replace it with
`POST /admin/project-accounts`, whose request is the provision contract above and
whose response includes the new account plus its initial membership. Add
`GET /admin/users`; `PATCH /admin/users/{user_id}/activation`; create-only
`POST /projects/{project_id}/members` for an existing account; role-changing
`PATCH /projects/{project_id}/members/{user_id}`; and revoking
`DELETE /projects/{project_id}/members/{user_id}`. A duplicate membership is a 409,
and a role update or revoke of no existing membership is a 404.

Retain `GET /projects/{project_id}/members` with enriched membership/account-state
responses and the existing `GET /projects/{project_id}/audit-events` behavior. Add
`GET /admin/audit-events`, returning Administrator-visible user-resource events
(including bootstrap, provisioning, sign-in, deactivation, and reactivation) whether
or not they carry a project ID; project membership events remain in their associated
project audit trail. Use distinct operations and audit action names for membership
granted, role changed, membership revoked, account deactivated, and account
reactivated. Return a clear conflict for a normalized duplicate username; return 404
for missing target records; reject deactivation/reactivation of an Administrator
through this project-account workflow. Login and `get_current_user` must reject
inactive accounts with the existing generic 401 response, and role checks must
continue to query current membership on each request. Update the documented API
workflow and API-test helpers as part of this replacement. Retain `POST /projects`,
but route it through the same transaction-scoped project-plus-audit operation.

#### 3. Administration-focused API coverage

**File**: `tests/test_api.py`

**Intent**: Extend the existing fixture/helper style to prove access and audit invariants
through HTTP rather than testing implementation details alone.

**Contract**: Cover unauthenticated and non-administrator denial; no public registration
route; atomic account-plus-initial-membership provision; normalized duplicate behavior;
mixed roles for one account across two projects; Publisher-as-Operator inheritance;
separate role-change and revoke semantics; immediate authorization denial after revoke
or deactivation using a previously issued token; reactivation; correct project and
system audit visibility; and rollback of account, membership, and project creation
when an audit insertion fails. Keep the established 401/403/404 distinction and
HDFS-only API fixture.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py` passes the existing API behavior plus all
  account-lifecycle, isolation, and atomic-audit cases.
- `ruff check src/api tests/test_api.py` and `mypy` pass.
- Generated OpenAPI exposes the named Administrator-only lifecycle routes, no
  unauthenticated account-provisioning or membership mutation operation, and no
  retained `POST /admin/users` route.

#### Manual Verification:

- Sign in as the bootstrapped Administrator and exercise every lifecycle API operation
  through `/docs`; verify non-administrator credentials cannot use them.
- Confirm project audit events include the associated membership action and the system
  audit view includes provisioning and account activation-state transitions.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that the manual API checks succeeded before
proceeding.

---

## Phase 3: Administrator interface

### Overview

Make the protected lifecycle available in the existing React Administration view without
moving authorization decisions to the browser.

### Changes Required:

#### 1. Typed administration API client

**File**: `frontend/src/api.ts`

**Intent**: Add TypeScript representations and API-client methods for the narrow account
and membership contracts introduced in Phase 2.

**Contract**: The client can list non-secret account state, provision a project account,
list selected-project memberships with user details, grant a membership to an existing
account, update a role, revoke a membership, set account active state, and read
system-level audit events. It continues to attach the bearer token but makes no local
authorization decision and surfaces server error messages via the existing `ApiError`.

#### 2. Selected-project account-management controls

**File**: `frontend/src/App.tsx`

**Intent**: Extend `AdministrationView` so an Administrator can complete the S-01
workflow from the currently selected project and see its current state after every
successful mutation.

**Contract**: Add a provision form requiring username, compliant password, and initial
Operator/Publisher role; a project-member list showing username, account state, and
role; controls to grant existing users, change a role, revoke membership, and
activate/deactivate non-administrator accounts; and a system-audit panel. Preserve
current sign-in/session-expiry handling, selected-project refresh behavior, accessible
form labels, disabled states while requests are pending, and inline error/success
feedback. Refresh server state after mutations rather than mutating authority state
optimistically.

#### 3. Administration presentation styles

**File**: `frontend/src/styles.css`

**Intent**: Add only the layout and state styles needed for the new account-management
cards, membership list, and destructive/reversible action controls while preserving the
existing visual system.

**Contract**: Active/inactive and role labels are legible without color alone; revoke and
deactivate actions are visibly distinguished from non-destructive updates; narrow
viewports retain usable labels and controls.

### Success Criteria:

#### Automated Verification:

- `cd frontend && npm run build` completes without TypeScript or production-build
  errors.
- Phase 2 endpoint-level API contract tests pass before this client is connected to
  the new lifecycle routes.

#### Manual Verification:

- As an Administrator, provision a lowercase Operator and Publisher into the selected
  project; sign in as each and confirm they see only their authorized project behavior.
- Grant an existing account a different role in a second project, change a role, revoke
  its first membership, deactivate/reactivate the account, and confirm each result
  refreshes correctly.
- Confirm an Operator/Publisher cannot reach account controls and that failed form
  submissions present a safe, actionable server message.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that the manual UI checks succeeded before
proceeding.

---

## Phase 4: Verification and documentation

### Overview

Lock in the authorization boundary, provide an operator-facing setup path, and reconcile
the now-resolved account-access documentation.

### Changes Required:

#### 1. API and deployment documentation

**Files**: `README.md`, `context/foundation/prd.md`, `context/deployment/deploy-plan.md`

**Intent**: Document the implemented username/password JWT sign-in decision, the
CLI-only bootstrap boundary, and the account/membership administration workflow without
claiming unsupported recovery, inference, or broader log-source functionality.

**Contract**: Replace the PRD’s stale “sign-in method undecided” question with the
implemented decision. Document lowercase usernames, initial project-role provisioning,
membership lifecycle, activation/reactivation semantics, and audit visibility. Retain
the explicit no-public-sign-up and HDFS-only statements, never record credentials in
examples, and preserve the deployment guide's interactive bootstrap instruction.

#### 2. Full change verification

**Files**: `tests/test_api.py`, `frontend/`, `README.md`

**Intent**: Run the project’s established checks and record any platform limitation
accurately before considering S-01 complete.

**Contract**: Verify the API and artifact test targets used by CI, all configured Ruff
and mypy checks, and the frontend production build. Native ML-dependent tests remain
outside this account-access change; when run in the restricted environment, distinguish
native-library sandbox failures from assertion failures rather than changing the
Intel-compatible lockfile.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_api.py tests/test_artifacts.py` passes.
- `ruff check src tests scripts run_ablation.py` and `mypy` pass.
- `cd frontend && npm ci && npm run build` passes.

#### Manual Verification:

- Follow the documented local bootstrap, Administrator sign-in, project-account
provisioning, membership change, revocation, deactivation, reactivation, and audit
review flow without using undocumented database operations.
- Review the docs and OpenAPI to confirm there is no public sign-up route or
Administrator-creation control in the browser workflow.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that the manual end-to-end checks succeeded before
declaring the change ready to archive.

## Testing Strategy

### Unit Tests:

- Fresh-schema behavior for lowercase unique usernames and active-state defaults.
- Repository transaction rollback when a forced audit write fails.
- Shared username validation/normalization used by both API and CLI bootstrap.

### Integration Tests:

- Administrator-only atomic provisioning and immediate assigned role.
- Correct authorization after membership grant, role transition, membership revocation,
  deactivation, and reactivation with already-issued JWTs.
- Account and membership actions remain visible only through their intended project or
  system audit endpoint.
- Existing HDFS model/analysis authorization tests retain their established 401, 403,
  and 404 outcomes.

### Manual Testing Steps:

1. Bootstrap the first Administrator by CLI; sign in through the same-origin UI and
   create a project account with each allowed role.
2. Sign in as each project account and attempt allowed, prohibited, and cross-project
   actions.
3. Use the Administrator UI to alter role, grant another project, revoke membership,
   deactivate, and reactivate; review both audit surfaces after every action.
4. Submit malformed and duplicate usernames/passwords and verify no account, membership,
   or audit partial state appears.

## Performance Considerations

The confirmed MVP scale is one administrator/user and low request volume. Account,
membership, and audit lists may be straightforward bounded queries for this slice; do
not introduce caching, polling, background workers, or pagination until real scale
requires them. Preserve the existing per-request user/membership lookup because it is
the mechanism that makes revocation and deactivation take effect immediately.

## Migration Notes

This is an unreleased, disposable metadata state. Before implementation verification,
remove the local API database and rerun `python -m src.api.migrations` so it is created
from the revised initial schema. The first Railway deployment applies the same initial
schema to an empty PostgreSQL database. Do not use this approach after any environment
holds accounts, projects, models, runs, or audit records; a future deployed migration
must be planned separately as an additive, backward-compatible change.

## References

- Product requirements: `context/foundation/prd.md:87-102,147-156`
- Roadmap slice: `context/foundation/roadmap.md:127-138`
- Existing authentication and authorization: `src/api/main.py:53-102`
- Current user/membership persistence: `src/api/storage.py:101-174`
- Existing test conventions: `tests/test_api.py:24-74,119-153`
- Existing Administrator UI: `frontend/src/App.tsx:672-795`
- Deployment bootstrap boundary: `context/deployment/deploy-plan.md:112-121`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Account persistence and transactional audit

#### Automated

- [x] 1.1 Focused migration tests prove the fresh initial schema is idempotent, initializes active state, accepts normalized lowercase identities, and rejects duplicate names
- [x] 1.2 Focused repository tests prove each account/membership mutation rolls back when its audit insert fails
- [x] 1.3 `ruff check src/api tests/test_api.py` and `mypy` pass

#### Manual

- [x] 1.4 Remove a disposable local API metadata database, rerun migrations, and confirm the bootstrapped Administrator and provisioned users can sign in using case-insensitive input

### Phase 2: Administration API contract

#### Automated

- [ ] 2.1 `python -m pytest tests/test_api.py` passes the existing API behavior plus all account-lifecycle, isolation, and atomic-audit cases, including rollback of account, membership, and project creation when an audit insertion fails
- [ ] 2.2 `ruff check src/api tests/test_api.py` and `mypy` pass
- [ ] 2.3 Generated OpenAPI exposes the named Administrator-only lifecycle routes, no unauthenticated account-provisioning or membership mutation operation, and no retained `POST /admin/users` route

#### Manual

- [ ] 2.4 Sign in as the bootstrapped Administrator and exercise every lifecycle API operation through `/docs`; verify non-administrator credentials cannot use them
- [ ] 2.5 Confirm project audit events include the associated membership action and the system audit view includes provisioning and account activation-state transitions

### Phase 3: Administrator interface

#### Automated

- [ ] 3.1 `cd frontend && npm run build` completes without TypeScript or production-build errors
- [ ] 3.2 Phase 2 endpoint-level API contract tests pass before this client is connected to the new lifecycle routes

#### Manual

- [ ] 3.3 As an Administrator, provision a lowercase Operator and Publisher into the selected project; sign in as each and confirm they see only their authorized project behavior
- [ ] 3.4 Grant an existing account a different role in a second project, change a role, revoke its first membership, deactivate/reactivate the account, and confirm each result refreshes correctly
- [ ] 3.5 Confirm an Operator/Publisher cannot reach account controls and that failed form submissions present a safe, actionable server message

### Phase 4: Verification and documentation

#### Automated

- [ ] 4.1 `python -m pytest tests/test_api.py tests/test_artifacts.py` passes
- [ ] 4.2 `ruff check src tests scripts run_ablation.py` and `mypy` pass
- [ ] 4.3 `cd frontend && npm ci && npm run build` passes

#### Manual

- [ ] 4.4 Follow the documented local bootstrap, Administrator sign-in, project-account provisioning, membership change, revocation, deactivation, reactivation, and audit review flow without using undocumented database operations
- [ ] 4.5 Review the docs and OpenAPI to confirm there is no public sign-up route or Administrator-creation control in the browser workflow
