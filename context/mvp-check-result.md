# MVP Project Analysis Report

**Assessment scope:** repository source code and documentation only. Visual design,
styling, accessibility, and deployment were intentionally not evaluated.

**Assessed revision:** `309cea3` (`chore(archive): close add-remove-operations`)  
**Assessment date:** 2026-09-14

## Project snapshot

Hybrid Logs Analyzer is an HDFS-only anomaly-detection control plane. A FastAPI API,
private inference worker, isolated model-package validator, and React UI let
project-authorized users register and publish model versions, upload datasets, run
analysis, and inspect traceable results.

## Checklist

### 1. CRUD actions — ✅ Met

The persisted core item **Model Version** has all four operations. It is stored in
the `model_versions` database table (`src/api/migrations.py`, lines 60–76), with
associated object-store package data.

- **Create:** `POST /projects/{project_id}/models` is handled by
  `register_model_version` (`src/api/routers/models.py`, lines 55–157), which calls
  `ApiDatabase.create_model_version`. That method inserts a durable
  `model_versions` row (`src/api/storage.py`, lines 554–632).
- **Read:** `GET /projects/{project_id}/models` and
  `GET /projects/{project_id}/models/{model_version_id}` are handled by
  `list_model_versions` and `get_model_version` (`models.py`, lines 41–52 and
  159–174). Their storage methods query persisted rows (`storage.py`, lines 634–648).
- **Update:** `POST /projects/{project_id}/models/{model_version_id}/publish`
  explicitly transitions an eligible model to published (`models.py`, lines 177–208).
  `ApiDatabase.publish_model_version` persists the status, publication time, and
  publisher (`storage.py`, lines 829–871).
- **Delete:** `DELETE /projects/{project_id}/models/{model_version_id}` removes an
  unused model (`models.py`, lines 211–251). The database method deletes the row,
  records an audit event, and prevents deletion when an analysis run still references
  the version (`storage.py`, lines 690–769).

The update is deliberately a lifecycle transition rather than unrestricted metadata
editing, but it is a user-triggered, persisted update of this central resource.

### 2. Business logic — ✅ Met

The project contains domain-specific HDFS anomaly-detection logic well beyond CRUD.
`score_frozen_hdfs_log` (`src/modules/hdfs_inference.py`, lines 115–190) parses raw
logs, fails on unmatched input, groups events into HDFS block sequences, partitions
the sequences into scored and provisional sets, and returns traceable results.

`_score_selected_sequences` (same file, lines 193–305) builds graph inputs, loads the
approved tensor-only model state with `weights_only=True`, calculates anomaly scores
using package-defined coefficients, and classifies a block when `score > threshold`.
The PRD defines the corresponding user value and rule: catalog-member blocks are
heuristically final while non-members remain provisional and do not affect anomaly or
normal counts (`context/foundation/prd.md`, Business Logic Changes, lines 173–187).

### 3. Tests addressing a defined risk — ✅ Met

`context/foundation/test-plan.md` defines Risk #3: an ineligible package could become
eligible, or a registered-but-unpublished model version could be used for analysis
(lines 51 and 179–184).

Two real pytest integration tests directly cover that stated risk:

- `test_registration_rejects_ineligible_zip_without_inserting`
  (`tests/test_api.py`, lines 1340–1350) expects a structured `422` rejection and
  verifies that no model row or object-store files remain.
- `test_unpublished_eligible_model_cannot_start_analysis`
  (`tests/test_api.py`, lines 1598–1624) registers an eligible model, then verifies
  analysis is rejected with `409` until that version is published and that no run is
  created.

This is a direct test-plan-to-test mapping, rather than a collection of unconnected
tests.

### 4. Authentication tied to a user — ✅ Met

Authentication is tied to provisioned database users. `login`
(`src/api/routers/authentication.py`, lines 19–45) retrieves the stored user,
checks that the account is active, verifies the password, records the sign-in, and
issues a token. Passwords use salted scrypt hashes with constant-time comparison, and
JWTs carry the user UUID as their subject (`src/api/security.py`, lines 35–99).

Each protected request is resolved back to an active database user by
`get_current_user` (`src/api/deps.py`, lines 71–89). Project resources are scoped by
membership and role: `require_project_access` returns `404` for an unauthorized
project and `require_project_role` enforces Publisher/Operator permissions
(`src/api/deps.py`, lines 102–136). Model routes apply those project checks before
listing, creating, publishing, reading, or deleting versions
(`src/api/routers/models.py`, lines 41–52, 72–73, 170–189, and 223–225).

### 5. Documentation — ✅ Met

The repository has both required layers of substantive documentation:

- `README.md` identifies the product as an HDFS-only anomaly-detection control plane
  and names its API, inference worker, validator, and React UI (lines 1–5). It also
  documents the reproducible local setup.
- `context/foundation/prd.md` explains the operational problem and motivation
  (lines 26–40), user-facing success criteria and user stories (lines 49–110), scope
  requirements FR-001 through FR-013 (lines 112–139), and explicit non-goals
  (lines 207–215).

The documentation is specific to the intended workflow, roles, and HDFS-only MVP
boundary; it is not placeholder content.

## Project status

**5/5 criteria met — 100%**

The repository clears the minimal technical foundations assessed here: persisted CRUD,
meaningful domain logic, risk-driven tests, user-tied authentication and authorization,
and written product documentation. This finding does not by itself guarantee
certification; it only identifies no obvious gap in these five technical criteria.

## Priority improvements

No criterion is currently unmet, so no blocking improvement is required for this
checklist.

## Verification limitation

I attempted to execute the two tests mapped to Risk #3 with:

```bash
.venv/bin/python -m pytest tests/test_api.py -m "not ml" \
  -k "registration_rejects_ineligible_zip_without_inserting or unpublished_eligible_model_cannot_start_analysis"
```

The run collected both tests but terminated before execution with a floating-point
exception while NumPy imported under the local Python 3.11 virtual environment. The
test criterion above is therefore based on the located test-plan mapping and test
implementations, not a successful execution in this environment. Re-run the suite in
the repository's supported locked Intel macOS Python environment before using it as
runtime verification.
