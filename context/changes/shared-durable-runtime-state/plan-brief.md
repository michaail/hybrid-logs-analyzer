# Shared durable runtime state — Plan Brief

> Full plan: `context/changes/shared-durable-runtime-state/plan.md`

## What & Why

F-01 gives the deployed HDFS workflow a shared, durable ownership and version
boundary for models, datasets, runs, and results. Later slices (publish, intake,
inference, inspect) must not coordinate through a local workspace directory or a
SQLite file that two services cannot share.

## Starting Point

FastAPI already stores project-scoped model versions and analysis runs in
SQLite-or-PostgreSQL, and Railway already supplies `DATABASE_URL`. Those rows still
point at trusted-workspace paths, datasets are not first-class, anomaly rows are
never written, and model/run audit is a second transaction. S-01 already owns
`001_initial_schema` identity columns.

## Desired End State

A migrated database records kinded pointers (`workspace` | `object`), project-owned
datasets, expanded run statuses, and stored result summaries. Operators can list
datasets and see `dataset_id` on runs. Public HTTP still validates HDFS logs and
writes only `rejected` / `not_supported`. Inference and Bucket uploads remain later
slices; this change only makes their shared state possible.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Scope | Schema + repository + additive HTTP; no Bucket/upload/inference | Unlocks S-02–S-05 without stealing those workflows |
| Pointers | Kinded opaque reference + checksum | Current path flow keeps working; object kind is ready for S-02/S-03 |
| Datasets | First-class project-owned table now | Avoids rewriting run ownership in S-03 |
| Migration | Additive `002` | Does not undo S-01's `001` identity schema |
| Statuses | Expand enum now; HTTP still writes the two terminals | S-04 can CAS without another CHECK fight |
| Results | Durable rows + `results_summary_json` | GET reads stored data; S-05 does not invent a second contract |
| Checksums | Required for `object`, null for workspace logs | Protects the two-second ack budget on large HDFS files |
| Dataset identity | `(project, storage_kind, reference)` | Reuse stored datasets without content-hashing |
| Writes | Atomic audit + CAS; no public result writer | Matches S-01; cannot forge anomalies over HTTP |
| Postgres tests | Docker harness + `TEST_DATABASE_URL`; CI stays SQLite | Dialect proof without slowing the default suite |
| HTTP | Additive fields + GET datasets | Visible ownership without breaking `log_reference` clients |

## Scope

**In scope:**
- Migration `002`, datasets, kinded pointers, expanded statuses, stored summaries
- Atomic repository writes, status CAS, result insert for tests/future inference
- Additive API fields and Operator dataset GET
- React types, read-only dataset list, docs, local Postgres compose

**Out of scope:**
- Bucket adapter, uploads, F-02 package contract, inference execution
- Hashing workspace HDFS logs; public result/status write routes
- Notebook ArtifactStore; BGL; deleting product records

## Architecture / Approach

Keep `ApiDatabase` as the dual-dialect store. PostgreSQL is the deployed shared
state; SQLite remains local/dev. Bytes stay outside the DB. HTTP upserts a
workspace-kind dataset from today's `log_reference`. A future inference process
will CAS run status and write results through the same repository, not a public
API.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Schema + PG harness | `002` + local Docker Postgres | SQLite cannot ALTER CHECK; run table must be rebuilt |
| 2. Repository | Upsert, atomic audit, CAS, result writes | Illegal transitions or two-phase audit would leak state |
| 3. Additive HTTP | Dataset GET, analyze upsert, stored summaries | Must not change `not_supported` walking-skeleton behavior |
| 4. Client + docs | Types, read-only dataset list, accurate gates | UI must not imply upload or completed inference |

**Prerequisites:** S-01 schema (`001`) and existing FastAPI/React walking skeleton.
**Estimated effort:** ~2–3 sessions across four phases.

## Open Risks & Assumptions

- Local `.api/analyzer.db` is still disposable and should be reset after `002`.
- If Railway staging already applied `001`, `002` must apply forward, not rewrite.
- Postgres-marked tests can rot if nobody runs the compose harness; the plan
  documents it rather than adding Postgres to GitHub Actions.
- Object-kind rows are repository/test-only until S-02/S-03 supply real keys.

## Success Criteria (Summary)

- Models, datasets, runs, and results are project-owned, versioned, and migratable
  on SQLite and PostgreSQL.
- Operators can list stored datasets and inspect stored summaries; valid HDFS
  analysis still ends `not_supported`.
- No public way to forge results or attach Bucket credentials in this change.
