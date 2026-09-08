---
project: "Log Anomaly Detection System"
researched_at: 2026-09-08T18:52:00Z
updated_at: 2026-09-08T21:56:00+02:00
recommended_platform: "Railway"
runner_up: "Render"
context_type: mvp
tech_stack:
  backend_language: "Python 3.10+"
  backend_framework: "FastAPI 0.115.12"
  frontend_language: "TypeScript"
  frontend_framework: "React"
  persistence_target: "Railway PostgreSQL"
  runtime: "FastAPI API, React static build, finite on-demand inference service"
---

## Recommendation

**Deploy the MVP on Railway.**

Railway fits the selected brownfield stack: the existing FastAPI control plane, a thin
React/TypeScript UI, Railway PostgreSQL, and a private Railway Bucket can operate in one
single-region project. The API and finite inference service can use Railway Serverless:
they wake only for an HDFS request, then sleep when quiet. This aligns the cost model with
rare thesis demonstrations rather than paying to retain a model-loaded worker.

Hobby has a $5/month minimum that includes the first $5 of resource usage; PostgreSQL
remains a durable allocated service, while the sleeping API and inference services do not
accrue compute charges when inactive. The decision remains limited to the HDFS-only MVP
and does not claim that the inference artifact contract is already implemented.

## Platform Comparison

Scores use the project platform criteria as of 2026-09-08. `Pass` means the capability is
officially supported; `Partial` means an important operational action still needs a
dashboard or a separate API workflow.

| Platform | CLI-first | Managed / serverless | Agent-readable docs | Stable deploy API | MCP / integration | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Railway | Partial | Pass | Pass | Pass | Pass | Recommended |
| Render | Partial | Pass | Pass | Pass | Pass | Runner-up |
| Fly.io | Pass | Pass | Pass | Pass | Partial | Third |
| Vercel | Pass | Pass | Pass | Pass | Pass | Not shortlisted |
| Cloudflare Workers + Pages | Pass | Pass | Pass | Pass | Pass | Dropped: Python runtime is beta |
| Netlify | Fail | Pass | Pass | Pass | Pass | Dropped: no supported Python function runtime |

### Platform notes

- **Railway:** Python/container workloads, PostgreSQL, and S3-compatible Buckets can be
  placed in one project. The official CLI supports deploys, variables, logs, metrics, and
  JSON output; its hosted and local MCP server supports operational queries and redeploys.
  An arbitrary rollback still requires the dashboard, so CLI-first maintenance is partial.
  The Free plan includes only $1/month after the trial; Hobby is $5/month with that amount
  applied to usage. On-demand API/inference compute is small for rare runs, but PostgreSQL
  and active inference time remain cost drivers.
- **Render:** Supports Python web services, persistent background workers, PostgreSQL, and
  Key Value in one managed platform. Its CLI and MCP support deploys and log inspection;
  arbitrary rollback is via the REST API or dashboard, so CLI-first is partial. Free web
  services spin down after 15 minutes and free PostgreSQL expires after 30 days, while
  background workers are paid; the $7/month Starter web service is a realistic minimum
  before a paid worker and durable database.
- **Fly.io:** Strongest terminal workflow (`flyctl`), full Python container support, and
  persistent worker/WebSocket capability. New organizations have no meaningful ongoing
  free allowance, and managed Postgres is a separate, relatively costly product. Its MCP
  tooling is primarily for hosting/proxying MCP servers rather than broad agent-operated
  platform management. It is viable, but less cost-aligned and less integrated than
  Railway for this MVP.
- **Vercel:** Python Functions and Fluid Compute are supported. The Hobby tier includes
  one million invocations, but long-running ML work has function duration, package-size,
  and memory constraints. Large Python Functions (up to 5 GB) and extended 30-minute
  duration are **public beta**; this is unsuitable as the foundation for the required
  durable analysis worker. It remains a good frontend option, not the recommended
  all-in-one analysis platform.
- **Cloudflare Workers + Pages:** Excellent low-cost edge tooling, CLI, documentation, and
  managed data primitives. However, Python Workers use a Pyodide/WASM execution model and
  are **open beta** (requiring the `python_workers` compatibility flag); compatibility
  with the existing scientific/ML stack cannot be assumed. It is excluded rather than
  risking notebook-parity regressions.
- **Netlify:** Strong documentation, CLI, deploy previews, managed database/Blob services,
  and an official MCP server. Its current Functions documentation targets JavaScript,
  TypeScript, and Go rather than this Python service/worker workload, so it fails the
  runtime hard constraint.

### Shortlisted Platforms

#### 1. Railway (Recommended)

Railway places the existing FastAPI API, React build, private on-demand inference service,
PostgreSQL, and S3-compatible Bucket in one project. The API and inference service sleep
when quiet; the $5 Hobby minimum is a predictable starting point, but not a guarantee that
PyTorch/PyG inference fits within its included usage.

#### 2. Render

Render is the closest alternative: it supports the same Python web/database topology,
declarative `render.yaml` Blueprints, a CLI, and hosted MCP. It ranks below Railway because
the chosen on-demand service model and co-located Bucket/PostgreSQL story are more direct
on Railway for a short-lived MVP.

#### 3. Fly.io

Fly.io is a capable Python-container choice with the most complete CLI and useful
auto-stop/start controls. It ranks third because new-user costs start immediately and
managed Postgres co-location is materially more expensive than the intended very-small
MVP budget.

## Anti-Bias Cross-Check: Railway

### Devil's Advocate — Weaknesses

1. The $5 Hobby floor is not a free production tier. PostgreSQL remains allocated, and a
   single unexpectedly large PyTorch/PyG run can exceed the included monthly usage.
2. Arbitrary rollback is dashboard-only. The CLI supports redeploy and restart, but an
   agent cannot independently restore any historical deployment through the documented
   CLI workflow.
3. Automatic Railpack builds may not reproduce the scientific Python environment or
   required native libraries. A Dockerfile may be necessary, increasing implementation
   work and image-size risk.
4. Railway Serverless may not sleep if a service sends network traffic through polling,
   persistent database connections, or telemetry; a design intended to be cheap can
   silently behave like an always-on service.
5. The current codebase is notebook-led. Splitting it into a web API and inference service can
   change numerical behavior unless the existing shared modules and parity fixtures remain
   the implementation source of truth.

### Pre-Mortem — How This Could Fail

The thesis demonstration fails because it was treated as a routine Python web deployment.
Railway builds from `requirements.txt`, which intentionally omits PyTorch and PyTorch
Geometric, so the inference service cannot start or cannot load the approved model. A
rushed Linux-wheel fix changes numerical behavior from the notebook baseline. The sleeping
API is then woken for a demonstration and the first request is delayed or returns a
transient 502 without a retry. Finally, the inference service is implemented as a polling
worker or retains a database connection, so it never sleeps and consumes budget while
idle. The safe model-artifact contract is still missing, so loading a registered artifact
would breach the API's security boundary. Mitigate this with one representative HDFS
end-to-end deployment, a Linux-specific pinned inference environment, retryable
cold-start invocation, a finite non-polling run contract, and notebook-parity verification.

### Unknown Unknowns

- Railway Buckets are private and S3-compatible, cost $0.015/GB-month, and have free API
  operations and Bucket egress. They do not provide object versioning, lifecycle rules,
  object locks, or configurable server-side encryption; use immutable keys and
  PostgreSQL-held checksums instead.
- Private API-to-inference traffic wakes a sleeping service, but it also counts as activity.
  Both services only sleep when no request, database pool, telemetry, or other outbound
  traffic remains after the finite run completes.
- Bucket access uses public networking even within Railway. Use Bucket variable references
  only in the service that needs them and account for service egress on uploads.
- Railway MCP exposes destructive actions. Read-only operations are allowed by default;
  every project/environment-scoped deploy, variable change, scaling action, bucket
  credential reset, deletion, or production rollback requires explicit human confirmation.
- The selected React UI must not use persistent WebSocket sessions for this MVP. It polls
  the existing FastAPI run-status endpoint at a bounded interval while the page is open.

## Operational Story

- **Preview deploys:** Create a Railway `staging` environment and manually deploy the API,
  React build, and inference service only for a test. Remove the test deployment with
  `railway down --service <name>` when it is no longer needed; no pull-request deployment
  automation is configured.
- **Secrets:** Keep credentials in Railway service variables, set with
  `railway variable set KEY=value`. Provide Bucket credentials through service-specific
  variable references, never the React build. Rotate a secret by setting its replacement,
  redeploying affected services, then deleting the old value.
- **Rollback:** A human selects a retained successful deployment in the Railway dashboard
  and confirms rollback; Railway restores its image and custom variables in seconds.
  Database migrations, stored uploads, and external artifacts are not rolled back.
- **Approval:** Require a human to approve production publication, arbitrary production
  rollback, primary-secret or Bucket-credential rotation, database deletion, and any schema
  migration. An agent may read project-scoped status/logs; any MCP mutation requires the
  user to name the target project and environment and explicitly approve the action.
- **Logs:** Read current output with `railway logs -n 100`, build logs with
  `railway logs --build`, and deployment history with `railway deployment list`. The
  Railway MCP `get_logs` operation is appropriate for bounded, read-only agent log review.

## Risk Register

| Risk | Source | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| One inference run exceeds included Hobby usage | Devil's advocate | M | M | Set a Railway spend limit/alert before the first test; run one representative HDFS analysis and size the inference service from measured peak RSS. |
| Python scientific dependencies fail in automatic build | Devil's advocate | M | H | Build and test a reproducible deployment image early; pin runtime dependencies and verify notebook-parity metrics before release. |
| Services fail to sleep and behave as always-on | Devil's advocate / Research finding | M | M | Do not poll; close idle database connections; disable nonessential telemetry; verify services sleep after a test run. |
| An agent performs an unintended Railway mutation | Unknown unknowns | L | H | Use project/environment-scoped credentials and require explicit human approval for every MCP or CLI mutation. |
| Bucket artifacts are overwritten or cannot be recovered | Unknown unknowns | M | H | Use immutable project/version keys, checksums in PostgreSQL, and explicit deletion only after review. |
| On-demand inference changes notebook evaluation results | Pre-mortem | M | H | Keep parsing, enrichment, sequencing, graphs, and artifact behavior in `src/modules/`; execute HDFS parity tests against the agreed baseline before publishing a model. |

## Getting Started

1. Use the selected stack in `context/foundation/tech-stack.md`: FastAPI control plane,
   React/TypeScript UI, Railway PostgreSQL, Railway Bucket, and a finite inference service.
   Do not deploy the notebook directory directly.
2. On macOS, install the current Railway CLI with `brew install railway`, verify the
   installed version with `railway --version`, and authenticate using `railway login`.
   Railway MCP requires CLI 5.44.0 or later when connected through the CLI.
3. Create a Railway staging project with `railway init`, add PostgreSQL with
   `railway add --database postgres`, and create a Bucket for model and parser/config
   artifacts. Keep its credentials private and service-specific.
4. Build the React static UI and the FastAPI API as the initial public service; add the
   private inference service only after the non-executable artifact contract and
   Linux-specific PyTorch/PyG dependencies are verified.
5. Deploy a representative HDFS test with `railway up --detach`, inspect it with
   `railway deployment list` and `railway logs -n 100`, confirm the API/inference services
   sleep after completion, then remove the test deployment when it is no longer needed.

## Research Sources

- [Selected brownfield technology stack](tech-stack.md)
- [Railway pricing](https://docs.railway.com/pricing) and
  [machine-readable pricing](https://railway.com/pricing.md)
- [Railway CLI reference](https://docs.railway.com/guides/cli)
- [Railway MCP server](https://docs.railway.com/ai/mcp-server) and
  [rollback guidance](https://docs.railway.com/guides/roll-back-bad-deploy)
- [Railway Serverless](https://docs.railway.com/deployments/serverless) and
  [Railway Buckets](https://docs.railway.com/storage-buckets)
- [Render free-tier limitations](https://render.com/docs/free) and
  [Render CLI](https://render.com/docs/cli)
- [Fly.io pricing](https://fly.io/docs/about/pricing/) and
  [Python deployment guide](https://fly.io/docs/python/)
- [Vercel function limitations](https://vercel.com/docs/functions/limitations) and
  [Fluid Compute](https://vercel.com/docs/fluid-compute)
- [Cloudflare Python Workers](https://developers.cloudflare.com/workers/languages/python/)
  and [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)
- [Netlify Functions overview](https://docs.netlify.com/build/functions/overview/) and
  [pricing](https://www.netlify.com/pricing/)

## Out of Scope

The following were not evaluated in this research:

- Docker image configuration
- CI/CD pipeline setup
- Production-scale architecture (multi-region, high availability, and disaster recovery)
