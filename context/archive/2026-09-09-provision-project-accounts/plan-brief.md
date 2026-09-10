# Provision project-authorized accounts — Plan Brief

> Full plan: `context/changes/provision-project-accounts/plan.md`

## What & Why

S-01 completes the administrator-operated account workflow for the HDFS-only web MVP.
An Administrator will provision a non-administrator account with its first project role,
then safely manage project access and account activation without any public sign-up path.

This builds on existing FastAPI authentication and project authorization rather than
creating another identity system. It closes the gap between API-only primitives and the
workflow required to authorize the Publishers and Operators used by later roadmap slices.

## Starting Point

The API already has password/JWT sign-in, an Administrator bootstrap command,
administrator-only user creation, and project-local `operator`/`publisher` memberships.
The React Administration view creates projects and displays project audit events, but
cannot provision or manage accounts; account creation, membership writes, and audit
writes are currently separate transactions.

## Desired End State

Within the selected project's Administration view, an Administrator can create a
lowercase-username Operator or Publisher account with initial access in one atomic
operation. They can later grant a user another project role, change a role, revoke a
membership, or deactivate/reactivate a non-administrator account.

The API remains the authorization authority. An existing JWT immediately loses access
when its membership is revoked or its account is deactivated, and every privileged
mutation is represented in the relevant audit history.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Account lifecycle | Reversible account deactivation plus project-membership lifecycle | Preserves historical records while allowing an Administrator to remove and restore access safely. |
| Initial access | Atomically create account, initial membership, and audit event | Prevents a failed audit or partial request from leaving an unauthorized or untraceable state. |
| Login identity | Lowercase canonical usernames | Avoids confusing `Alice`/`alice` duplicate accounts and makes sign-in predictable. |
| Administrator boundary | UI provisions only Operator/Publisher accounts | Keeps global Administrator bootstrap out of the browser and avoids expanding S-01 into peer-admin governance. |
| Role changes | In-place membership update with before/after audit | Distinguishes privilege changes from first-time grants without a temporary access gap. |
| Audit visibility | Project audit plus Administrator-only system audit | Makes membership events useful to project oversight while keeping account-state events discoverable. |
| User experience | Extend selected-project Administration view | Reuses the product’s established project selection and keeps a single thin API client. |

## Scope

**In scope:**
- Revised unreleased initial schema for canonical usernames and active account state
- Transactional account/membership mutations with immutable audit records
- Administrator-only lifecycle API and system audit listing
- React controls for project account and membership management
- Focused API, migration, authorization, and build verification

**Out of scope:**
- Public registration, invitations, password recovery, MFA, SSO, or browser-created Administrators
- Account or audit deletion
- Model loading, model publication changes, dataset intake, inference, or non-HDFS support

## Architecture / Approach

The storage layer gains additive identity state and transactional lifecycle operations. FastAPI
validates and authorizes narrow administration requests, deriving effective permissions from
the current database state on every protected request. The React Administration view calls
those API operations, refreshes server state after a mutation, and never decides permissions
locally.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Persistence and audit | Canonical identity, active state, and atomic writes | Disposable metadata must be reset before the revised initial schema is used. |
| 2. Administration API | Protected lifecycle operations and audit endpoints | Must preserve authorization status-code and isolation conventions. |
| 3. Administrator interface | Selected-project account-management workflow | UI must accurately refresh state after access changes. |
| 4. Verification and docs | Regression proof and reconciled access documentation | Native ML checks are unrelated and must not prompt lockfile changes. |

**Prerequisites:** Existing FastAPI, React client, migrations, and CLI bootstrap remain in
place; no model or inference prerequisite applies.
**Estimated effort:** ~2–3 focused sessions across four phases.

## Open Risks & Assumptions

- The current metadata state remains disposable until first deployment. Once an
  environment holds real records, a later identity-schema change needs a separately
  planned backward-compatible migration.
- Audit immutability is enforced by the application API; database administrators remain trusted
  operators for this MVP.
- There are no frontend unit tests today, so production build checks plus defined manual flows
  provide the UI verification baseline.

## Success Criteria (Summary)

- An Administrator can fully provision and manage project access through the protected UI.
- Operator, Publisher, project-isolation, revocation, and deactivation rules are proven by API tests.
- Every lifecycle change is atomically auditable and the documented bootstrap/sign-in path is accurate.
