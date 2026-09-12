---
project: "Log Anomaly Detection System"
platform: Railway
environment: staging
status: ready-for-manual-provisioning
scope: HDFS-only control plane plus private on-demand inference
updated_at: 2026-09-11
---

# First Railway Staging Deployment

## Objective

Deploy a manually approved, single-region Railway staging environment for the HDFS-only
control plane and a private on-demand inference service. The public FastAPI service serves
the compiled React client and uses Railway PostgreSQL for durable identities, projects,
model metadata, analysis-run state, and audit records. The inference service is invoked
once per queued run, shares that database and the private Bucket, and becomes idle.

Boundaries that remain in this release:

- The public `web` image stays on `requirements-api.txt`. It never loads PyTorch, Drain3,
  or uploaded model bytes.
- Admitted HDFS model packages and Operator dataset uploads persist as `storage_kind=object`
  through the Bucket adapter when credentials are attached to `web` and `inference`.
- BGL is notebook-only research and is excluded from the deployed MVP.
- There is no polling worker, public inference route, or long-lived heartbeat.

## Repository deliverables

- `Dockerfile` builds the React client with Node, then runs the public API from a minimal
  Python 3.10 image with `requirements-api.txt`.
- `Dockerfile.inference` builds the private Linux ML service from `requirements-inference.txt`.
  It runs as a non-root user and does not receive `API_JWT_SECRET`.
- `.railway/railway.ts` is the current Railway Infrastructure as Code definition. It creates the
  PostgreSQL service, a private `models` Bucket, public `web`, and private `inference`, passes
  the database and Bucket credentials by reference, runs migrations before the web deployment,
  starts Uvicorn on Railway's `PORT`, and probes `/health`. `web` uses `Dockerfile`;
  `inference` uses `Dockerfile.inference` and may sleep when idle. `INFERENCE_SERVICE_URL`
  points at the private DNS name `http://inference.railway.internal:8080`. Both services
  reference one pre-created, environment-level `INFERENCE_INTERNAL_TOKEN` shared variable.
  Non-staging apply still throws.
- `src/api/migrations.py` applies versioned, idempotent schema migrations. PostgreSQL migrations
  hold an advisory transaction lock so concurrent deploys cannot race; the web process and
  administrator bootstrap command never create the schema at startup.
- `DATABASE_URL` replaces the local SQLite path setting. SQLite remains available only for local
  tests and development through a `sqlite:///...` URL; Railway must use PostgreSQL.
- FastAPI serves `frontend/dist` from the same origin when that build is present, so the
  production client needs no CORS configuration or `VITE_API_BASE_URL`.
- The API adds content-type, framing, referrer, permissions, and same-origin content-security
  headers to public application responses. Interactive API documentation keeps its required
  external resources and is intentionally excluded from the content-security policy.
- `.github/workflows/verify.yml` runs the API/artifact tests, Ruff, mypy, and the frontend
  production build without publishing a deployment.

## Required Railway resources

Create these resources in one Railway project and one `staging` environment:

1. A public service named `web`, deployed from this repository at a pinned commit.
2. A private service named `inference`, built from `Dockerfile.inference`. Do not attach a
   public domain. It shares PostgreSQL and the `models` Bucket with `web` and receives the
   internal invocation token, not `API_JWT_SECRET`.
3. A PostgreSQL service. Its `DATABASE_URL` is exposed to `web` and `inference` only through
   a Railway variable reference; never copy a database password into this repository or a
   browser build.
4. A private Railway Bucket named `models` in the same staging project. Its region is
   immutable (`ams` in `.railway/railway.ts`); keep it aligned with `web`, `inference`, and
   PostgreSQL. Attach endpoint, bucket name, and access keys to `web` and `inference` by
   variable reference as defined in the IaC file. Do not copy Bucket secrets into this
   repository or the React build.
5. A Hobby-plan spend limit and usage alert before the first deployment.

The initial release intentionally has no Railway Volume. Model packages and Operator HDFS
logs are admitted as uploads and stored as object-kind rows.

## Service variable contract

Before applying this IaC, create one high-entropy sealed Railway **shared environment variable**
named `INFERENCE_INTERNAL_TOKEN`. The IaC references it as `ctx.shared.INFERENCE_INTERNAL_TOKEN`
for both services; do not create separate service-scoped copies.

Set these variables on `web` before deployment:

- `DATABASE_URL`: a Railway variable reference to the PostgreSQL service's `DATABASE_URL`.
- `API_JWT_SECRET`: a new, high-entropy secret generated outside the repository.
- `API_JWT_TTL_MINUTES`: `30` unless a deliberate security decision changes it.
- `API_TRUSTED_WORKSPACE_ROOT`: leave at the default `workspace`. It is no longer the
  Operator log intake path; Operators upload object-kind datasets instead. Model
  registration also no longer uses a host path.
- `API_OBJECT_STORE_ENDPOINT`, `API_OBJECT_STORE_BUCKET`, `API_OBJECT_STORE_ACCESS_KEY_ID`,
  `API_OBJECT_STORE_SECRET_ACCESS_KEY`, and `API_OBJECT_STORE_REGION`: Railway variable
  references to the `models` Bucket. These are declared in `.railway/railway.ts` and must
  never be copied into the React build.
- `INFERENCE_SERVICE_URL`: private URL `http://inference.railway.internal:8080` as declared
  in IaC.

Set these variables on `inference` (never on the frontend build):

- `DATABASE_URL` and the Bucket credentials, by the same Railway references as `web`.
- Do not set `API_JWT_SECRET` on `inference`.

Do not set `API_DATABASE_PATH`, `AZURE_OPENAI_*`, or model credentials on this release. The
React build has no secrets and must not receive any server variable, invocation token, or
Bucket key.

## Manual provisioning procedure

All Railway mutations require a named target and explicit human approval. Run the following only
after local checks are green and a human has approved the `staging` project:

```bash
brew install railway
railway --version
railway login
node --version
npm ci
railway init
railway environment new staging
railway environment staging
railway config plan
railway config apply
railway variable set API_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" --service web
railway variable set API_JWT_TTL_MINUTES=30 --service web
```

Use Node 22 or later for the IaC dependency. `railway config plan` is read-only. `railway config
apply` prompts for approval and creates the `web`, `inference`, PostgreSQL, and `models` Bucket
resources defined in `.railway/railway.ts`; database and Bucket references are managed in source.
Before deploying, configure the spend alert and a public Railway domain for `web` only. Confirm the
Bucket region (`ams`) matches the staging project before the first apply — the region cannot
change later. Then deploy the pinned commit:

```bash
railway up --service web --detach
railway up --service inference --detach
```

Confirm that the deployment uses `.railway/railway.ts` and its pre-deploy migration command
succeeds before exposing the domain. Railway's legacy `railway.toml`/`railway.json` deployment
format is not used because new services cannot opt into it. The IaC definition rejects all
non-`staging` environments, preventing this first-release configuration from being applied to
production by mistake.

Bootstrap the first administrator only from an interactive Railway service shell:

```bash
railway ssh --service web
python -m src.api.bootstrap --username admin
```

The bootstrap command prompts for a password, so it neither records the password in a command
history nor prints it to build or deployment logs. Perform it once; a duplicate username is
rejected. Usernames are stored as a canonical lowercase identity, and later sign-in is
case-insensitive. Do not introduce a startup password variable or hard-coded administrator
account. After bootstrap, sign in through the same-origin UI and use the Administration view to
provision Operator or Publisher accounts for a project; the browser never creates Administrators.

## Staging validation

Record the deployed Git commit, Railway deployment ID, migration version, service configuration,
public origin, test timestamp, cold-start observation, and peak resource use.

Verify the following after the deployment becomes healthy:

```bash
curl --fail --show-error https://<web-domain>/health
curl --fail --show-error https://<web-domain>/openapi.json
curl --fail --show-error https://<web-domain>/
railway logs --service web -n 100
railway logs --service inference -n 100
railway deployment list --service web
railway deployment list --service inference
```

Then sign in through the same-origin UI and confirm all of these conditions:

- The login page, assets, and browser refresh load from the public domain.
- The bootstrapped administrator can authenticate, create a project, provision a
  project-authorized Operator or Publisher, manage membership and account activation, and
  review project and system audit events.
- An unauthenticated request is rejected, and a caller without project access cannot enumerate
  another project's records.
- A Publisher can upload a complete HDFS package ZIP, receive `eligible` or a structured 422,
  and explicitly publish an eligible version. Operators cannot register or publish.
  `drain_parser.bin` is deserialized only in the private inference process after that
  Publisher admission and checksum verification.
- An Operator can upload a UTF-8 HDFS log, receive an accepted object-kind dataset or a
  structured 422, and start analysis by selecting that `dataset_id`.
- A published inference-ready v2 model queues a run (`202 queued`). Observe a staging
  cold start: the first activation may retry while `inference` wakes, the run stays
  honestly `queued` during a transient activation failure, and polling then reaches
  `running` and a terminal `completed` or `failed` state. Do not treat a dispatch retry
  as a fabricated success.
- The browser, frontend build, and public API responses contain neither
  `INFERENCE_INTERNAL_TOKEN` nor Bucket credentials.
- The health endpoint reports success only while PostgreSQL is reachable.
- No secret appears in the rendered client, build output, deployment log, or API response.
- After testing, both services become idle; no polling worker, permanent database pool,
  heartbeat, or telemetry keeps them active.

Do not expose a public domain or JWT secret on `inference`. Confirm `/internal/analysis-runs`
is absent from the public OpenAPI document. Full-corpus notebook-parity verification remains
a later release gate and is not an Operator upload.

## Failure, rollback, and cleanup

- For a bad image or application configuration, a human selects a known-good deployment in the
  Railway dashboard and confirms rollback. Railway image rollback does not undo migrations,
  PostgreSQL contents, or Bucket objects.
- Fix a bad migration with a forward migration or an explicitly tested database restore; never
  remove data or run a destructive database command during a staging incident.
- Rotate a leaked service secret by setting its replacement, redeploying the affected service,
  validating login or a queued run, then deleting the old variable. Rotate
  `INFERENCE_INTERNAL_TOKEN` on `web` and `inference` together.
- Once the manual test is complete, remove temporary test deployments with
  `railway down --service web` and `railway down --service inference` only after a human
  confirms the target. Retain the documented deployment evidence, but do not retain
  bootstrap-only credentials.

Before production data is enabled, add and test PostgreSQL backup/restore, bounded
structured-log review, and HDFS notebook-parity checks within one percentage point of the
agreed baseline.
