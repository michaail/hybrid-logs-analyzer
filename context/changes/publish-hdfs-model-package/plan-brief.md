# Publish HDFS Model Package — Plan Brief

> Full plan: `context/changes/publish-hdfs-model-package/plan.md`
> Frame brief: `context/changes/publish-hdfs-model-package/frame.md`
> Research: `context/changes/publish-hdfs-model-package/research.md`

## What & Why

A Publisher has no way to submit a complete HDFS model package from outside
the API host and receive either a structured rejection or an eligible version.
This slice adds that admission path so a remote Publisher can get a package
into the existing eligible → explicit-publish lifecycle.

## Starting Point

F-02 already validates a pre-staged directory and probes tensors in isolation.
Explicit publish, Operator 403, and analysis-requires-published are live.
HTTP still rejects ZIP paths; Railway has no usable trusted workspace.

## Desired End State

A Publisher uploads a ZIP in the browser. Invalid packages get a structured
422 and no row. Valid packages become `eligible` with `storage_kind=object`
and only declared files stored. Publish stays a separate click. Inference
stays `not_supported`.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Problem to plan | Off-host admission to 422 or eligible, not rebuild publish | Publish gate already works | Frame |
| Transport | Multipart ZIP to same-origin FastAPI | CSP `connect-src 'self'`; validator reads local temp | Plan |
| Public register API | ZIP upload only; drop `package_reference` | Railway cannot honor a host path | Plan |
| Durable storage | Object-kind adapter: filesystem default, Bucket when configured | Tests stay Bucket-free; staging can persist | Plan |
| Eligibility vs persist | Temp unpack → isolated validator → persist declared files | No durable orphans; validator stays secret-free | Plan |
| Extra ZIP members | Do not copy undeclared files | F-02 extra-file ignore is unsafe if the tree is copied | Research |
| Object checksum | `artifact_sha256` on the object-kind row | Already verified; matches F-01 object pointer rule | Plan |
| ZIP layout | `manifest.json` at archive root | Current extractor; no folder unwrap | Plan |

## Scope

**In scope:** ZIP multipart admission, declared-files materialize, filesystem
+ Bucket adapter, object-kind rows, Publisher file dialog, Railway Bucket
attach, docs, invert HTTP ZIP 422 tests.

**Out of scope:** Auto-publish, inference, dataset upload, public path
registration, presigned PUT, package exporter, Operator button hiding,
`weights_only=False` research loaders, lockfile regeneration.

## Architecture / Approach

Browser ZIP → FastAPI (Publisher) → temp extract → isolated directory
validator → copy three declared files to object prefix
`projects/<project-id>/models/<id>/<version>/` → insert `eligible` → existing
`/publish`. Validator never sees Bucket secrets.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Materialize + filesystem store | Declared-files copy and local object protocol | Copying extras would persist undeclared payloads |
| 2. Multipart ZIP admission | Public register is ZIP; 422/201/409/403 | Must invert ZIP 422 tests without skipping probe isolation |
| 3. Publisher ZIP dialog | File picker + existing 422 Banner | Path/pipeline-manifest copy must not return |
| 4. Bucket, IaC, docs | Staging persistence when configured | Bucket creds must not leak into validator or the client |

**Prerequisites:** F-01, F-02, S-01 done; isolated validator and `/publish` stay.
**Estimated effort:** ~2–3 sessions across four phases.

## Open Risks & Assumptions

- SQLite cannot `ALTER` a CHECK; `004` must rebuild `model_versions` like F-01.
- Duplicate identity after object put must delete the prefix (409 orphans).
- Live Railway Bucket verification is skipped if staging is unprovisioned;
  filesystem adapter is then the recorded result.
- Hand-built ZIPs remain the producer (no exporter).

## Success Criteria (Summary)

- Publisher ZIP upload yields eligible or a clear 422; nothing is auto-published.
- Operators cannot register; unpublished models cannot start analysis.
- Declared files persist as object-kind; extras do not; API still does not
  deserialize `.pt` in-process.
