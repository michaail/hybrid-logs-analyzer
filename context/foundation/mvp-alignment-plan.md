---
project: "Log Anomaly Detection System"
status: approved
created: 2026-09-13
updated: 2026-09-13
purpose: Close remaining MVP validation gaps so supported-package, parity, and deployment claims match the implementation.
---

# Close MVP Validation Gaps

Make the HDFS MVP’s supported-package, parity, and deployment claims internally consistent. The accepted target is v2-only model packages, checksum-pinned trusted release evidence, and a reproducible local Docker Compose deployment; Railway remains an unverified future deployability design.

## Workstreams

| ID | Outcome | Status |
| --- | --- | --- |
| prd-parity-contract | Align PRD to v2-only support and promote the checksum-pinned trusted parity baseline. | pending |
| retire-v1 | Remove v1 package handling and convert fixtures, tests, UI, and active documentation to v2-only. | pending |
| isolated-validator | Implement and test the private validator service and API client integration. | pending |
| compose-acceptance | Add local Compose provisioning, artifact bootstrap, acceptance procedure, and truthful deployment documentation. | pending |
| verify-evidence | Re-run trusted parity and Compose/PostgreSQL acceptance gates; record evidence. | pending |

## Product and evidence boundary

- Amend [prd.md](prd.md) to make `attribute-aware-gae-v2` plus its immutable preprocessing bundle the only accepted package contract. Remove promises to register, publish, select, or execute v1 packages.
- State the intentional non-compatible upgrade: inventory and delete any v1 model rows and their object prefixes with a one-off administrator cleanup before rollout; retain audit history but provide no v1 runtime compatibility. Preserve `feature_contract: notebook_raw_v1`; it names the trusted baseline’s feature semantics and is not a legacy package format.
- Make external-evaluation evidence an attached, non-empty JSON attestation rather than evidence the service can semantically verify as "successful." This matches the current validator and FR-003’s explicit quality boundary.
- Resolve PRD Open Question 3 with an active [hdfs-parity-baseline.md](hdfs-parity-baseline.md), promoted from the approved archived evidence. Pin the v3 package, preprocessing bundle, source corpus, labels, test block IDs, and checksums.
- Narrow FR-011 precisely to the implemented and approved contract: exact decision threshold and absolute tolerance of `0.01` for test F1, PR-AUC, and ROC-AUC. Explicitly exclude ungated `test_precision`, `test_recall`, and `val_*` values from the FR-011 acceptance set. Align [roadmap.md](roadmap.md), [test-plan.md](test-plan.md), and the stale pointer in [configs/hdfs_baseline.yaml](../../configs/hdfs_baseline.yaml).

## Remove v1 implementation support

- Update [src/modules/model_package.py](../../src/modules/model_package.py), [src/modules/inference_bundle.py](../../src/modules/inference_bundle.py), and [src/api/validation.py](../../src/api/validation.py) so the v2 manifest and companion bundle are mandatory and v1 archives receive a clear `422` rejection.
- Add and run the explicit v1 cleanup before the upload gate changes. It must identify `metadata_json.format = attribute-aware-gae-v1` or a missing preprocessing bundle, delete each admitted package prefix through the object-store abstraction, then delete only those model rows after checking that no analysis run depends on them.
- Replace v1 fixtures with v2 package-and-bundle fixtures; update API, contract, inference, and E2E tests to assert v2-only admission and no v1 compatibility path.
- Remove legacy status/copy from [frontend/src/App.tsx](../../frontend/src/App.tsx), [README.md](../../README.md), active deployment docs, and active test strategy. Keep archive documents immutable as historical records.

## Restore isolated package admission

- Add a private `model-validator` HTTP service that receives the bounded package ZIP and required companion bundle ZIP, extracts them in its own temporary directory, runs only the existing `weights_only=True` probe, and returns the typed validation report. It has no database, Bucket/filesystem object-store, or JWT credentials.
- Extend [src/api/settings.py](../../src/api/settings.py) and admission code to call that private service with bounded timeouts and a service-scoped token. Preserve the injectable local command path only where focused tests need it.
- Add a validator-specific image/runtime (including its HTTP dependencies), contract tests for valid, invalid, unavailable, and secret-isolation cases, and update [.railway/railway.ts](../../.railway/railway.ts) plus [deploy-plan.md](../deployment/deploy-plan.md) to describe it as a future private service—not as a validated staging deployment.

## Local Compose acceptance environment

- Add a top-level Compose definition with `postgres`, one-shot `migrate`, `web`, private `inference`, and private `model-validator`. Only `web` publishes a host port.
- Use a named shared filesystem volume for API and inference object storage. The validator gets neither this volume nor application secrets. Bind-mount the checksum-pinned F-03 catalog read-only into inference, and bind-mount supplied release artefacts read-only only into the smoke tooling.
- Require the catalog manifest and its configured SHA-256 at Compose startup; inference health fails when either is absent or mismatched. Upload the trusted v3 model and preprocessing bundle through the Publisher API flow rather than pre-seeding bypassed storage/database rows.
- Provide a committed Compose environment template and an explicit local acceptance procedure: initialize migrations, bootstrap the first administrator through the existing CLI, create roles/project, register and publish the trusted v3 release, upload a bounded valid HDFS fixture derived from the pinned artefacts, execute a run, and verify durable PostgreSQL state, audit events, final/provisional result separation, and failure behavior.
- Reframe [deploy-plan.md](../deployment/deploy-plan.md) and [README.md](../../README.md): Compose is the MVP’s reproducible deployment proof; Railway is retained only as an unexecuted future deployment design. Do not claim Railway staging, Railway Bucket behavior, private Railway DNS, or Railway cold-start behavior as validated.

## Verification and handoff

- Run the supplied trusted release through `scripts/verify_hdfs_parity.py` with explicit paths and retain its generated report outside Git alongside the input checksum manifest.
- Run the targeted v2/admission/validator tests; then run PostgreSQL-marked tests against the Compose PostgreSQL service, API tests, inference ML tests in a normal local terminal, lint, type-checking, frontend build, and the Compose acceptance procedure.
- Capture a concise local acceptance record containing Git commit, Compose image digests, artifact checksums, migration version, command results, and the resulting run/audit IDs. This closes the local-deployment claim without overstating cloud staging evidence.
