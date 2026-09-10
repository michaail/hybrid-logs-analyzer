---
date: 2026-09-10T13:05:05+02:00
researcher: michalklos
git_commit: 7b80fda0581f97cadda6587cadf820d07183035f
branch: feature/Slice-02
repository: hybrid-logs-analyzer
topic: "publish-hdfs-model-package (S-02: Publisher upload, validate, explicit publish)"
tags: [research, codebase, model-package, fastapi, publisher, frontend, storage]
status: complete
last_updated: 2026-09-10
last_updated_by: michalklos
---

# Research: publish-hdfs-model-package (S-02: Publisher upload, validate, explicit publish)

**Date**: 2026-09-10T13:05:05+02:00
**Researcher**: michalklos
**Git Commit**: 7b80fda0581f97cadda6587cadf820d07183035f
**Branch**: feature/Slice-02
**Repository**: hybrid-logs-analyzer

## Research Question

How does the live HDFS control plane currently let a Publisher register, reject, and explicitly publish a model package, and what remains for roadmap S-02 (`publish-hdfs-model-package`: upload a complete HDFS-compatible package, clear ineligibility rejection, explicit publish of the eligible version) relative to PRD US-01 / FR-002 / FR-003 / FR-004 / FR-008?

## Summary

F-02 already shipped the non-executable package contract, isolated `weights_only=True` probe, structured 422 rejection, and directory admission. Explicit publish (FR-004) is live in API and UI: register creates `eligible`, a second Publisher action flips `published`, Operators get 403, and analysis requires a same-project published version. F-01 added `storage_kind` / `checksum` columns, but registration still writes `workspace` path pointers with a null checksum.

The S-02 gap is **bytes intake**, not the publish gate. There is no multipart, `UploadFile`, `FormData`, or file input anywhere in `src/` or `frontend/`. HTTP registration accepts only a workspace-relative **directory** `package_reference`; a ZIP path is 422 with no row. The reusable library can unpack a ZIP under caps, then deletes the extract — it is not an admission-storage operation. Railway Bucket / object-kind materialization of **declared files only** is still unimplemented. PRD Open Question 2 and F-02 docs call this deferral by design, not a contradiction with US-01’s “upload” wording.

GitHub permalinks are omitted: `feature/Slice-02` has no upstream and this commit is not pushed.

## Detailed Findings

### Package contract (F-02, reusable)

`src/modules/model_package.py` is Torch-free. A closed `manifest.json` (`extra="forbid"` on the package model) requires:

- `source_compatibility: "hdfs"` and `format: "attribute-aware-gae-v1"`
- `metrics.best_threshold` finite (`PackageMetrics` allows extra metric keys)
- declared `files.artifact` (must end `.pt`) and `files.evidence` with **exactly** those two SHA-256 checksums
- architecture + scoring fields used later to check state-dict keys/shapes/dtypes

Defaults: `model.pt`, `evidence.json`. Extra **undeclared** files are not enumerated, so they do not fail eligibility (documented in `README.md:382-383`). Extra **manifest** keys are rejected.

ZIP transport exists only in `validate_model_package_source` (`src/modules/model_package.py:330-339`): 64 members, 32 MiB compressed, 96 MiB uncompressed; zip-slip, absolute paths, `..`, symlinks, and nested archives are rejected. Extraction is temp and always deleted. The helper never returns a `<zip>#<member>` identity.

The isolated process `python -m src.model_validator` loads tensors with `torch.load(..., map_location="cpu", weights_only=True)` (`src/model_validator/runtime.py:68-76`) and scrubs application/cloud secrets from the child environment. FastAPI never imports Torch and never deserializes `.pt`.

### Registration API (admission today)

`POST /projects/{project_id}/models` (`src/api/main.py:376-441`) is JSON `{ "package_reference": "..." }` only (`src/api/schemas.py:152-155`).

Sequence:

1. JWT bearer → active user (`src/api/main.py:71-86`); missing/inactive → 401.
2. `require_project_role(..., {PUBLISHER})` (`388`). Operator → 403. Non-member → 404 (hides project existence). Administrator bypasses the role set.
3. `trusted_package_directory` (`src/api/validation.py:48-56`) resolves under `API_TRUSTED_WORKSPACE_ROOT`. **Files and ZIPs are rejected here** before the validator runs.
4. `run_private_package_validator` subprocess, 120s, scrubbed env (`59-85`). Failure/timeout/non-JSON → **503**, no insert.
5. Invalid report → **422** `detail = { valid, issues: [{path, reason}, ...] }`, no insert.
6. `admit_validated_package` (`88-126`) re-reads the manifest, rejects artifact symlinks, re-hashes SHA-256, copies identity. Paths stored are workspace-relative POSIX.
7. `ApiDatabase.create_model_version` (`src/api/storage.py:474-541`) inserts `status='eligible'`, `source_compatibility='hdfs'`, default `storage_kind='workspace'`, `checksum=None`, then audit `model.registered` in the same session. Duplicate `(project_id, model_identifier, version)` → **409**.

`GET /projects/{project_id}/models` lists **eligible and published** for any project member.

### Publish API (FR-004 already done)

`POST /projects/{project_id}/models/{model_version_id}/publish` (`src/api/main.py:460-485`):

- Publisher (or Administrator) only.
- Missing / wrong project → 404.
- Status not `eligible` → 409 `"Only eligible model versions can be published."`
- CAS `UPDATE ... WHERE id = ? AND status = 'eligible'` (`src/api/storage.py:572-579`) sets `published_at` and `published_by_user_id`, then audit `model.published` (`details_json` is only identifier + version).
- If the CAS updates 0 rows, storage raises `ValueError`. `main.py` does not map that race to 409 (would be an unhandled 500).

Analysis create (`src/api/main.py:506-520`) requires `status == published` and `model.project_id == request project`; otherwise 409 / 404. Publishing does **not** enable inference: valid logs still finish `not_supported`.

### Persistence vs F-01 object pointers

`model_versions` (`src/api/migrations.py:46-62`) plus F-01 `storage_kind` / `checksum` (`351-354`) plus F-02 `package_reference` / `artifact_sha256` (`162-170`). Status CHECK: `'eligible' | 'published'` only.

Bytes never enter the database. Register never passes `storage_kind="object"`. Datasets have a SQL CHECK that object kind needs a checksum; **model_versions does not** — only `_normalized_checksum` in Python. There is no Bucket/S3 client. `ApiSettings` (`src/api/settings.py:13-21`) has workspace root, not object-store config.

Tech-stack target keys `projects/<project-id>/models/<model-id>/<version>/manifest.json` (`context/foundation/tech-stack.md:77-82`) are not implemented. Model id is assigned at INSERT (`uuid4()` in `create_model_version`), so a presigned-upload-before-insert flow must pre-generate the UUID or content-address another way.

### Publisher UI and client

`frontend/src/App.tsx`:

- Models empty state: “pre-staged HDFS model package directory” (`575-578`).
- Dialog: one text field `package_reference`; warning “Browser artifact uploads are intentionally unavailable” (`1238-1295`).
- Explicit “Publish version” on `eligible` cards (`621-624`); register notice says “registered as eligible” (`239-245`).
- Select-for-analysis is disabled unless published (`613-618`).
- Register / Publish buttons are **not** hidden by role; Operators see them and the API returns 403.
- `publishedModels` (`53-56`) is computed and unused.

`frontend/src/api.ts`: `ModelStatus = "eligible" | "published"`, `StorageKind = "workspace" | "object"`, `registerModel` / `publishModel` JSON only (`182-192`). `responseMessage` already joins 422 `issues[].reason`. CSP `connect-src 'self'` (`src/api/main.py:737-742`) would block a browser PUT to a cross-origin Bucket unless the policy changes or upload stays same-origin.

### AuthZ and audit (FR-008)

| Action | Who | Audit |
| --- | --- | --- |
| Register | Publisher / Admin | `model.registered` (artifact path, sha256, package_reference, identifier, version, pipeline_run_id) |
| Publish | Publisher / Admin | `model.published` (identifier, version); publisher id/time on the **row** |
| Upload | **no endpoint** | **no `model.upload` event** |

Project audit (`GET /projects/{id}/audit-events`) is Administrator-only. System audit lists user-resource events only — model events are project-scoped.

Deactivated accounts lose access on the next request (401). Publisher ⊇ Operator for analysis routes (`src/api/main.py:111-112`).

### Tests that lock current S-02-adjacent contracts

- Operator register 403: `tests/test_api.py:397-403`
- Operator publish 403; Publisher eligible → published: `tests/test_api.py:407-441`
- Direct ZIP → 422, empty model list: `tests/test_api.py:878-891` (**this assertion inverts if ZIP becomes an HTTP source**)
- Checksum + empty evidence collected in one 422: `tests/test_api.py:894-907`
- Dummy/pickle vs real tensors: `test_http_admission_uses_real_validator_probe` (`@pytest.mark.ml`)
- Validator crash → 503, no row
- ZIP caps / zip-slip: `tests/test_model_package.py` (library only, not HTTP)
- Secrets scrub: `tests/test_model_validator.py`

There is **no dedicated test** that an unpublished eligible model cannot start analysis (the check exists at `src/api/main.py:516-520`; the lifecycle test publishes first). Cross-project `model_version_id` 404 is implemented but similarly under-tested.

### PRD / roadmap mapping

| Requirement | Live | S-02 still owns |
| --- | --- | --- |
| FR-003 completeness/compatibility, structured reject, eligible row | Yes (directory) | Apply the same report to uploaded ZIP/bytes |
| FR-004 explicit publish + audit | Yes | Keep; do not auto-publish on upload |
| FR-008 project isolation + audit | Register/publish audited; unpublished not usable for analysis | Do not leak published models across projects; optional `model.upload` audit |
| US-01 / FR-002 “upload” | Path to pre-staged directory only | Browser/HTTP transfer of package bytes; materialize **declared files only** into immutable storage; point row at object-kind + checksum |
| Inference | `not_supported` | Out of scope (S-04) |

## Code References

- `src/modules/model_package.py:17-23` — package names, format, ZIP caps
- `src/modules/model_package.py:60-65` — `best_threshold` required; extra metric keys allowed
- `src/modules/model_package.py:149-160` — closed HDFS `attribute-aware-gae-v1` manifest
- `src/modules/model_package.py:261-327` — directory eligibility without importing Torch
- `src/modules/model_package.py:330-339` — ZIP is library transport, not stored identity
- `src/model_validator/runtime.py:68-82` — isolated `weights_only=True` probe
- `src/api/validation.py:48-56` — HTTP rejects file/ZIP `package_reference`
- `src/api/validation.py:59-85` — subprocess validator; API does not load the artifact
- `src/api/validation.py:88-126` — admit regular-file artifact, re-hash, workspace-relative paths
- `src/api/main.py:103-114` — Publisher ⊇ Operator; 403 on insufficient role
- `src/api/main.py:376-441` — register 201 / 422 / 409 / 503
- `src/api/main.py:460-485` — explicit publish
- `src/api/main.py:513-520` — analysis requires same-project published model
- `src/api/main.py:737-742` — CSP `connect-src 'self'`
- `src/api/storage.py:474-541` — eligible insert + `model.registered`
- `src/api/storage.py:556-598` — publish CAS + `model.published`
- `src/api/schemas.py:152-178` — request is `package_reference` only; response includes `storage_kind` / `checksum`
- `src/api/migrations.py:46-62` — `eligible`/`published` CHECK
- `src/api/migrations.py:162-170` — `package_reference`, `artifact_sha256`
- `src/api/migrations.py:351-354` — F-01 pointer columns
- `frontend/src/api.ts:1-64` — client model types
- `frontend/src/api.ts:182-192` — JSON register/publish, no FormData
- `frontend/src/App.tsx:570-638` — register/publish UI; pre-staged copy
- `frontend/src/App.tsx:1238-1295` — path dialog; uploads unavailable
- `tests/test_api.py:397-403` — Operator cannot register
- `tests/test_api.py:428-441` — Operator cannot publish; Publisher can
- `tests/test_api.py:878-891` — direct ZIP 422 (current HTTP contract)
- `README.md:360-394` — directory-only admission; later slice must materialize ZIPs
- `context/foundation/prd.md:58-69` — US-01
- `context/foundation/prd.md:180` — browser upload deferred; current path is pre-staged directory
- `context/foundation/tech-stack.md:77-84` — intended object-key shape and presigned URLs

## Architecture Insights

- **Eligibility and publication are separate states on purpose.** F-02 and the Socrates note on FR-004 treat auto-publish as the failure mode. S-02 should add upload **in front of** the existing register → eligible → publish pipeline, not collapse it.
- **Validate in an isolated process; persist only after a typed report.** The API authorizes, consumes JSON, and re-hashes. Torch stays out of the request process. Uploaded bytes need a temp location the validator can read **without** Bucket/JWT/DB secrets in that process (`allowed_validator_environment` already strips them).
- **Declared-files-only materialization is a hard F-02 follow-on.** Ignoring extra files is safe only if S-02 does not copy the whole tree. Persist `manifest.json` + declared artifact + declared evidence (and checksums), then point `package_reference` at that immutable directory/object prefix.
- **ZIP admission is two-stage.** Library unpack is proven; HTTP currently rejects archives. S-02 should validate ZIP (including **bytes written** vs caps — F-02 impl-review F7), materialize declared files, then call the same directory contract. Do not persist `<zip>#<member>`.
- **Object-kind is schema-ready, not wired.** `create_model_version` already accepts `storage_kind`/`checksum`; register never passes them. S-02 should set `object` + a non-empty checksum when bytes leave the trusted workspace. Consider a SQL CHECK matching `datasets`.
- **Workspace registration cannot ship on Railway as-is.** Deploy notes: staging has no usable trusted workspace for Publisher-staged directories. That is why S-02 is the north-star slice.
- **Do not use the research loader for admission.** `src/modules/model.py` still has `weights_only=False` for notebooks; health-check and AGENTS.md forbid passing uploaded artifacts to that path.
- **UI is a thin client.** Permissions and lifecycle are server-enforced. Hiding Register/Publish from Operators is UX, not a security control. Keep API 403 tests. Avoid resurrecting “pipeline manifest” copy (F-02 impl-review F1).
- **Lessons.md** does not constrain this slice’s design; implement-time rules are “A/B test a Cursor rule” and “delete unused code after impl-review with operator confirmation” (`publishedModels` is unused today).

Files a planner should expect to touch (no implementation here): `src/api/main.py`, `schemas.py`, `validation.py`, `storage.py`, `settings.py`, possibly `migrations.py`; new object-store adapter; `src/modules/model_package.py` materialize helper; `src/model_validator` if the CLI must accept a ZIP; `frontend/src/App.tsx` + `api.ts`; invert or extend `tests/test_api.py:878-891`; README / `.env.example` / deploy-plan.

Unlikely to need changes for the publish **button** itself: `publish_model_version` in `main.py` / `storage.py`.

## Historical Context (from prior changes)

- `context/archive/2026-09-09-trusted-model-package-contract/plan-brief.md` — F-02: library + directory admission; “S-02 still owns browser upload”; ZIP is transport; “Ignoring extra files is safe only if S-02 later stores declared files only”; “Publish stays explicit. Inference stays unavailable.”
- `context/archive/2026-09-09-trusted-model-package-contract/plan.md` — HTTP must not extract zips today; S-02 validates ZIP then copies **only declared files** into immutable F-01 storage before this route registers that directory. No ZIP-member artifact identity.
- `context/archive/2026-09-09-trusted-model-package-contract/reviews/impl-review.md` — F1 UI copy (pre-staged directory, not pipeline manifest); F2 symlink/`lstat`; F3 validator env allowlist; F7 extract must count **bytes written** when S-02 unpacks; F6 live click-through verification.
- `context/archive/2026-09-09-shared-durable-runtime-state/plan-brief.md` — object-kind rows are repository/test-only until S-02/S-03 supply real keys; Bucket client and multipart upload out of F-01 scope; register/publish remain workspace-kind with null checksum on current HTTP.
- `context/archive/2026-09-09-provision-project-accounts/plan-brief.md` — Publisher role and atomic audit exist; S-01 explicitly out of scope for model publication changes.
- `context/foundation/roadmap.md` S-02 — “Explicit publication of a pretrained PyTorch `.pt` package must not make an eligible model usable outside its authorized project.”
- `context/foundation/prd.md` Open Question 2 — format resolved; current registration is pre-staged directory; browser upload of package bytes is deferred. US-01 still describes the end-state capability S-02 is meant to deliver.

Aligned reading: PRD “upload” is the product end state; F-02 parked the mechanism; S-02 is where upload becomes real. Treating F-02’s “no browser upload” as permanent policy would contradict the same F-02 docs.

## Related Research

No other `research.md` artifacts exist under `context/changes/` or `context/archive/`.

## Open Questions

These are planning decisions, not missing codebase facts:

1. **Transport:** multipart ZIP to FastAPI (same-origin, CSP-friendly) vs presigned PUT to Railway Bucket (requires CSP / `connect-src` change and a Bucket adapter F-01 left out)?
2. **Keep directory `package_reference`?** Dual path for local/dev, or ZIP/upload only once object storage exists?
3. **Object key assignment:** tech-stack uses `model-id` assigned at INSERT — pre-generate UUID, or content-address by `artifact_sha256`?
4. **What is `model_versions.checksum` vs `artifact_sha256`?** Artifact digest is already stored; object kind may want package Merkle, object etag, or the same SHA-256.
5. **Local vs staging storage:** immutable directory under trusted workspace for SQLite/dev vs Bucket-only in Railway?
6. **ZIP layout:** `manifest.json` at archive root (current extractor) vs unwrap a single top-level folder?
7. **Validate-then-store vs store-then-validate** for uploaded bytes, given the validator must not receive Bucket secrets?
8. **HTTP max upload size** vs existing 32/96 MiB / 64-member ZIP caps?
9. **Hide Register/Publish from Operators in the UI**, or keep API-only 403?
10. **Add tests** for unpublished analysis 409 and cross-project model id 404; map publish CAS `ValueError` to 409; optional SQL CHECK on model object+checksum.
11. **Producer:** hand-built ZIP still, or a notebook/pipeline exporter (F-02 left exporter out of scope)?
12. **`external_evaluation_evidence` after object storage:** keep relative path `evidence.json`, object key, or inlined JSON?
