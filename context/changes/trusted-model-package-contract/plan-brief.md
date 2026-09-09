# Trusted model package contract — Plan Brief

> Full plan: `context/changes/trusted-model-package-contract/plan.md`

## What & Why

F-02 defines the non-executable HDFS model-package contract that must pass
before a model can enter the workflow. Publishers already register models
through FastAPI; that path currently trusts a pipeline-run pointer and never
inspects the `.pt`. This change makes eligibility a declared package check in
a dedicated, minimally privileged validation process so the public API never
deserializes Publisher artifacts.

## Starting Point

`POST /projects/{project_id}/models` validates a workspace run manifest and a
canonical `attribute_gae.pt` path, then stores an `eligible` version. Tests
register dummy bytes. Training still saves combined pickle checkpoints loaded
with `weights_only=False`. Explicit publish and `not_supported` analysis
already exist. There is no package layout, SHA-256, zip rule, or tensor-only
probe.

## Desired End State

The reusable validator accepts a package directory or ZIP transport. The
current registration API accepts only a pre-staged immutable package
directory, and only when its manifest, HDFS compatibility, evidence file,
checksums, and `attribute-aware-gae-v1` state-dict keys/shapes/dtypes all
check out. Extra undeclared files are ignored. Invalid packages return one
structured 422 listing every issue. S-02 will later validate ZIP transport
and materialize declared files in F-01 storage. Publish stays explicit.
Inference stays unavailable.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Slice boundary | Library plus current admission; no upload API | F-02 must replace dummy-byte registration now; S-02 still owns browser upload. |
| Canonical unit | Directory with `manifest.json`; ZIP is library transport, not a current registration source | Current API has no archive-member resolver; S-02 materializes validated ZIP contents in F-01 storage. |
| Artifact payload | `attribute-aware-gae-v1` tensor-only `.pt`, statically checked with `weights_only=True` | Current pickle checkpoints are unsafe; key/shape/dtype checks make the artifact reconstructable without running the GAE. |
| Origin | Any authorized Publisher package matching the contract | Matches US-01; no signing infrastructure for the thesis MVP. |
| Evidence | Required `evidence.json` in the package | Completeness is checkable without fetching URLs. |
| Integrity | SHA-256 of declared files | Detects swapped artifacts before storage. |
| Rejection | Structured 422 of all issues | PRD requires a clear rejection; one pass to fix. |
| Extra files | Ignore undeclared files; extras count toward zip caps | Allows leftover pipeline files without failing eligibility. |
| Producer | Validator only; no pipeline exporter | Keeps this slice to the contract; fixtures are hand-built. |
| Metrics gate | Finite `best_threshold` only | Completeness, not quality; other keys allowed. |
| Zip safety | 32 MiB / 96 MiB / 64 files; zip-slip and nested archives rejected | Blocks bombs on a small host without GB-scale extracts. |

## Scope

**In scope:**
- Pydantic package contract and directory validator
- Zip unpack with resource and zip-slip limits
- Switch registration to a pre-staged directory `package_reference`
- Additive `package_reference` / `artifact_sha256` columns
- Thin UI field change and structured error display
- Docs closing the model-package format question

**Out of scope:**
- Browser upload, Bucket persistence, isolated inference
- Pipeline exporter, notebook loader changes, BGL packages, quality scoring

## Architecture / Approach

Reusable `src/modules/model_package.py` validates a directory (and zip
transport) without constructing `AttributeAwareGAE`. A private
package-validation process runs the restricted `weights_only=True` probe with
no application secrets; FastAPI authorizes, consumes its typed report, and
records manifest identity plus the artifact digest. It registers only
resolvable files beneath a pre-staged directory; no `<zip>#<member>` reference
is persisted. The React dialog sends only that path.
`torch.load(..., weights_only=False)` remains a research-only path and is not
used for admission.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Directory contract | Schema, SHA-256, evidence, isolated tensor probe | API and validator runtime boundaries must remain separate. |
| 2. ZIP transport | Caps, zip-slip, nested-archive rejection | It validates transport only; S-02 owns materialization for registration. |
| 3. Admission wiring | API, migration, thin UI | Must not enable inference or leak path-escape packages. |
| 4. Docs and verification | README/PRD plus full checks | Sandbox ML failures must not trigger lockfile changes. |

**Prerequisites:** Existing FastAPI registration, trusted workspace, Publisher
role, and explicit publish remain. F-01 storage and S-02 upload are not
required.
**Estimated effort:** ~2–3 sessions across four phases.

## Open Risks & Assumptions

- Ignoring extra files is safe only if S-02 later stores declared files
  only; a whole-tree copy would persist undeclared payloads.
- Without an exporter, Publishers assemble packages by hand until S-02.
- Torch 2.2.2 `weights_only=True` must still be narrowed to a tensor state
  dict in the isolated validator, not trusted as a complete sandbox.
- The format-specific state schema must change only under a new manifest
  format version; it is the compatibility bridge to later inference.

## Success Criteria (Summary)

- A valid HDFS package can be registered as `eligible` and explicitly published.
- Dummy bytes, pickle checkpoints, checksum mismatches, and zip-slip archives
  are rejected with a structured report and no eligible row.
- Analysis of a published model remains `not_supported` until the inference slice.
