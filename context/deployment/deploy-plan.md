---
project: "Log Anomaly Detection System"
platform: Railway
environment: staging
status: ready-for-manual-provisioning
scope: HDFS-only control-plane walking skeleton
updated_at: 2026-09-08
---

# First Railway Staging Deployment

## Objective

Deploy a manually approved, single-region Railway staging environment for the HDFS-only
control plane. The first release contains one public FastAPI service that serves the compiled
React client and uses Railway PostgreSQL for durable identities, projects, model metadata,
analysis-run state, and audit records.

It is deliberately not an end-to-end anomaly-detection release:

- The API continues to return `not_supported` for a valid analysis request because it never
  loads a model.
- Do not provision an inference service, a model loader, a polling worker, or bucket credentials
  for this release.
- Railway Bucket integration, direct browser uploads, the non-executable model-artifact contract,
  Linux PyTorch/PyG dependencies, and HDFS notebook-parity verification are later release gates.
- BGL is notebook-only research and is excluded from the deployed MVP.

## Repository deliverables

- `Dockerfile` builds the React client with Node, then runs the public API from a minimal
  Python 3.10 image with `requirements-api.txt`.
- `.railway/railway.ts` is the current Railway Infrastructure as Code definition. It creates the
  PostgreSQL and `web` service, passes the database service variable by reference, runs migrations
  before deployment, starts Uvicorn on Railway's `PORT`, and probes `/health`.
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
2. A PostgreSQL service. Its `DATABASE_URL` is exposed to `web` only through a Railway variable
   reference; never copy a database password into this repository or a browser build.
3. A private Railway Bucket reserved for future immutable model and parser-config objects. Add it
   through the same Infrastructure as Code definition only after selecting its immutable region;
   use the same region as `web` and PostgreSQL. Leave its credentials unattached to `web` until
   the Bucket adapter and artifact contract exist.
4. A Hobby-plan spend limit and usage alert before the first deployment.

The initial release intentionally has no Railway Volume. The existing trusted-workspace reference
flow is not usable on Railway until it is replaced by authorized Bucket-backed storage.

## Service variable contract

Set these variables on `web` before deployment:

- `DATABASE_URL`: a Railway variable reference to the PostgreSQL service's `DATABASE_URL`.
- `API_JWT_SECRET`: a new, high-entropy secret generated outside the repository.
- `API_JWT_TTL_MINUTES`: `30` unless a deliberate security decision changes it.
- `API_TRUSTED_WORKSPACE_ROOT`: leave at the default `workspace` for this walking skeleton. Do
  not point it at source code or pass Bucket credentials to the API.

Do not set `API_DATABASE_PATH`, `AZURE_OPENAI_*`, model credentials, or Bucket access keys on
this release. The React build has no secrets and must not receive any server variable.

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
apply` prompts for approval and creates the `web` and PostgreSQL resources defined in
`.railway/railway.ts`; its `DATABASE_URL` reference is managed in source. Before deploying,
configure the spend alert and a public Railway domain in the dashboard. Select the future Bucket
region before adding that resource to the IaC file. Then deploy the pinned commit:

```bash
railway up --service web --detach
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
rejected. Do not introduce a startup password variable or hard-coded administrator account.

## Staging validation

Record the deployed Git commit, Railway deployment ID, migration version, service configuration,
public origin, test timestamp, cold-start observation, and peak resource use.

Verify the following after the deployment becomes healthy:

```bash
curl --fail --show-error https://<web-domain>/health
curl --fail --show-error https://<web-domain>/openapi.json
curl --fail --show-error https://<web-domain>/
railway logs --service web -n 100
railway deployment list --service web
```

Then sign in through the same-origin UI and confirm all of these conditions:

- The login page, assets, and browser refresh load from the public domain.
- The bootstrapped administrator can authenticate, create a project, and view its audit events.
- An unauthenticated request is rejected, and a caller without project access cannot enumerate
  another project's records.
- The health endpoint reports success only while PostgreSQL is reachable.
- No secret appears in the rendered client, build output, deployment log, or API response.
- The public API becomes idle after testing; no polling worker, permanent database pool,
  heartbeat, or telemetry keeps it active.

Do not claim an HDFS inference demonstration from this release. A valid HDFS request can only be
tested after trusted Bucket-backed input and the separate model-artifact security contract exist;
until then, `INFERENCE_CONTRACT_UNAVAILABLE` is the expected safe terminal outcome.

## Failure, rollback, and cleanup

- For a bad image or application configuration, a human selects a known-good deployment in the
  Railway dashboard and confirms rollback. Railway image rollback does not undo migrations,
  PostgreSQL contents, or Bucket objects.
- Fix a bad migration with a forward migration or an explicitly tested database restore; never
  remove data or run a destructive database command during a staging incident.
- Rotate a leaked service secret by setting its replacement, redeploying `web`, validating login,
  then deleting the old variable.
- Once the manual test is complete, remove temporary test deployments with
  `railway down --service web` only after a human confirms the target. Retain the documented
  deployment evidence, but do not retain bootstrap-only credentials.

Before production data or inference is enabled, add and test PostgreSQL backup/restore, immutable
Bucket-key and checksum handling, bounded structured-log review, artifact upload/download
authorization, a Linux inference image, and HDFS notebook-parity checks within one percentage
point of the agreed baseline.
