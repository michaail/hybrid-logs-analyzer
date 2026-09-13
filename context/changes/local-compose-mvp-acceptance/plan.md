# Local Compose MVP Acceptance Implementation Plan

## Overview

Add a top-level Docker Compose stack that is the HDFS MVP’s reproducible deployment proof, reframe active docs so Railway is an unexecuted future design, and record fail-closed local parity plus Compose/PostgreSQL acceptance evidence without committing binaries.

## Current State Analysis

Images for `web`, `inference`, and `model-validator` already exist. `.railway/railway.ts` already names that graph plus Postgres and a Bucket. There is **no** root Compose file. The only Compose definition is `tests/postgres/compose.yaml` (Postgres 16 on host `5433`) for two `@pytest.mark.postgres` tests.

Factory `uvicorn` and the web image use `ApiSettings.from_environment()` with no `model_validator_command`. Register is **503** unless `MODEL_VALIDATOR_SERVICE_URL` and `MODEL_VALIDATOR_INTERNAL_TOKEN` are set together. `scripts/e2e_serve.py` injects a files-only command and SQLite under `.e2e/` — UI smoke, not Compose proof.

Trusted v3 ZIPs, the labelled corpus, and the F-03 catalog live in gitignored workspace paths pinned by `context/foundation/hdfs-parity-baseline.md`. `scripts/verify_hdfs_parity.py` writes `parity-report.json` beside the expected record (also gitignored).

README, `deploy-plan.md`, `infrastructure.md`, and `tech-stack.md` still present Railway as the MVP host.

## Desired End State

An operator with Docker, the pinned workspace artefacts, and this repository can `docker compose --env-file compose.env up`, migrate, bootstrap the first administrator with the existing CLI, register and publish the trusted v3 pair through the Publisher API, upload `tests/fixtures/hdfs_inference_release/hdfs.log`, complete a run against PostgreSQL, and exercise validator-503 and catalog-mismatch failures. Git holds `compose.yaml`, `compose.env.example`, reframed docs, and `acceptance-record.md` (commit, image digests as run evidence, checksums, migration version, command results, run/audit IDs). Git does not hold ZIPs, `.pt` files, logs, or `parity-report.json`. Alignment workstreams `compose-acceptance` and `verify-evidence` are `done`. Railway remains unexecuted.

### Key Discoveries:

- Three Dockerfiles already match the service split; the gap is orchestration, volumes, and an env template (`Dockerfile`, `Dockerfile.inference`, `Dockerfile.validator`).
- Validator settings refuse JWT/DB/Bucket env (`src/model_validator/settings.py`). `API_OBJECT_STORE_ROOT` is not in that denylist — Compose must still **not** mount the object volume on the validator.
- Host `.env` is SQLite-oriented. Compose must **not** interpolate container `DATABASE_URL` from that file; hardcode the Postgres service URL in `compose.yaml`.
- `model_validator_command` is not loaded from the environment; Compose web must set the HTTP URL+token pair.
- F-03 catalog is inference-only; missing or mismatched pin → inference `/health` 503 and run `COMPLETENESS_CATALOG_UNAVAILABLE`, not all-provisional.
- `.gitignore` already ignores `.env.*`, `releases/`, `artifacts/`, `data/`. Name the committed template `compose.env.example` and the local file `compose.env` (and ignore `compose.env`).

## What We're NOT Doing

- Applying or claiming Railway staging, Bucket, private DNS, or cold-start behavior as validated
- Committing generated binaries, Colab exports, `parity-report.json`, or filled `compose.env`
- Pre-seeding database or object-store rows for the trusted release
- Substituting fixture v2 packages for the recorded v3 register/publish
- Regenerating `requirements-macos-intel.lock.txt`
- Adding datasets, APIs, or product features beyond HDFS MVP
- Adding `httpx` to `requirements-api.txt`
- Changing Dockerfiles except if a Compose-only bug is found (not planned)
- A new smoke-container service; acceptance runs from the host against `localhost:8000`
- Treating Playwright / `e2e_serve.py` as Compose or Torch-validator proof
- Schema migrations or `ON DELETE CASCADE`
- A digest lockfile; digests are run evidence only
- A JWT-free migrate entrypoint; keep `python -m src.api.migrations`

## Implementation Approach

Reuse the three existing images and Railway’s env pairing, substituting a named filesystem volume for the Bucket and Compose DNS for `*.railway.internal`. Write a Python contract test that parses `compose.yaml` without a Docker daemon so CI can lock isolation rules. Reframe all four active docs that still call Railway the verified MVP host. Execute evidence on a normal local machine (Docker + ML venv), fail closed if v3 or the catalog tree is missing, and commit only the markdown record.

## Critical Implementation Details

Compose automatically interpolates a project-root `.env`. Do not set container `DATABASE_URL` from `${DATABASE_URL}`. Set it explicitly to the Postgres service (`postgres:5432`) in `compose.yaml`. Always invoke Compose with `--env-file compose.env`.

`tests/postgres/compose.yaml` also binds host `5433`. It remains as a thin dialect harness for people not running the MVP stack; the two Compose files are **mutually exclusive** on that port. When the MVP stack is up, `TEST_DATABASE_URL=postgresql://analyzer:analyzer@127.0.0.1:5433/analyzer`.

Migrate and web need `API_JWT_SECRET` because migrations use `ApiSettings.from_environment()`. Bootstrap stays interactive (`docker compose exec web python -m src.api.bootstrap`); do not add a startup password variable.

The Operator log for the recorded run is the committed golden fixture, not a corpus extract. That run proves stack + Postgres durability + final/provisional split as the catalog allows; it is **not** FR-011. FR-011 is `scripts/verify_hdfs_parity.py` against the baseline paths.

## Phase 1: Compose stack and env template

### Overview

Add the five-service Compose definition, committed env template, gitignore for the local env file, a daemon-free contract test, and a 5433-conflict note on the existing Postgres harness.

### Changes Required:

#### 1. Root Compose file

**File**: `compose.yaml`

**Intent**: Define the MVP stack: `postgres`, one-shot `migrate`, `web`, private `inference`, private `model-validator`.

**Contract**: Services named exactly `postgres`, `migrate`, `web`, `inference`, `model-validator`. Images: `postgres:16`; `Dockerfile` / `Dockerfile.inference` / `Dockerfile.validator` for the app services. `migrate` uses the web image, command `python -m src.api.migrations`, `restart: no`, `depends_on` postgres healthy; web `depends_on` migrate `service_completed_successfully`. Published host ports **only** `8000:8080` (web) and `5433:5432` (postgres). Internal service ports stay `8080`. Named volume for objects mounted on **web and inference only** at a shared `API_OBJECT_STORE_ROOT`. Catalog: read-only bind of `${HDFS_COMPLETENESS_CATALOG_DIR}` into inference; `INFERENCE_HDFS_COMPLETENESS_MANIFEST` is the in-container manifest path; SHA-256 from env. Web `INFERENCE_SERVICE_URL=http://inference:8080` and `MODEL_VALIDATOR_SERVICE_URL=http://model-validator:8080` plus the matching tokens. Validator env is **only** `MODEL_VALIDATOR_INTERNAL_TOKEN` (and `PORT` if required). Validator has no object volume, no `DATABASE_URL`, no `API_JWT_SECRET`, no Bucket keys, no catalog mount. Postgres user/db `analyzer` / password from env so host `TEST_DATABASE_URL` matches the existing dialect tests. Healthchecks: postgres `pg_isready`; web/inference/validator `GET /health`.

#### 2. Env template and local ignore

**Files**: `compose.env.example`, `.gitignore`

**Intent**: Commit placeholders; keep real secrets and the filled file out of Git.

**Contract**: Template lists JWT, Postgres password, inference token, validator token, `HDFS_COMPLETENESS_CATALOG_DIR` (host path the operator must already have), `INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256`. Comments: copy to `compose.env`; generate high-entropy secrets; catalog dir must contain `manifest.json` and sibling `selected-block-ids.txt`; stack will not become inference-healthy until that tree and SHA match; v3 ZIPs are required for the recorded Publisher upload. `.gitignore` adds `compose.env` (do not use a `.env.*` name for the template — that pattern is already ignored).

#### 3. Postgres harness note

**File**: `tests/postgres/compose.yaml`

**Intent**: Prevent two Postgres instances fighting over `5433`.

**Contract**: Comment at the top: mutually exclusive with root `compose.yaml` on host `5433`; when the MVP stack is up, point `TEST_DATABASE_URL` at it instead of starting this file.

#### 4. Compose contract test

**File**: `tests/test_compose_contract.py`

**Intent**: Lock isolation and published ports in CI without a Docker daemon.

**Contract**: Parse `compose.yaml` as YAML. Assert the five service names; published ports are exactly web `8000` and postgres `5433`; validator environment has no `DATABASE_URL`, `API_JWT_SECRET`, or `API_OBJECT_STORE_*`; validator has no volume that is the named object volume; inference has the catalog bind and the F-03 SHA env; web has both private service URLs. No live `docker compose up` in this test.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_compose_contract.py -m "not ml"` passes
- `test -f compose.yaml compose.env.example` succeeds
- `ruff check tests/test_compose_contract.py`

#### Manual Verification:

- Owner runs `docker compose --env-file compose.env config` and confirms validator has neither JWT nor object-store volume, and that only `8000` and `5433` are published

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Documentation reframe

### Overview

Make Compose the documented MVP proof. Demote Railway to unexecuted future hosting design in every active doc that still recommends it as the verified path.

### Changes Required:

#### 1. Operator README

**File**: `README.md`

**Intent**: Document Compose as the reproducible local deployment; keep host-process uvicorn as a dev path that still needs validator URL+token for register.

**Contract**: Add a Compose section: copy `compose.env.example` → `compose.env`, set catalog host path and SHA, `docker compose --env-file compose.env up --build`, wait for migrate, `docker compose exec web python -m src.api.bootstrap --username admin`, API at `http://127.0.0.1:8000`. State fail-closed: missing catalog → inference `/health` 503; missing validator pair would be a mis-template (pair is required in compose.yaml). Point recorded acceptance at this change’s `acceptance-record.md` once Phase 3 writes it. Do not claim Railway staging, Bucket, private DNS, or cold start as validated. Leave `e2e_serve.py` described as UI smoke, not Compose proof.

#### 2. Deploy plan

**File**: `context/deployment/deploy-plan.md`

**Intent**: Lead with Compose acceptance; keep Railway as an unexecuted future procedure.

**Contract**: Frontmatter/title/objective no longer read as “first Railway staging is the MVP deploy.” Open with the Compose stack, published ports (`8000`, `5433` exception), volume/isolation rules, catalog bind-mount, interactive bootstrap, and the acceptance procedure (migrate → bootstrap → provision roles → register/publish **v3** → upload golden fixture log → poll run → results vs provisional-results → validator 503 → catalog mismatch). Railway sections stay but are explicitly **unexecuted / not proof**. Do not rewrite IaC as if it were applied.

#### 3. Foundation infra and stack

**Files**: `context/foundation/infrastructure.md`, `context/foundation/tech-stack.md`

**Intent**: Stop telling later agents to “deploy the MVP on Railway” as the verified path.

**Contract**: Keep the Railway-vs-Render comparison as historical platform research. Change the recommendation/hosting rows: **verified MVP deployment proof is local Compose**; Railway remains the unexecuted future hosting design. Do not delete the comparison tables. Update frontmatter so `recommended_platform` / `deployment.platform` cannot be read as “Railway already validated.”

#### 4. Developer env example pointer

**File**: `.env.example`

**Intent**: Point Compose users at `compose.env.example` so SQLite `.env` is not mistaken for the stack.

**Contract**: Short comment: Compose uses `compose.env` / `compose.yaml`; do not feed this file’s `DATABASE_URL=sqlite://...` into Compose interpolation.

### Success Criteria:

#### Automated Verification:

- `rg -n "unexecuted" context/deployment/deploy-plan.md README.md` matches
- `rg -n "local Compose" README.md context/deployment/deploy-plan.md context/foundation/infrastructure.md context/foundation/tech-stack.md` matches
- `rg -n "compose.env.example" README.md .env.example` matches

#### Manual Verification:

- Owner confirms README and deploy-plan lead with Compose as MVP proof and Railway as unexecuted future design, and that infrastructure.md no longer reads as “deploy the MVP on Railway” without that qualifier

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 3: Evidence run and acceptance record

### Overview

Run the labelled parity gate and the Compose acceptance procedure on a normal local machine, commit only the markdown record, and stamp both remaining alignment workstreams `done`.

### Changes Required:

#### 1. Trusted parity (no new script)

**Files**: none in Git except the record in item 3

**Intent**: Re-run the existing FR-011 gate with explicit baseline paths.

**Contract**: From a normal ML/Linux inference environment (not Cursor sandbox, not Ubuntu CI), run `scripts/verify_hdfs_parity.py` with the paths in `context/foundation/hdfs-parity-baseline.md` including `--test-block-ids`. Leave `expected.json` immutable. Write the report under gitignored `releases/hdfs/v3/`. If v3/corpus/expected files are missing, **stop** — do not record a pass. Quote `passed`, threshold equality, and metric deltas in the acceptance record; do not commit the report file.

#### 2. Compose acceptance procedure (host-side)

**Files**: none except the record in item 3

**Intent**: Prove the stack with the real validator and inference images against PostgreSQL.

**Contract**: Prerequisites: `compose.env` filled; `HDFS_COMPLETENESS_CATALOG_DIR` points at an existing fingerprint directory; `releases/hdfs/attribute-gae-v3.zip` and the matching preprocessing ZIP exist. If either artefact set is missing, **fail closed**. Sequence: `docker compose --env-file compose.env up --build -d` (migrate completes); bootstrap via `exec`; provision project/publisher/operator; Publisher register+publish **v3** (not fixture v2); Operator upload `tests/fixtures/hdfs_inference_release/hdfs.log`; start analysis; poll to `completed` or record a real terminal failure; GET results and provisional-results; confirm audit events exist. Negatives (same stack, recorded): (1) validator stopped → register 503 and empty model list; (2) catalog SHA or file mismatch → inference `/health` 503 and/or run `COMPLETENESS_CATALOG_UNAVAILABLE`, not all-provisional. Then `pytest -m postgres` with `TEST_DATABASE_URL` on `127.0.0.1:5433`. Also run targeted v2/admission/validator tests, API tests, lint, mypy, and frontend build as listed in alignment — on a normal local terminal for `@ml`. Capture `docker compose images` digests as **run evidence**.

#### 3. Acceptance record

**File**: `context/changes/local-compose-mvp-acceptance/acceptance-record.md`

**Intent**: Durable, binary-free evidence that archives with this change.

**Contract**: Markdown with at least: Git commit SHA; date; Compose image digests (run evidence); artifact checksums (re-state from baseline + v3 ZIP checksums); migration version (`008` unless migrate prints another); commands and exit codes; analysis run id; relevant audit ids; parity `passed` plus threshold/metric notes; notes that fixture log ≠ FR-011 and Railway was not exercised. No attached ZIP, `.pt`, log, or `parity-report.json`.

#### 4. Alignment stamp

**File**: `context/foundation/mvp-alignment-plan.md`

**Intent**: Close the two workstreams this change owns.

**Contract**: `compose-acceptance` and `verify-evidence` status `done`. Leave earlier rows as they are. Bump `updated`.

### Success Criteria:

#### Automated Verification:

- `test -f context/changes/local-compose-mvp-acceptance/acceptance-record.md` succeeds
- `rg -n "compose-acceptance" context/foundation/mvp-alignment-plan.md` shows `done`
- `rg -n "verify-evidence" context/foundation/mvp-alignment-plan.md` shows `done`

#### Manual Verification:

- Owner confirms `verify_hdfs_parity.py` passed in a normal local ML venv and that `parity-report.json` is not staged
- Owner confirms Compose happy path (v3 publish + golden fixture log) plus validator 503 and catalog mismatch, and that `git status` shows no binaries under `releases/`, `artifacts/`, or `data/`

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Testing Strategy

### Unit Tests:

- `tests/test_compose_contract.py` — services, published ports, validator isolation, catalog bind on inference, web private URLs

### Integration Tests:

- Existing `@pytest.mark.postgres` against MVP `5433` when the stack is up (Phase 3)
- Existing API / validator tests unchanged (SQLite + injected command / HTTP stubs)
- Do not add Playwright to this change as Compose proof

### Manual Testing Steps:

1. `docker compose --env-file compose.env config` — validator env/volumes; ports `8000` and `5433` only
2. Bring the stack up with a real catalog path; confirm inference `/health` 503 if SHA is wrong
3. Bootstrap admin; register v3; publish; upload golden fixture log; complete or honestly fail a run
4. Stop validator; register → 503
5. Run `verify_hdfs_parity.py`; confirm report stays gitignored
6. Confirm `compose.env` is untracked

## Performance Considerations

First `docker compose up --build` pulls Torch images and is slow; that is expected. Inference and validator may sleep in Railway IaC; Compose should keep them up for the acceptance window (no requirement to copy `sleepApplication`). Admission still has a 2s connect / 120s validator read timeout — do not add inference-style retries on validation.

## Migration Notes

No schema migration. Existing `tests/postgres/compose.yaml` stays; operators must not run it at the same time as the MVP stack. Local SQLite `.env` remains valid for host uvicorn/dev.

## References

- Related research: `context/changes/local-compose-mvp-acceptance/research.md`
- Alignment source: `context/foundation/mvp-alignment-plan.md`
- Parity pin: `context/foundation/hdfs-parity-baseline.md`
- Railway topology template: `.railway/railway.ts`
- Lessons: object-store rollback; real ML subprocesses; generated data stays out of Git

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Compose stack and env template

#### Automated

- [x] 1.1 `python -m pytest tests/test_compose_contract.py -m "not ml"` passes — ac9ba13
- [x] 1.2 `test -f compose.yaml compose.env.example` succeeds — ac9ba13
- [x] 1.3 `ruff check tests/test_compose_contract.py` — ac9ba13

#### Manual

- [x] 1.4 Owner runs `docker compose --env-file compose.env config` and confirms validator has neither JWT nor object-store volume, and that only `8000` and `5433` are published — ac9ba13

### Phase 2: Documentation reframe

#### Automated

- [x] 2.1 `rg -n "unexecuted" context/deployment/deploy-plan.md README.md` matches
- [x] 2.2 `rg -n "local Compose" README.md context/deployment/deploy-plan.md context/foundation/infrastructure.md context/foundation/tech-stack.md` matches
- [x] 2.3 `rg -n "compose.env.example" README.md .env.example` matches

#### Manual

- [x] 2.4 Owner confirms README and deploy-plan lead with Compose as MVP proof and Railway as unexecuted future design, and that infrastructure.md no longer reads as “deploy the MVP on Railway” without that qualifier

### Phase 3: Evidence run and acceptance record

#### Automated

- [ ] 3.1 `test -f context/changes/local-compose-mvp-acceptance/acceptance-record.md` succeeds
- [ ] 3.2 `rg -n "compose-acceptance" context/foundation/mvp-alignment-plan.md` shows `done`
- [ ] 3.3 `rg -n "verify-evidence" context/foundation/mvp-alignment-plan.md` shows `done`

#### Manual

- [ ] 3.4 Owner confirms `verify_hdfs_parity.py` passed in a normal local ML venv and that `parity-report.json` is not staged
- [ ] 3.5 Owner confirms Compose happy path (v3 publish + golden fixture log) plus validator 503 and catalog mismatch, and that `git status` shows no binaries under `releases/`, `artifacts/`, or `data/`
