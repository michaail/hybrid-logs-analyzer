# Retire v1 and Isolate Validator — Plan Brief

> Full plan: `context/changes/retire-v1-isolate-validator/plan.md`

## What & Why

The PRD is already v2-only, but admission still registers
`attribute-aware-gae-v1` and runs the Torch probe as a local subprocess
inside (or beside) the API. This change deletes leftover v1 rows, rejects v1
uploads with 422, and moves the probe to a private HTTP service with no
DB/JWT/object-store credentials.

## Starting Point

v1 fixtures and E2E seed `tests/fixtures/model_packages/valid_files` with no
bundle. v2 already works via `tests/fixtures/hdfs_inference_release/`.
Cleanup has no CLI; format lives in `metadata_json`. Validator is
`python -m src.model_validator <dir> [bundle-dir]`.

## Desired End State

Publishers can only register `attribute-aware-gae-v2` plus a preprocessing
bundle. An administrator CLI removes leftover v1/null-bundle objects and
rows (skipping models that still have analysis runs). Production admission
POSTs ZIP bytes to a token-gated validator. Compose stays later.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Package contract | v2+bundle only; 422 for v1 | No compatibility path | Alignment |
| Dependent leftovers | Skip row, continue, exit 1 if any skipped | FK RESTRICT; do not delete runs | Plan |
| Cleanup shape | CLI, dry-run default, `--apply` to mutate | Mirror bootstrap; not a silent migration | Plan |
| Fixtures | Default/E2E v2+bundle; keep a v1 422 oracle | Preserve rejection tests | Plan |
| Validator transport | Multipart original ZIPs; extract in validator | Isolation; API stays Torch-free | Alignment / Plan |
| API default | Command (tests) or URL+token; else 503 | No hidden `python -m src.model_validator` in the API image | Plan |
| Validator image | Dedicated `Dockerfile.validator` | Slim Torch+HTTP, not the inference image | Alignment / Plan |
| v1 422 | ZIP-manifest preview **and** contract refuse v1 | Cheap path plus no direct-validator admit | Plan |
| Bundle field | Keep `File(default=None)`; typed 422 in admit | Starlette `File(...)` is not `{valid, issues[]}` | Plan review |
| Railway | Add private service in IaC; prose = unexecuted | Alignment names `railway.ts`; Compose is later | Alignment / Plan |

## Scope

**In scope:** retire CLI; v2-only contract/API/fixtures/E2E/UI/README/PRD lag
copy; validator HTTP + client + image; Railway IaC + deploy-plan phrase;
alignment workstream stamps.

**Out of scope:** Compose; parity re-run / binaries; deleting runs or audit
rows; v1 compatibility; proving Railway staging.

## Architecture / Approach

API preview-reads `manifest.json` from the package ZIP. v1 or missing bundle
→ 422, no put. Otherwise POSTs ZIP bytes to `/internal/packages/validate`
with a service token. Validator unpacks, `weights_only=True` probe, typed
JSON. API then materializes declared files and inserts the DB row last.
Tests inject `model_validator_command` and skip HTTP.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Administrator v1 cleanup | Dry-run/`--apply` CLI + tests | Skipping dependents leaves visible v1 rows |
| 2. v2-only admission | 422 gate, v2 fixtures/E2E, copy | E2E misses the bundle file input |
| 3. Private validator HTTP | Service, client, image, Railway IaC | Accidental JWT/store env on the validator |

**Prerequisites:** `prd-parity-contract` archived; alignment plan approved.
**Estimated effort:** ~3 sessions across 3 phases.

## Open Risks & Assumptions

- Environments with v1 rows must run `--apply` before depending on the new
  gate; skipped dependents stay until runs are retired separately.
- Adding `model-validator` to Railway IaC does not mean staging was applied.
- E2E files-only validator still does not prove the Torch probe; `@ml` does.

## Success Criteria (Summary)

- v1 ZIP → structured 422 and no model row; v2+bundle still registers.
- Cleanup deletes eligible leftovers and fails closed on dependent rows.
- Validator HTTP has no JWT/DB/store; API without command or URL 503s register.
