# Local Compose MVP Acceptance — Plan Brief

> Full plan: `context/changes/local-compose-mvp-acceptance/plan.md`
> Research: `context/changes/local-compose-mvp-acceptance/research.md`

## What & Why

The HDFS MVP still has no reproducible local deployment: images exist, but docs and Railway IaC are not a proven stack. This change adds a top-level Compose environment and records trusted-parity plus Compose/PostgreSQL acceptance evidence so those claims match the implementation, without treating Railway as validated or committing binaries.

## Starting Point

Three Dockerfiles and validator/inference HTTP wiring already exist. The only Compose file is a Postgres-16 harness on host `5433` for two dialect tests. Factory register needs validator URL+token. v3 artefacts and the F-03 catalog are gitignored and checksum-pinned.

## Desired End State

An operator can bring up postgres, migrate, web, inference, and model-validator; bootstrap the first admin with the existing CLI; publish the trusted v3 pair; run analysis against PostgreSQL; and point at a committed markdown record. Railway stays an unexecuted future design.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Postgres host port | Publish MVP Postgres on `5433`; point `TEST_DATABASE_URL` at it | One database for dialect tests and acceptance | Plan |
| Catalog mount | Env host path the operator must already have | No copying gitignored trees into the repo | Plan |
| Missing v3 | Fail closed | Fixture v2 must not be recorded as trusted-release proof | Plan |
| Docs breadth | README, deploy-plan, infrastructure.md, tech-stack.md | Stop agents treating Railway as the verified MVP host | Plan |
| Acceptance record | `acceptance-record.md` in this change folder | Archives with the work; no extra foundation source of truth | Plan |
| Operator log | Committed `hdfs_inference_release/hdfs.log` | Acceptance can upload a valid HDFS file without the full corpus | Plan |
| Recorded failures | Happy path + validator 503 + catalog mismatch | Those two negatives are the easy false “green stack” | Plan |
| Web port | `localhost:8000` → container 8080 | Matches README’s API origin; images keep PORT 8080 | Plan |
| Image digests | Run evidence, not a lockfile | Rebuilds churn; git commit + compose.yaml are the identity | Plan |
| Topology / isolation | Five services; validator off the object volume; no pre-seed | Locked in alignment + research | Research |
| FR-011 vs Compose run | Parity script is FR-011; fixture-log run is not | Golden fixture is not the labelled baseline | Research |

## Scope

**In scope:** Root `compose.yaml` + `compose.env.example`; contract test; doc reframe; fail-closed evidence record; stamp `compose-acceptance` and `verify-evidence`.

**Out of scope:** Railway apply; committing binaries; pre-seeding rows; fixture v2 as recorded publish; macos lockfile; new product APIs; Playwright as Compose proof; digest lockfile.

## Architecture / Approach

Reuse existing images. Compose DNS replaces Railway private URLs; a named volume replaces the Bucket for web+inference. Catalog is a read-only host bind into inference only. Hardcode container `DATABASE_URL` to the Postgres service so developer SQLite `.env` cannot poison the stack. Always `docker compose --env-file compose.env`.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Compose stack and env template | Five-service compose, template, isolation test | Host `.env` sqlite interpolation; 5433 clash with tests/postgres |
| 2. Documentation reframe | Compose-first README/deploy/infra/stack | Partial reframe leaves Railway as “the” MVP |
| 3. Evidence run and record | Parity + Compose procedure + `acceptance-record.md` | Missing v3/catalog; sandbox `@ml` mistaken for proof |

**Prerequisites:** Docker; filled `compose.env`; F-03 catalog tree + SHA; v3 ZIP pair on disk; ML venv for parity / `@ml`.
**Estimated effort:** ~3 sessions (compose, docs, local evidence gate).

## Open Risks & Assumptions

- Golden fixture log may barely overlap the F-03 catalog; provisional-heavy results are acceptable and are not FR-011.
- `5433` is an explicit exception to “only web publishes a host port.”
- `tests/postgres/compose.yaml` and the MVP stack must not run together.

## Success Criteria (Summary)

- Compose config/test proves isolation and ports `8000` + `5433`.
- Active docs call Compose the MVP proof and Railway unexecuted.
- `acceptance-record.md` exists with commit, digests, checksums, run/audit IDs; no binaries in Git.
