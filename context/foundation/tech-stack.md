---
project: "Log Anomaly Detection System"
recorded_at: 2026-09-08
context_type: brownfield
status: selected
sources:
  - context/foundation/prd.md
  - context/foundation/stack-assessment.md
  - src/api/
  - src/modules/
deployment:
  platform: Railway
  region_strategy: single-region
  promotion: manual-test-deployment
---

# Brownfield Technology Stack Contract

## Decision

Extend the existing Python application rather than replace it with a greenfield
starter. Keep FastAPI as the authoritative API, authentication, authorization,
and audit boundary. Add a thin React and TypeScript interface that consumes
that API. Deploy the MVP to Railway with PostgreSQL and private S3-compatible
Railway Buckets. This is a short-lived, HDFS-only thesis MVP; it is not a
production-scale architecture commitment.

## Existing Baseline

| Area | Implemented technology | Boundary to preserve |
| --- | --- | --- |
| Language and runtime | Python 3.10+ | Do not modify the intentional Intel macOS lockfile for deployment. |
| API | FastAPI 0.115.12, Pydantic v2, Uvicorn | `src/api/main.py` is the project-scoped JWT, role, validation, and audit control plane. |
| Authentication | Admin-provisioned accounts, scrypt password hashes, HS256 JWT bearer tokens | The frontend does not make authorization decisions. |
| Metadata persistence | SQLite through `src/api/storage.py` | Migrate the deployed API state to PostgreSQL; keep the model, run, results, and audit contracts. |
| Pipeline | Python modules under `src/modules/`, notebook R&D path, `run_ablation.py` | Keep parsing, enrichment, sequencing, graph, and artifact behavior reusable outside notebooks. |
| Pipeline artifacts | Workspace files and `ArtifactStore` atomic `_SUCCESS.json` manifests | Keep versioned code separate from ignored workspace data, models, caches, and outputs. |
| Quality tools | pytest, Ruff, mypy with the Pydantic plugin | Retain the existing toolchain and HDFS notebook-parity checks. |

The API already records valid HDFS analysis requests as terminal
`not_supported` because inference is deliberately absent. It never deserializes
uploaded model artifacts. Those are intentional security boundaries, not
incomplete API error handling.

## Selected MVP Components

| Area | Selected component | Decision rationale |
| --- | --- | --- |
| Browser UI | React with TypeScript | A thin, stateful user interface for model publication and HDFS analysis that does not duplicate the FastAPI control plane. A React build may initially be served from the API service to limit the deployed surface. |
| API and control plane | Existing FastAPI and Pydantic | Fits the existing code, typed request contracts, JWT authentication, project roles, and generated OpenAPI documentation. |
| Durable relational state | Railway PostgreSQL | Required for shared durable state between the API and inference service; two services must not coordinate through the current SQLite file. |
| Model and parser-config storage | Railway Bucket | Private, S3-compatible storage for immutable, project-scoped model packages and parser/config artifacts. PostgreSQL stores object references, version metadata, and checksums. |
| Analysis execution | Private, on-demand inference service | A separate FastAPI-compatible service is invoked once per HDFS run, loads one approved artifact, persists results, and becomes idle. It is not a polling worker. |
| Hosting | Railway, single region | Supports the selected Python services, PostgreSQL, Buckets, and manual test deployments with acceptable MVP cost and operational overhead. |
| Verification and delivery | GitHub Actions checks; manual Railway test deployment | Tests and static checks run automatically; a live environment is deployed and removed only when explicitly needed for thesis testing. |

## On-Demand Runtime Shape

1. The public FastAPI service authenticates the caller, enforces project access,
   validates the HDFS request, and creates the run record.
2. It invokes the private inference service for that run. The API retries a
   cold-start failure rather than treating the first transient unavailable
   response as a completed analysis.
3. The inference service reads only the authorized model, parser, and
   configuration objects; it writes results and a terminal run status to
   PostgreSQL, then returns.
4. API and inference services use Railway Serverless only when quiet: no
   polling loop, long-lived database pool, heartbeat, or telemetry may keep a
   service awake. PostgreSQL remains durable state and is not expected to
   sleep.

This makes rare inference requests cost primarily for active execution, while
accepting cold-start latency for a thesis demonstration.

## Storage and Isolation

- Use immutable object keys scoped by project and version, for example
  `projects/<project-id>/models/<model-id>/<version>/manifest.json`.
- Store the object key, checksum, model version, source compatibility, and
  project ownership in PostgreSQL. Do not infer a model or config from the
  newest Bucket object.
- Buckets are private. Pass bucket credentials only to the services that need
  them through Railway variable references. Use short-lived presigned URLs for
  authorized browser upload or download when direct object transfer is needed.
- Keep the API process free from model deserialization. The inference process
  remains isolated, has minimal filesystem access, receives no unrelated
  application secrets, and follows the model-artifact security rule.

## Explicit Implementation Prerequisites

The following are selected work, not capabilities that exist today:

1. Define a non-executable, trusted model-artifact contract before inference
   loads any model. Current PyTorch `weights_only=False` paths are not an
   acceptable upload or serving mechanism.
2. Create and test a Linux-compatible, pinned inference dependency contract
   for PyTorch and PyTorch Geometric. It is separate from
   `requirements-macos-intel.lock.txt`, which remains unchanged.
3. Implement PostgreSQL persistence and a migration path from the current
   SQLite repository before the API and inference service share deployed state.
4. Implement the React UI and its API client. It must use the API's
   authentication and project-scoped endpoints rather than reproduce its
   security logic.
5. Implement finite HDFS inference execution, run-state transitions, failure
   handling, and parity verification against the agreed notebook baseline.

## Boundaries

- User-facing MVP support is HDFS only. Existing BGL research code does not
  expand the deployed scope.
- Notebooks remain the research, training, and comparison environment; the web
  application does not add web-based training or model retraining.
- No queue polling, real-time stream processing, WebSocket UI, production
  multi-region design, or automatic production deployment is selected.
- `10x-bootstrapper` is not applicable: it scaffolds greenfield starters and
  must not overwrite this brownfield repository.
