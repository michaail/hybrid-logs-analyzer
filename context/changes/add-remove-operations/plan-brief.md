# Add remove operations for models and datasets — Plan Brief

> Full plan: `context/changes/add-remove-operations/plan.md`

## What & Why

Create/Read exist for HDFS model versions and uploaded datasets; models also have
publish. There was no public DELETE. Authorized remove completes CRUD for those
two item types without cascading analysis history.

## Starting Point

`delete_model_version` already fail-closes when `analysis_runs` reference the
version. CLI `retire_v1` deletes object prefixes then the row; it is not a public
API. Membership revoke is the HTTP 204 + transactional audit pattern. The React
client already treats HTTP 204 as empty success.

## Desired End State

- `DELETE /projects/{project_id}/models/{model_version_id}` → 204 for a
  same-project Publisher when no analysis run references the version.
- `DELETE /projects/{project_id}/datasets/{dataset_id}` → 204 for a same-project
  Operator (Publisher counts as Operator) when no analysis run references the
  dataset.
- Success writes `model.deleted` / `dataset.deleted` in the same DB transaction
  as the row delete, then removes object prefixes.
- Referenced resources return 409 unchanged. React confirm dialogs show
  403/409 as `role="alert"` with no success copy.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
| -------- | ------ | ---------------- |
| Referenced resources | HTTP 409, no cascade | Analysis history must stay; FKs have no ON DELETE CASCADE |
| Object vs DB order | Commit row + audit first, then prefixes | Prefer leftover objects over dangling metadata |
| Roles | Publisher deletes models; Operator deletes datasets | Matches register/publish vs upload |
| UI visibility | Remove stays visible | Hiding is not the security control |
| Tests | HTTP + Vitest, no Playwright | Isolation/409 oracles belong in pytest |

## Scope

**In scope:** Storage helpers, two DELETE routes, object-prefix cleanup, React
confirm dialogs, isolation/role tests, README.

**Out of scope:** Deleting runs/results/audit; CASCADE; Playwright; soft-delete
columns; public unpublish; dataset PATCH; project delete.

## Architecture / Approach

Fail-closed integrity check inside the deleting transaction. Commit metadata
delete first, then `object_store.delete_prefix`. Unshared preprocessing bundles
are removed with the last model that referenced them.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| ----- | ---------------- | -------- |
| 1. Persistence and HTTP DELETE | Storage + routes + pytest oracles | Shared bundle prefix deleted too early |
| 2. React confirm dialogs | api.ts, Dialog, Vitest deny-copy | 403/409 looking like success |
| 3. Documentation | README + 10x change folder | Claiming cascade delete of runs |

**Prerequisites:** Branch `feature/add-remove-operations`; existing 204 membership
revoke and `delete_model_version` fail-closed helper.
**Estimated effort:** One implementation pass across 3 phases.

## Open Risks & Assumptions

- Best-effort object cleanup after a committed row delete can leave orphans.
- Administrators pass `require_project_role` and can delete, consistent with
  other member routes.

## Success Criteria (Summary)

- Unused eligible and published models, and unused datasets, delete with 204.
- Referenced resources stay 409 with rows and objects unchanged.
- Operator model Remove stays visible and shows a 403 alert.
