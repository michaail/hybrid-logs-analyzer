# Hybrid Logs Analyzer

HDFS log anomaly detection control plane: FastAPI API, private inference worker,
isolated model-package validator, and React UI.

Research notebooks (training, ablation, Colab) live in the
[`research/`](research/) git submodule
([hybrid-logs-analyzer-research](https://github.com/michaail/hybrid-logs-analyzer-research)).
Clone this repository and initialize the submodule so notebooks can import
`src.modules` from this checkout:

```bash
git clone --recurse-submodules https://github.com/michaail/hybrid-logs-analyzer.git
# or, in an existing clone:
git submodule update --init
```

See [`research/README.md`](research/README.md) and
[`research/notebooks/PROCESS.md`](research/notebooks/PROCESS.md) to run the
R&D path. Production-facing pipeline behavior stays in `src/modules/` and
`run_ablation.py` here.

## Local environment

The local development baseline targets Python 3.10+ on Intel (`x86_64`) macOS. Runtime
versions are intentionally pinned; do not upgrade them as part of routine environment setup,
because newer ML releases may not publish Intel macOS builds.

```bash
# Verify the expected architecture, then create an isolated environment.
uname -m  # expected: x86_64
python3 -m venv .venv
source .venv/bin/activate

# Recreate the exact Intel-compatible runtime and development environment.
python -m pip install --upgrade pip
python -m pip install -r requirements-macos-intel.lock.txt

# Verify the local development gates.
python -m pytest
ruff check src tests scripts run_ablation.py
mypy
python -m pip_audit -r requirements.txt
```

`pyproject.toml` is the single configuration source for pytest, Ruff, mypy, and the Pydantic
mypy plugin. Pydantic provides runtime validation for typed boundary models; mypy performs
static checking. `requirements.txt`, `requirements-macos-intel.txt`, and
`requirements-dev.txt` are the maintained input pins. `requirements-macos-intel.lock.txt`
captures the complete environment verified on the Intel development machine. Regenerate
that lock only as an explicit compatibility task. Colab dependency ranges live in
`research/requirements-colab.txt`.

HDFS corpora used for labelled parity remain under ignored `data/raw/`. Copy `.env.example`
to `.env` for local secrets. Azure OpenAI keys are only required for optional LLM
enrichment in the research path.

## FastAPI foundation

The HDFS-only API provides administrator-provisioned accounts, project isolation, auditable
model registration/publication, and analysis-run validation. It stores metadata in the database
configured by `DATABASE_URL`. Publishers upload a complete HDFS model package ZIP; only
declared package files are persisted in object storage (a local filesystem root by default, or
an S3-compatible Bucket when those credentials are configured). The public API process never
deserializes a model artifact.

### Local Compose (verified MVP proof)

The verified HDFS MVP deployment proof is **local Compose**, not Railway. Copy
`compose.env.example` to `compose.env`, set the F-03 catalog host path and SHA-256,
generate high-entropy JWT and tokens, then:

```bash
cp compose.env.example compose.env
# Fill API_JWT_SECRET, POSTGRES_PASSWORD, INFERENCE_INTERNAL_TOKEN,
# MODEL_VALIDATOR_INTERNAL_TOKEN, HDFS_COMPLETENESS_CATALOG_DIR, and
# INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256.

docker compose --env-file compose.env up --build
docker compose --env-file compose.env exec web python -m src.api.bootstrap --username admin
```

Wait for the one-shot `migrate` service to finish before bootstrap. The API is at
`http://127.0.0.1:8000` (container 8080). Postgres is published on host `5433` so
`pytest -m postgres` can use the same database; do not start
`tests/postgres/compose.yaml` at the same time.

A missing or mismatched catalog makes inference `/health` return 503 (not
all-provisional). `compose.yaml` always sets the validator URL+token pair on `web`;
omitting that pair would be a mis-template, and register would 503 with no model row.
The validator has no JWT, database URL, or object-store volume.

`scripts/e2e_serve.py` remains UI smoke (files-only validator, disposable SQLite). It is
not Compose proof and not Torch-validator proof. Playwright is not Compose proof.

Railway staging, Bucket, private DNS, and cold start are **unexecuted** future hosting
design. Recorded Compose acceptance (after the evidence run) is
`context/changes/local-compose-mvp-acceptance/acceptance-record.md`.

### Host-process development

Copy `.env.example` to `.env` and set a unique `API_JWT_SECRET`. Configure
`DATABASE_URL` (for example, `sqlite:///.api/analyzer.db` locally). Do not feed that
SQLite URL into Compose; Compose uses `compose.env` / `compose.yaml`.
`API_TRUSTED_WORKSPACE_ROOT` is no longer the Operator log intake path; Operators
upload object-kind HDFS datasets instead. Optional `API_OBJECT_STORE_ROOT` defaults to a
sibling `.api/objects` directory for local object-kind model packages and admitted datasets:

```bash
source .venv/bin/activate
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Put the printed value in API_JWT_SECRET in .env.

python -m src.api.migrations
python -m src.api.bootstrap --username admin
uvicorn src.api.main:create_app --factory --reload
```

Registering a model requires the private validator. Set
`MODEL_VALIDATOR_SERVICE_URL` and `MODEL_VALIDATOR_INTERNAL_TOKEN` together on the API
process, and the same token on the validator process. Local UI smoke without that HTTP
service uses `scripts/e2e_serve.py`, which injects a files-only command. A factory
`uvicorn` start with neither the URL/token pair nor an injected command fails closed
on register (`503`) and inserts no model row.

The API is then available at `http://127.0.0.1:8000`, with OpenAPI documentation at `/docs`.
There is no public sign-up route. The first Administrator is created only by the
interactive CLI bootstrap above; the browser never creates Administrators.

Local analysis uses three processes. Keep the public API Torch-free; run inference in
its own environment (the Linux inference image, or a local ML venv) with the shared
database and object store:

```bash
# Terminal 1 — public API (requirements-api.txt)
uvicorn src.api.main:create_app --factory --reload

# Terminal 2 — private inference (requirements-inference.txt). Listens on PORT or 8080.
python -m src.inference_service

# Terminal 3 — React client
cd frontend && npm install && npm run dev
```

Set `INFERENCE_SERVICE_URL` (for example `http://127.0.0.1:8080`) and the same
`INFERENCE_INTERNAL_TOKEN` in the API process and the inference process. Do not put
that token, JWT secret, or object-store keys in the Vite/React build. A valid analysis
request still returns `202 queued` immediately. The API then retries activation for a
bounded interval. If both settings are unset, or activation cannot succeed, the run
becomes `failed` with `INFERENCE_DISPATCH_FAILED` and a generic Operator-safe report.
That public result does not include the inference URL, token, or exception text.

For live model registration against this factory `uvicorn` path, also run the private
validator (`python -m src.model_validator.service` from
`requirements-model-validator.txt`) and set `MODEL_VALIDATOR_SERVICE_URL` (for example
`http://127.0.0.1:8081`) with `MODEL_VALIDATOR_INTERNAL_TOKEN` on both the API and
validator processes. Local UI smoke that only needs admission can skip that service
and use `scripts/e2e_serve.py` instead.

The private inference process also requires a pinned F-03 catalog pair:

```bash
# After scripts/build_hdfs_evaluation_dataset.py prints the ignored manifest path:
shasum -a 256 artifacts/cache/hdfs/evaluation-data/<fingerprint>/manifest.json
```

Set both `INFERENCE_HDFS_COMPLETENESS_MANIFEST` and
`INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256` (lowercase hex) on the inference
process only. Leave them out of the public API, the React build, and model-validator
packages.

Locally, the manifest value is the absolute path to that ignored `manifest.json`.
Local Compose bind-mounts that directory read-only into `inference`. An unexecuted
future Railway design would use the Bucket object key
`hdfs/reference-catalog/manifest.json` plus sibling `selected-block-ids.txt`.
Inference `/health` verifies the catalog before reporting ready.

A missing or checksum-mismatched catalog fails the analysis run; it does not
treat every block as provisional. Generated evaluation artifacts stay under ignored
workspace paths and must not be committed.

Sign-in uses a username and password. Usernames are stored as a canonical lowercase
identity (3–64 characters: letters, digits, underscore, dot, or hyphen), and sign-in is
case-insensitive. A successful `POST /auth/token` returns a JWT bearer token with a
30-minute default lifetime. Do not put passwords in committed examples or logs.

An Administrator then creates a project, provisions a non-administrator Operator or
Publisher with `POST /admin/project-accounts` (username, password, project, and initial
role in one request), and later manages access with create-only membership grant,
role change, and membership revoke endpoints. `PATCH /admin/users/{user_id}/activation`
deactivates or reactivates a non-administrator account. Revocation and deactivation
take effect on the next authorized request; deactivated accounts cannot sign in.
Accounts and memberships are not deleted.

Project membership actions appear in `GET /projects/{project_id}/audit-events`.
Bootstrap, provisioning, sign-in, deactivation, and reactivation appear in
`GET /admin/audit-events`. The selected-project Administration view in the React
client exposes the same workflow.

### Trusted HDFS model package

Registration is a same-origin multipart ZIP upload (`POST /projects/{project_id}/models`,
file field `package`). Directory `package_reference` JSON is not a public admission path.
Invalid packages return a structured 422 `{ valid, issues[] }` and insert no row. A valid
package becomes `eligible` with `storage_kind=object` and `checksum` set to the artifact
SHA-256. Explicit `POST .../publish` remains a second Publisher action; the API does not
auto-publish. Operators receive 403 on register and publish.

The reusable library unpacks a zip under hard caps (32 MiB compressed, 96 MiB uncompressed,
64 members; zip-slip and nested archives are rejected). After the isolated directory
validator accepts the extract, only `manifest.json` and the two declared files are copied
into object storage. Extra undeclared ZIP members are ignored for eligibility and are not
persisted. `manifest.json` must sit at the ZIP root; a single wrapping folder is not
unwrapped.

A hand-built registration looks like two ZIPs:

```text
hdfs-attribute-gae-v2.zip
  manifest.json
  model.pt
  evidence.json

hdfs-preprocessing-bundle.zip
  manifest.json
  drain.ini
  drain_parser.bin
  embeddings.npz
```

`manifest.json` is a closed schema. Required fields include `model_identifier`, `version`,
`source_compatibility` (`hdfs` only), `format` (`attribute-aware-gae-v2`), `metrics` with a
finite `best_threshold`, `architecture` (`node_dim`, `edge_dim`, `hidden_dim`, `latent_dim`,
`gine_aggregation`, `node_transformation`, paired `edge_mean`/`edge_std`), `scoring`
(`alpha`, `beta`, `gamma`), `preprocessing_bundle` (`identifier`, `version`, `digest`), and
`files` with relative POSIX `artifact` / `evidence` paths plus
lowercase hex SHA-256 checksums of those files. Extra undeclared files are ignored for
eligibility. `evidence.json` must be a non-empty JSON object; its contents are not scored.

`model.pt` must be a tensor-only AttributeAwareGAE state dict. A dedicated private
validator service loads it with `torch.load(..., map_location="cpu", weights_only=True)`
and checks keys, shapes, and dtypes against the declared architecture. The public API never
imports PyTorch, never calls `torch.load`, and never uses `weights_only=False` on an admitted
artifact. Install `requirements-model-validator.txt` only for that isolated process; keep
`requirements-api.txt` Torch-free. Do not regenerate `requirements-macos-intel.lock.txt`
from the validator file.

Publishers register with `POST /projects/{project_id}/models` as multipart ZIP (`package` and
`preprocessing_bundle`) and explicitly
publish an eligible version. Operators admit a UTF-8 HDFS log with
`POST /projects/{project_id}/datasets` (multipart field `log`, 32 MiB cap). A valid file
becomes a new `storage_kind=object` dataset with a SHA-256 checksum. Invalid, empty,
oversize, or non-UTF-8 payloads return 422 with a validation report, persist no object, and
insert no row. Analysis starts with `POST /projects/{project_id}/analysis-runs` using
`{ model_version_id, dataset_id }` only. Missing or foreign datasets return 404. The API
copies the dataset object key into `log_reference`; it does not re-scan the log at analyze
time. An unpublished model returns 409 before any run
is created. An inference-ready published v2 model returns `202` with status `queued` and
null completion/error fields; the API then activates the private inference service with
bounded retry. If activation succeeds, the inference service owns
`queued → running → completed|failed`. If activation cannot succeed, the still-queued
run becomes `failed` with `INFERENCE_DISPATCH_FAILED`. Server logs keep exception type
names only; they never include the token or `Authorization` header. Model and run
responses add `storage_kind` and nullable `checksum`; runs also return `dataset_id`.
GET results returns the stored
`results_summary_json`, not a computed empty summary. There is no public PATCH for
datasets, and no public POST/PATCH for anomaly rows or run status.

Invalid uploads never become analysis runs. Isolated inference runs in a private service
built from `Dockerfile.inference`; the public API image stays on `requirements-api.txt`
and never imports PyTorch. Do not SHA-256 Operator HDFS logs at analyze time.

### Inspecting HDFS analysis results

An authorized Operator can retrieve one bounded page of detected HDFS blocks with
`GET /projects/{project_id}/analysis-runs/{analysis_run_id}/results`. Each anomaly identifies
the HDFS `block_id` (also retained as the compatibility `record_reference`), score, decision
threshold, level, and stored source-log context. Source context contains original source line
numbers and raw text in scoring-sequence order. The response labels how many scored lines
matched the block; it may show only the stored subset, so it must not be interpreted as the
entire original source file.

Result pages accept only `limit` (1–100, default 50), `sort` (`score_desc` or
`block_id_asc`), `block_id_prefix`, `min_score`, and the opaque `cursor` returned by the
previous page. Pagination is keyset-based and does not re-score the run or expose model
artifacts. The `summary` counts apply to the complete run, not the selected filter or page.
The response also records the selected model/version, pipeline run, dataset checksum, model
artifact checksum, and preprocessing-bundle identity when present.

Results are project-scoped: a caller without membership in the selected project receives
`404`, including when presenting a cursor issued for another project. Invalid or rejected
HDFS uploads remain a `422` validation report at dataset admission and create no analysis
run or historical result row. These pages present heuristically final detected anomalies
only. S-06 / FR-012 uses membership in a pinned F-03 selected-block-id catalog as the
documented reference-membership heuristic: catalog members may receive anomaly or normal
outcomes labelled **heuristically final**. That membership is useful triage evidence, not
proof that an HDFS lifecycle ended. Histories absent from the catalog are provisional
and must not appear in the anomaly list or heuristic-final counts.

`GET /projects/{project_id}/analysis-runs/{analysis_run_id}/provisional-results` provides
the separate, operator-authorized page of those provisional histories. It accepts only
`limit` (1–100, default 50), literal `block_id_prefix`, and the opaque `cursor` from the
preceding provisional page; it has no score filter or score-based ordering. Each returned
record contains a block ID, `not_in_reference_catalog` reason, server-owned explanation,
and bounded source evidence. It never contains a model score, decision threshold, or
anomaly level. The route returns an empty page for queued, failed, rejected, and historical
runs, and rejects a malformed, mismatched, or anomaly-issued cursor with `422`.

The result summary remains run-wide, including while either result page is filtered or
paginated. Its four existing fields are heuristic anomaly count, heuristic normal count,
rejected records, and invalid records; `provisional_count` and
`unassigned_context_line_count` are additive run columns. A parser-matched line with no
HDFS block ID belongs to neither result page and increments only the unassigned-context
count. The React outcome view keeps provisional histories in a separate panel and labels
all scored outcomes as **heuristically final**.

S-04 analysis loads a frozen Drain3 FilePersistence snapshot with the bundle `drain.ini`
via `DrainParser.load`, then calls `annotate_file` only. It does not fit Drain, re-enrich
templates, or put parser files in the GAE package. Unmatched admitted lines fail the run
with `UNMATCHED_TEMPLATE`. To bound the finite private service, inference rejects inputs with
more than 100,000 non-empty lines or 25,000 HDFS blocks before graph scoring.

Processing drift is checked by the versioned golden fixture in
`tests/fixtures/hdfs_inference_release/` (parser matches, ordered `block_id`s, graph
topology, features, scores, and `score > threshold` decisions). Feature and score
comparisons use absolute/relative tolerances of `1e-5`; block order, source line
references, parser checksums, and the decision threshold are exact.

Labelled FR-011 verification is a controlled release gate, not a browser upload and not
part of default CI. It validates every source line against the frozen parser, then scores
complete held-out block histories in bounded temporary shards without relaxing private
service limits. Supply the exported release ZIP pair, the labelled corpus, and an
immutable expected JSON (checksums plus test F1 / PR-AUC / ROC-AUC / threshold). The
command writes `parity-report.json` beside that record and does not modify it. Exit
status is nonzero when a checksum mismatches, the threshold changes, or a core metric
moves by more than 0.01:

```bash
python scripts/verify_hdfs_parity.py \
  --model-package releases/hdfs/attribute-gae-v3.zip \
  --preprocessing-bundle releases/hdfs/attribute-gae-preprocessing-v3.zip \
  --corpus data/raw/hdfs/HDFS_full.log \
  --labels data/raw/hdfs/anomaly_label.csv \
  --expected releases/hdfs/v3/expected.json \
  --report releases/hdfs/v3/parity-report.json \
  --test-block-ids releases/hdfs/test_block_ids.txt
```

`--test-block-ids` is required for the selected baseline's held-out split. Omit it only
when every scored block in the supplied corpus is the evaluation set (the golden fixture).
Run this in the Linux inference environment or a local ML venv, not in Cursor's
restricted native-library sandbox. Do not treat a passing Operator upload as FR-011.

### Complete-history HDFS evaluation data

FR-013 evaluation data is a checksum-bound projection of an approved HDFS corpus onto an
explicit ordered block-ID list. A selected block is complete *within that corpus*: every
source line whose first `blk_*` match is selected appears exactly once, in original
source-file order, in one bounded shard. That is reproducible evaluation evidence, not a
claim that an arbitrary Operator upload is lifecycle-complete. S-06 / FR-012 pins this
artifact's selected-block-id list as a reference-membership heuristic for live analysis:
catalog members are labelled **heuristically final**, not proven lifecycle-complete.
F-03 does not classify Operator uploads.

Line-prefix samples are parser or intake smoke tests only and cannot support
anomaly-quality evaluation. The builder never infers a newest corpus, label file, release,
or held-out split; every input path is explicit. Source-file order is canonical.
Unparseable or backward timestamps become manifest warnings and do not reorder or discard
retained lines.

Production frozen-inference limits drive sharding: 100,000 non-empty source lines and
25,000 blocks per shard. A selected block is never split across shards.

Create the artifact from explicit paths:

```bash
python scripts/build_hdfs_evaluation_dataset.py \
  --corpus data/raw/hdfs/HDFS_full.log \
  --labels data/raw/hdfs/anomaly_label.csv \
  --selected-block-ids releases/hdfs/test_block_ids.txt \
  --workspace-root . \
  --code-root .
```

The command prints the published or reused `manifest.json` path. Output stays under the
ignored workspace cache `artifacts/cache/hdfs/evaluation-data/<fingerprint>/` and
must not be committed. Pin that absolute path and the manifest SHA-256 on the private
inference service (`INFERENCE_HDFS_COMPLETENESS_MANIFEST` and
`INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256`) so live analysis can apply the
reference-membership heuristic. The digest is calculated at deploy time and is not
stored in Git.

The cache entry includes:

- `selected-block-ids.txt` — copy of the supplied ordered ID file
- `shard-NNN.log` — bounded complete-history shards
- `manifest.json` — schema version; corpus, label, and selected-ID SHA-256 values;
  selected-block count; per-block retained-line counts; per-shard digests and counts;
  configured limits; and timestamp warnings
- `_SUCCESS.json` — atomic publication record

Unchanged inputs, shard limits, and git revision reuse the same cache entry. Changing
corpus, label, or selected-ID bytes produces a distinct artifact even if a path, size, or
mtime is reused.

### S-06 rollout, verification, and rollback

Roll out S-06 in this order:

1. Build and retain the F-03 artifact outside Git, then record the `manifest.json` SHA-256.
2. Apply migration `008_provisional_hdfs_results` to the shared database.
3. Configure and deploy the private inference service with the manifest location and exact
   SHA-256 (filesystem path or Compose bind-mount locally; Bucket object key
   `hdfs/reference-catalog/manifest.json` only in the unexecuted Railway design); verify
   `/health` can load the catalog before admitting queued work.
4. Deploy the public API.
5. Deploy the frontend.

The catalog is an immutable deployment input, not a browser or API upload. If its manifest
or selected-ID file changes after the digest is pinned, a new run fails with
`COMPLETENESS_CATALOG_UNAVAILABLE`; it must not silently classify every block as
provisional. Retain the exact catalog artifact and digest for every completed run.

Code rollback never drops migration 008's table, index, or columns. The original
four-field `results_summary_json` remains unchanged, so an older API can still read
completed runs after a code rollback. Do not remove provisional records or the catalog
artifact while any run may need inspection.

Run the regression checks in a normal local ML environment or the Linux inference
environment, not Cursor's restricted native-library sandbox:

```bash
python -m pytest
python -m pytest -m ml
ruff check src tests scripts run_ablation.py
mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

The approved 11,167,740-line corpus build and the controlled `scripts/verify_hdfs_parity.py`
run against the v3 release are documented manual release checks. They need the
workspace-local LogHub files and an ML/native environment; they are not default CI tests.
Automated coverage uses `tests/test_hdfs_evaluation_data.py` plus the golden fixture in
`tests/fixtures/hdfs_inference_release/`. The golden `release_gate` tests remain opt-in
(`pytest tests/test_hdfs_inference_parity.py -m release_gate` in an ML venv).

Optional PostgreSQL dialect tests stay out of default CI. If the MVP stack is already
up, point `TEST_DATABASE_URL` at host `5433` and do not start the harness below
(both bind that port):

```bash
# Thin dialect harness only — mutually exclusive with root compose.yaml on 5433.
docker compose -f tests/postgres/compose.yaml up -d
TEST_DATABASE_URL=postgresql://analyzer:analyzer@127.0.0.1:5433/analyzer python -m pytest tests/test_migrations.py tests/test_shared_state_repository.py -m postgres
```

## React interface

The React/TypeScript client is in [`frontend/`](./frontend). It is a thin client for the FastAPI
control plane: it stores the bearer token only in browser session storage, scopes every project
request through the selected project, and leaves authorization decisions to the API.

Run the API first, then start the development client in another terminal:

```bash
cd frontend && npm install && npm run dev
```

Vite proxies API paths to `http://127.0.0.1:8000` during local development (`E2E_API_ORIGIN`
overrides the proxy target for Playwright). A deployed static
build leaves `VITE_API_BASE_URL` unset when the API serves the client from the same origin.
The web image builds `frontend/dist` and serves it through FastAPI. See the
[deployment guide](context/deployment/deploy-plan.md): verified MVP proof is **local Compose**
(`web`, private `inference`, private `model-validator`, PostgreSQL, named object volume).
Railway Bucket / private DNS / cold start remain unexecuted future hosting. There is no
polling worker and no public inference route.

The current API accepts a Publisher ZIP for model registration and an Operator HDFS log
upload. The datasets panel admits a file; the analyze dialog selects an accepted
`dataset_id`. Inference-ready published v2 models queue an asynchronous run; the UI polls
`queued` and `running` every five seconds until `completed` or `failed`.

### Playwright E2E (HDFS model publication)

Browser tests live in [`frontend/e2e/`](./frontend/e2e) and run through the frontend Playwright config. They
start an isolated API (`scripts/e2e_serve.py`, disposable SQLite under `.e2e/`) and a Vite
dev server on dedicated ports so they do not reuse a developer’s `.api/` database. Run them
locally, in CI, or as pre-push verification — not after every agent edit.
Use Node 22 (`nvm use 22`) so Playwright and the frontend toolchain match CI.

```bash
source .venv/bin/activate
# CI installs requirements-e2e.txt (API deps + numpy). A full ML venv already has numpy.
nvm use 22
npm --prefix frontend install
npx --prefix frontend playwright install chromium
npm --prefix frontend run test:e2e
npm --prefix frontend run test:e2e:headed
npm --prefix frontend run test:e2e:seed
npm --prefix frontend exec playwright test publish-eligible-hdfs-model.spec.ts
```

Prefer `npm --prefix frontend run …` from the repository root. That sets the
working directory to `frontend/`, so Playwright loads `frontend/playwright.config.ts`
(base URL, isolated servers, and auth setup). `npx --prefix frontend playwright test`
keeps the current directory; a root `playwright.config.ts` re-exports the frontend
config so that form also works.

Optional non-secret environment variable names (values are generated into
`playwright/.auth/`, which is gitignored):

- `E2E_BASE_URL` (default `http://127.0.0.1:15173`)
- `E2E_API_ORIGIN` / `E2E_API_PORT` (default `http://127.0.0.1:18000`)
- `E2E_UI_PORT` (default `15173`)
- `E2E_PYTHON` (defaults to `.venv/bin/python` when present, otherwise `python3`)
- `E2E_ADMIN_USERNAME` / `E2E_ADMIN_PASSWORD`
- `E2E_PUBLISHER_USERNAME` / `E2E_PUBLISHER_PASSWORD`
- `E2E_PROJECT_B_USER_USERNAME` / `E2E_PROJECT_B_USER_PASSWORD`

Authentication: `frontend/e2e/auth.setup.ts` provisions Publisher (project A) and Operator (project
B) through the real admin HTTP API, then signs each role in through the UI and stores the
session token under `playwright/.auth/`. Specs restore that token into `sessionStorage`
(`logscope.access-token`) instead of logging in again. Refresh auth by re-running the suite
(the API process wipes `.e2e/` on each start).

Safe fixtures: `scripts/e2e_package.py` writes a unique `attribute-aware-gae-v2` package ZIP
and matching preprocessing-bundle ZIP (never `torch.load`s artifacts). Ineligible packages
use empty `evidence.json`. The E2E API validator is the existing Torch-free
`tests/support/files_only_validator.py` subprocess. A committed v1 directory
`tests/fixtures/model_packages/rejected_v1/` is a 422 oracle, not an upload fixture.

Cleanup: there is no public model-delete API. Each suite start deletes `.e2e/` and creates
a new SQLite file and object store. Tests also use unique identities so parallel workers
cannot collide.

Add a new E2E test only when the risk crosses UI, auth, routing, API, and persistence.
Cross-project model isolation stays in `tests/test_api.py`; do not duplicate it in
Playwright unless a UI/client-state regression can land independently.
