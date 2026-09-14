---
date: 2026-09-14T00:45:46+02:00
researcher: michalklos
git_commit: 62f4f6b1820f52f90bbdae47bdfe51ced2842237
branch: feature/mvp-alignment
repository: hybrid-logs-analyzer
topic: "local-compose-mvp-acceptance (Compose MVP stack plus trusted-parity and PostgreSQL evidence)"
tags: [research, codebase, compose, docker, postgres, inference, model-validator, parity, deployment]
status: complete
last_updated: 2026-09-14
last_updated_by: michalklos
---

# Research: local-compose-mvp-acceptance (Compose MVP stack plus trusted-parity and PostgreSQL evidence)

**Date**: 2026-09-14T00:45:46+02:00
**Researcher**: michalklos
**Git Commit**: 62f4f6b1820f52f90bbdae47bdfe51ced2842237
**Branch**: feature/mvp-alignment
**Repository**: hybrid-logs-analyzer

GitHub permalinks are omitted: `feature/mvp-alignment` is ahead of origin; this commit is not the pushed tip.

## Research Question

Add the local Compose MVP environment and record trusted-parity plus PostgreSQL acceptance evidence. Source: `context/foundation/mvp-alignment-plan.md`

## Summary

There is **no top-level Compose stack**. Images for `web`, `inference`, and `model-validator` already exist; Railway IaC already names the same three services plus Postgres and a Bucket. The only Compose file is `tests/postgres/compose.yaml` — a disposable Postgres 16 on host `5433` for two `@pytest.mark.postgres` tests. That harness is dialect proof, not MVP deployment proof.

The locked Compose target in `mvp-alignment-plan.md` is: `postgres`, one-shot `migrate`, `web`, private `inference`, private `model-validator`; **only `web` publishes a host port**; a **named filesystem volume** shared by web and inference; validator gets **neither** that volume nor JWT/DB/Bucket; F-03 catalog bind-mounted **read-only into inference**; trusted v3 packages admitted through the Publisher API, not pre-seeded rows.

Factory `uvicorn` / the web image use `ApiSettings.from_environment()` with **no** `model_validator_command`. Register is **503** unless `MODEL_VALIDATOR_SERVICE_URL` + `MODEL_VALIDATOR_INTERNAL_TOKEN` are set together. `scripts/e2e_serve.py` injects a files-only command and SQLite under `.e2e/` — it is UI smoke, not Compose acceptance.

Trusted parity is already specified: run `scripts/verify_hdfs_parity.py` against paths in `context/foundation/hdfs-parity-baseline.md`; write `releases/hdfs/v3/parity-report.json` (gitignored). Commit only a text acceptance record (commit SHA, image digests, checksums, migration version, command results, run/audit IDs). Do not commit binaries.

README, `deploy-plan.md`, `infrastructure.md`, and `tech-stack.md` still center Railway. Alignment already decided: Compose is the MVP’s reproducible proof; Railway stays unexecuted future design.

## Detailed Findings

### Current images and topology

Three Dockerfiles, no root `compose.yaml`:

| Image | File | Runtime | Must not receive |
| --- | --- | --- | --- |
| Public API + built React | `Dockerfile` | `requirements-api.txt`, `uvicorn src.api.main:create_app --factory`, `${PORT:-8080}` | Torch; JWT/DB are env, not baked in |
| Private inference | `Dockerfile.inference` | `python -m src.inference_service`, `PORT=8080` | `API_JWT_SECRET`; catalog not in image (`.dockerignore` excludes `artifacts/`) |
| Private validator | `Dockerfile.validator` | `python -m src.model_validator.service`, `PORT=8080` | JWT, `DATABASE_URL`, Bucket keys (`src/model_validator/settings.py:10-36`) |

`.dockerignore` excludes `.env`, `.venv`, `.api`, `data/`, `artifacts/`, `models/`, `outputs/`, `runs/`, `tests`, notebooks.

Railway (`.railway/railway.ts:8-82`) already models the graph Compose must reproduce locally, with two substitutions:

- Bucket `sharedStore` → named filesystem volume + `API_OBJECT_STORE_ROOT`
- `web.preDeploy: python -m src.api.migrations` → **one-shot `migrate` service**
- Private DNS `http://inference.railway.internal:8080` / `http://model-validator.railway.internal:8080` → Compose service DNS on the default network
- Catalog as Bucket key `hdfs/reference-catalog/manifest.json` → **read-only bind-mount** + local path in `INFERENCE_HDFS_COMPLETENESS_MANIFEST`

Validator and inference both listen on container `8080`; that is fine behind Compose DNS. Host mapping should not publish either. Local README already uses validator host `8081` only when processes share the host network.

### Secrets, object store, catalog, validator isolation

**Together-or-neither (web `ApiSettings.from_environment`)** — `src/api/settings.py:55-199`:

- `API_JWT_SECRET` and `DATABASE_URL` required
- Bucket quartet all four or none
- `INFERENCE_SERVICE_URL` + `INFERENCE_INTERNAL_TOKEN` together or neither
- `MODEL_VALIDATOR_SERVICE_URL` + `MODEL_VALIDATOR_INTERNAL_TOKEN` together or neither
- `model_validator_command` is **not** loaded from env (constructor/injection only)

**Inference** — `src/inference_service/settings.py:59-123`: token + `DATABASE_URL` required; no JWT; F-03 pair **must both be set**. If the manifest value is an existing file → local path mode; otherwise treat as object key. `__post_init__` forbids both path and key.

**Validator** — token required; startup raises if JWT/DB/Bucket env is present; `scrub_environment()` on factory create (`src/model_validator/service.py:26-28`). `API_OBJECT_STORE_ROOT` is **not** in the forbidden list — Compose must still **not mount** the object volume there.

**Object keys** (`src/api/object_store.py:77-137`): `projects/<pid>/models|datasets|preprocessing-bundles/...`; F-03 catalog is **not** project-scoped (`hdfs/reference-catalog/manifest.json`). Local share = same `API_OBJECT_STORE_ROOT` on web and inference.

**Health**:

- Web `/health`: DB only (`src/api/main.py:174-182`)
- Inference `/health`: DB + `verify_pinned_catalog` → 503 generic if missing/mismatch (`src/inference_service/main.py:42-77`, `src/inference_service/runner.py:379-446`)
- Validator `/health`: liveness, no DB (`src/model_validator/service.py:48-52`)

**Admission** (`src/api/validation.py:167-213`): command if injected; else HTTP ZIP POST; else `ValidatorUnavailableError` → register 503, no row (`src/api/main.py:453-457`).

**Env matrix for Compose**

| Variable | web | migrate | inference | model-validator |
| --- | --- | --- | --- | --- |
| `API_JWT_SECRET` | required | required (`src/api/migrations.py:438-439`) | must not | forbidden |
| `DATABASE_URL` | required | required | required | forbidden |
| `API_OBJECT_STORE_ROOT` | named volume | unused | same volume | do not mount |
| `INFERENCE_SERVICE_URL` + token | Compose DNS + shared token | no | token required | no |
| `MODEL_VALIDATOR_SERVICE_URL` + token | Compose DNS + shared token | no | no | token required |
| F-03 manifest + SHA-256 | must not | no | required (bind-mount path) | must not |

### Acceptance path (existing CLIs/APIs)

Documented host order (`README.md:330-337`): migrations → bootstrap admin → uvicorn. Compose should keep the same CLIs inside services: migrate job, then `python -m src.api.bootstrap` from a one-shot or `docker compose exec web` (password prompt — do not bake a password env; same rule as Railway ssh bootstrap in `deploy-plan.md:168-180`).

HTTP loop that Compose acceptance must exercise:

1. Admin token → create project → provision publisher + operator (`POST /admin/project-accounts`)
2. Publisher `POST /projects/{id}/models` with v2 package ZIP + bundle ZIP → `eligible` + `inference_ready: true` (`src/api/main.py:424-512`, `933`)
3. `POST .../publish` (`531-562`)
4. Operator `POST .../datasets` then `POST .../analysis-runs` → `202 queued` (`577-622`)
5. Poll until `completed|failed`; `GET .../results` vs `GET .../provisional-results` (`687-723`)
6. Audits: `user.bootstrapped`, `model.registered`, `model.published`, `dataset.registered`, `analysis.*`

**Do not pre-seed DB/object rows.** Alignment requires uploading the trusted v3 release through the Publisher flow. Lesson: validate before storage writes; DB row last (`context/foundation/lessons.md` object-store rollback).

**Release vs fixtures**

| Asset | Use in Compose acceptance |
| --- | --- |
| `releases/hdfs/attribute-gae-v3.zip` + preprocessing ZIP | Trusted upload (gitignored; bind-mount read-only into **smoke tooling**, not validator) |
| `tests/fixtures/hdfs_inference_release/` | Golden v2 in Git; useful if v3 binaries are absent locally |
| `scripts/e2e_package.py` | Harmless v2 for UI; not FR-011 proof |
| `tests/fixtures/hdfs_tiny.log` / fixture `hdfs.log` | Bounded Operator upload |

**Negative checks worth recording**

| Failure | Expected |
| --- | --- |
| Validator down / pair unset | Register 503, empty model list |
| Inference pair unset / dispatch exhausted | `202 queued` then `failed` + `INFERENCE_DISPATCH_FAILED` |
| Catalog pin wrong | Inference `/health` 503; run `COMPLETENESS_CATALOG_UNAVAILABLE`; **not** all-provisional |
| Unpublished / not inference-ready | Analyze 409 |

### PostgreSQL coverage today

`tests/postgres/compose.yaml:1-16` — `postgres:16`, `POSTGRESS_USER/PASSWORD/DB=analyzer`, host `5433:5432`, `pg_isready`. No volume (ephemeral).

`TEST_DATABASE_URL` skip gate: `tests/conftest.py:27-31`. **Two** marked tests only:

- `tests/test_migrations.py` — migrate through `008`, healthcheck
- `tests/test_shared_state_repository.py` — dataset uniqueness, checksum CHECK, run CAS

They do **not** cover HTTP admission, validator 503, dispatch, or provisional classification. Default API/E2E is SQLite (`scripts/e2e_serve.py:56-66`).

Planner choice: keep `tests/postgres/compose.yaml` as a lightweight dialect harness **or** point `TEST_DATABASE_URL` at the MVP Compose Postgres (without publishing 5433 if only `web` may publish a host port — pytest would need to run **on the Compose network** or a documented exception for the test harness).

### Parity evidence and gitignore

`scripts/verify_hdfs_parity.py` requires `--model-package`, `--preprocessing-bundle`, `--corpus`, `--labels`, `--expected`; optional `--report` (default beside expected) and `--test-block-ids`. Writes comparison JSON; never mutates `expected.json` (`src/modules/hdfs_parity.py:520-538`).

Pin: `context/foundation/hdfs-parity-baseline.md` — exact `best_threshold`, ±0.01 on `test_f1` / `test_pr_auc` / `test_roc_auc`. Binaries under `releases/`, `data/`, `artifacts/`, `models/hdfs/` are gitignored (`.gitignore:11-19`). Lesson: generated runtime data stays in ignored paths; Git holds path + SHA-256.

Alignment verification list (`mvp-alignment-plan.md:54-56`):

1. `verify_hdfs_parity.py` with explicit paths; retain report outside Git
2. Targeted v2/admission/validator tests; postgres-marked tests; API tests; inference `@ml` in a normal local terminal; lint; mypy; frontend build; Compose acceptance procedure
3. Concise local acceptance record: Git commit, Compose image digests, artifact checksums, migration version (`008` today), command results, run/audit IDs

`@ml` and full-corpus parity are **not** Cursor-sandbox / Ubuntu-CI proof (`AGENTS.md`, `lessons.md` isolated-subprocess rule). Do not treat Playwright files-only e2e as production validator/inference wiring.

### Documentation drift

| Doc | Today | Alignment target |
| --- | --- | --- |
| `README.md` | Host processes + Railway Bucket/catalog; Compose only as postgres test | Compose = local proof; Railway unexecuted |
| `context/deployment/deploy-plan.md` | Railway staging first; validator paragraph already “unexecuted”; Compose “later” | Lead with Compose; demote Railway |
| `context/foundation/infrastructure.md` | Recommend Railway for MVP | Contradicts alignment (not listed in the workstream bullet but must not stay as “MVP hosting”) |
| `context/foundation/tech-stack.md` | Hosting = Railway | Same |
| `.env.example` | SQLite defaults; commented inference/validator/Bucket | Need a **committed Compose env template** (alignment) distinct from `.env.example` |

## Code References

- `Dockerfile:1-27` — public multi-stage API + frontend; PORT default 8080
- `Dockerfile.inference:1-22` — Torch inference; no JWT in settings contract
- `Dockerfile.validator:1-18` — Torch HTTP validator; no DB client
- `.dockerignore:1-22` — drops artifacts, tests, secrets
- `tests/postgres/compose.yaml:1-16` — only Compose file; Postgres 16 on 5433
- `.railway/railway.ts:4-82` — web, inference, model-validator, postgres, Bucket
- `src/api/settings.py:22-199` — JWT/DB required; validator URL+token together or neither; command not from env
- `src/api/validation.py:97-213` — command vs HTTP vs 503
- `src/api/main.py:174-182,424-622,687-723` — health, register, analyze, provisional results
- `src/api/migrations.py:13-31,436-441` — versions `001`–`008`; CLI uses `from_environment`
- `src/inference_service/settings.py:38-123` — F-03 pair; path vs object key
- `src/inference_service/main.py:42-77` — health requires catalog
- `src/model_validator/settings.py:10-42` — refuse JWT/DB/Bucket
- `src/api/object_store.py:12-14,77-165` — prefixes; filesystem vs Bucket
- `scripts/e2e_serve.py:1-70` — files-only validator, disposable SQLite
- `scripts/verify_hdfs_parity.py:21-95` — labelled release gate
- `context/foundation/hdfs-parity-baseline.md:83-125` — pinned paths, FR-011 numbers, verify command
- `.gitignore:11-19` — `releases/`, `artifacts/`, `data/`, `models/`
- `tests/conftest.py:27-31` — skip postgres tests without `TEST_DATABASE_URL`

## Architecture Insights

- **Three runtimes, three images** already match the Compose service split. The missing piece is orchestration, volumes, and an env template — not new application code for process boundaries.
- **Object store is already an abstraction.** Local Compose should set filesystem mode (no Bucket quartet) and mount one named volume at the same `API_OBJECT_STORE_ROOT` on web and inference.
- **Catalog is inference-only.** Bind-mount the fingerprint directory (manifest + `selected-block-ids.txt`) read-only; pin SHA-256. Missing catalog fails the run; it does not dump every block into provisional results.
- **Validator is bytes-in, JSON-out.** It must stay off the object volume. Web posts original ZIP bytes (`src/api/validator_client.py`).
- **Migrate needs JWT+DB** because it uses `ApiSettings.from_environment()`. A one-shot migrate container can use the web image with JWT present; it should not need object-store or inference URLs for SQL apply.
- **Bootstrap is interactive.** Compose acceptance should `exec` bootstrap, not introduce a startup password variable (Railway lesson).
- **E2E and Compose prove different claims.** Files-only SQLite Playwright ≠ Torch validator + inference + Postgres.
- **Railway IaC is a template, not evidence.** Copy topology and env pairing from `.railway/railway.ts`; do not claim private Railway DNS or Bucket behavior as validated.

## Historical Context (from prior changes)

- `context/foundation/mvp-alignment-plan.md` — source: `compose-acceptance` and `verify-evidence` still pending; `retire-v1` / `isolated-validator` done.
- `context/archive/2026-09-13-retire-v1-isolate-validator/` — shipped validator HTTP, `Dockerfile.validator`, unexecuted Railway service; explicitly left Compose and parity re-run out of that change.
- `context/archive/2026-09-13-narrow-hdfs-mvp-contract/` — distilled `hdfs-parity-baseline.md`; out of scope: Compose, re-running parity, committing binaries.
- `context/archive/2026-09-11-run-parity-hdfs-analysis/` — created `verify_hdfs_parity.py` and the baseline; `releases/` gitignored; commit/runtime waived on the pin.
- `context/archive/2026-09-10-publish-hdfs-model-package/` — object-kind packages; live Bucket skippable if unprovisioned.
- `context/archive/2026-09-09-shared-durable-runtime-state/` — introduced `tests/postgres/compose.yaml`.
- `context/archive/2026-09-13-separate-provisional-hdfs-results/` — catalog pin; impl-review warned staging IaC honesty (catalog env vs health).
- `context/archive/2026-09-12-complete-hdfs-block-evaluation-data/` — ignored evaluation artefacts; full corpus not CI.

## Related Research

- `context/archive/2026-09-11-run-parity-hdfs-analysis/research.md` — parity gate and workspace artefacts
- `context/archive/2026-09-10-publish-hdfs-model-package/research.md` — upload/object-store admission
- `context/archive/2026-09-13-fail-undispatchable-analysis-runs/research.md` — dispatch failure path (`INFERENCE_DISPATCH_FAILED`)

## Open Questions

1. **Postgres dual-use:** Keep `tests/postgres/compose.yaml` published on `5433` for `pytest -m postgres`, or run those tests against MVP Compose Postgres without publishing the DB port (pytest in-network / `docker compose exec`)?
2. **Web host port:** Alignment says only `web` publishes a host port. Pick `8080` vs `8000` vs README’s `8000` for local uvicorn — document one.
3. **Catalog source:** Bind-mount `artifacts/cache/hdfs/evaluation-data/<fingerprint>/` from the developer machine, or require operators to copy that tree next to a Compose overlay? The fingerprint is machine-local and gitignored.
4. **v3 binaries absent:** Acceptance procedure if `releases/hdfs/attribute-gae-v3.zip` is not on disk — fail closed and point at the baseline, vs allow fixture v2 for “stack smoke” and require v3 only for the FR-011 record?
5. **Migrate JWT:** One-shot migrate currently needs `API_JWT_SECRET` even though it does not sign tokens. Accept that coupling, or split a JWT-free migrate entrypoint (out of alignment’s “existing CLI” wording — prefer keep `python -m src.api.migrations`).
6. **infrastructure.md / tech-stack.md:** Alignment names README + deploy-plan. Should this change also reframe foundation infra/stack docs so they stop recommending Railway as the verified MVP host?
7. **Evidence location:** Put the acceptance record in `context/changes/local-compose-mvp-acceptance/` (then archive) vs `context/foundation/` vs gitignored workspace with checksums copied into the change folder?
8. **Image digests:** Record `docker compose images` digests after build; rebuilds will churn. Pin compose file + git commit as the reproducible identity; treat digests as run evidence, not a lockfile.
