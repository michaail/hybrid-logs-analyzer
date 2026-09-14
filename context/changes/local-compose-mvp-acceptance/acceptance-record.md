# Local Compose MVP acceptance record

Date: 2026-09-14  
Git commit (committed tree at evidence): `209b1ce7a0f53383f60001c954b1e94c21f3330c` (`209b1ce`)  
Host: Intel macOS, local ML venv (Python 3.11.4, torch 2.2.2), Docker Compose `2.0.0-beta.1`  
Railway: **not exercised**

The Operator log for the recorded Compose run is the committed golden fixture
`tests/fixtures/hdfs_inference_release/hdfs.log`. That run is **not FR-011**.
FR-011 is `scripts/verify_hdfs_parity.py` against
`context/foundation/hdfs-parity-baseline.md`.

Uncommitted at evidence time (land with this change, not in `209b1ce`):

- `requirements-model-validator.txt` — `numpy==1.26.4` (admission blocker: validator
  `ModuleNotFoundError: No module named 'numpy'` in `inference_bundle._embedding_issues`)
- `tests/test_migrations.py` — Postgres `pg_indexes` pretty-prints `CASE` with newlines
  and extra parentheses; assertion compacted so `@pytest.mark.postgres` matches the
  same index SQL

Do not commit `compose.env`, ZIPs, `.pt` files, corpus logs, or
`releases/hdfs/v3/parity-report.json`.

## Compose image digests (run evidence, not a lockfile)

| Image | Id |
| --- | --- |
| `analyzer-web:local` | `sha256:2429734cb1be20d39356f3b3d9d2429089d4bec34e90809719cd504da7d28853` |
| `analyzer-inference:local` | `sha256:70db368c59f43120656051405b66444dd69f3773a28d32a060bbc414f8f3d4e5` |
| `analyzer-model-validator:local` | `sha256:dc64986e0c4822b136eab814abdc4460b820b2ad29db6574f8d99fdbb4f27884` (rebuilt after numpy pin; superseded `68a7120b48b1…`) |
| `postgres:16` | `sha256:fd39e733ee5adf1338780bf5ccb0f83422fff394dd22b1ba6303637ba642df13` |

Published host ports: web `8000→8080`, postgres `5433→5432`. Inference and
validator stayed private.

## Artifact checksums

Restated from `context/foundation/hdfs-parity-baseline.md` and verified on disk:

| Artefact | SHA-256 |
| --- | --- |
| `releases/hdfs/attribute-gae-v3.zip` | `7df39cb47490eca6c4af36b78ba9426904038f5d54654cb23661f80bef09181b` |
| `releases/hdfs/attribute-gae-preprocessing-v3.zip` | `e2af6e3a0321fc4c8fdd7a20648dbdd7d93838e170731b112c47163325c413d7` |
| Exported `model.pt` (package member / registered artifact) | `82a4a69acb3365be11aabecb2511812bcc4416a54660f0a487d393b31b5cd29d` |
| F-03 catalog `manifest.json` | `acdaa26f7f39a78a47e9c46f9dbfca0d83714d8afb15108334ed818c5b771e1f` |
| Golden fixture `tests/fixtures/hdfs_inference_release/hdfs.log` (dataset checksum) | `ea5194c5b806fb8d506d7501d9db0bbd246ab70e2f19c70d7d3b8373bc0394cf` |
| Immutable expected record `releases/hdfs/v3/expected.json` | `54e48dbd76aa3c1bfa210c615002e43d0b8814c21936ef5dbbfb055cb45e9b02` |

Catalog bind: gitignored
`artifacts/cache/hdfs/evaluation-data/bf2ac7cdc7a73d18c929/`
(`manifest.json` + sibling `selected-block-ids.txt`).

## Migration version

`schema_migrations` on Compose Postgres: `001` through `008_provisional_hdfs_results`.

## Commands and exit codes

| Step | Result |
| --- | --- |
| Sequential `docker compose --env-file compose.env build` web, inference, model-validator, then `up -d` | exit 0 |
| Rebuild `model-validator` after numpy pin | image `dc64986e0c48…` |
| `GET http://127.0.0.1:8000/health` | 200 `{"status":"ok"}` |
| Inference `GET /health` (via Compose DNS) | 200 `{"status":"ok"}` after catalog pin restored |
| Validator `GET /health` | 200 `{"status":"ok"}` |
| Publisher register **v3** | 201 `eligible`, `inference_ready: true`, version `v3` |
| Publisher publish | 200 `published` |
| Operator dataset upload (golden fixture) | 201 |
| Analysis create | 202 `queued` → `running` → `completed` |
| Validator stopped → register | 503 `{"detail":"Model package validator is unavailable."}`; `GET /models` still one published row |
| Catalog SHA override → inference `/health` | 503 `{"detail":"The pinned HDFS reference catalog is unavailable or failed verification."}` (not all-provisional). Pin restored; inference healthy again |
| `TEST_DATABASE_URL=postgresql://analyzer:analyzer@127.0.0.1:5433/analyzer python -m pytest tests/test_migrations.py tests/test_shared_state_repository.py -m postgres` | exit 0, 2 passed |
| Targeted API / admission / validator / compose contract (`-m "not ml"`) | exit 0, 174 passed, 2 skipped (postgres unset in that process) |
| `ruff check src tests scripts run_ablation.py` | exit 0 |
| `mypy` | exit 0 |
| `npm --prefix frontend run build` | exit 0 |
| `pytest -m ml` (inference, parity helpers, validator probe, package, API) | exit 0, 26 passed |
| `python scripts/verify_hdfs_parity.py` with baseline paths including `--test-block-ids` | exit 0, ~21 min; `passed: true` |

Compose `2.0.0-beta.1` notes: `docker compose exec -T … python -c` often swallows stdout;
host `curl` / `docker exec` used instead. Recreating inference without `--no-deps`
recreates postgres on this Compose version.

## Compose run and audit IDs

| Item | ID |
| --- | --- |
| Project | `a6c2f2d3-c6df-42df-bb09-0a4c113b1182` (`compose-acceptance-1789345015`) |
| Model | `c7f90a9e-df8f-4d9a-ae1d-ba053fc4ab1f` (`attribute-gae` `v3`) |
| Dataset | `c4143cfa-48b2-4d89-b065-2888b75f633b` |
| Run | `3daeda24-fa7b-455d-8120-e5875077ed06` (`completed`) |
| Publisher | `696a94ee-c06a-44ec-8487-910e5551e576` (`publisher-1789345015`) |
| Operator | `b694e051-6f21-4a9f-882d-22baa91638dd` (`operator-1789345015`) |

Results summary: `anomaly_count=0`, `provisional_count=2` (`blk_1`, `blk_2`,
`not_in_reference_catalog`). Catalog SHA in the run trace:
`acdaa26f7f39a78a47e9c46f9dbfca0d83714d8afb15108334ed818c5b771e1f`.

Audit actions (admin `GET /projects/{id}/audit-events`; field is `action`):

| Action | Event ID |
| --- | --- |
| `project.created` | `b42bed94-2f66-47c9-9a88-a377dd353f5e` |
| `project.membership_granted` (publisher) | `e7f19f61-bbe6-49df-b8a2-6934bae17e60` |
| `project.membership_granted` (operator) | `d8f8cbb8-6ae1-4988-b410-7a537347fe03` |
| `model.registered` | `cb07b483-49d8-40ef-a2ae-b402ea7fb438` |
| `model.published` | `9e57a58a-4ea3-4abc-b9fc-5decb9460d19` |
| `dataset.registered` | `edf507dd-eb5d-4cc3-9825-cccc16484954` |
| `analysis.queued` | `2f75c782-2008-4793-b4f2-46fde0f7d442` |
| `analysis.running` | `e0079a26-b2bc-48b4-8b7b-bd2be439f3da` |
| `analysis.completed` | `0d23c845-6d34-4b43-92cb-2cb030cea45e` |

## FR-011 parity (2026-09-14 re-run)

Command as in `hdfs-parity-baseline.md`. `expected.json` was not overwritten.
Report written to gitignored `releases/hdfs/v3/parity-report.json` (not staged).

| Gate | Result |
| --- | --- |
| `passed` | `true` |
| `best_threshold` | `0.1922733336687088` exact |
| `test_f1` | `0.9320466425412143` (delta `0.0`) |
| `test_pr_auc` | `0.941418945569857` (delta `+7.738e-07`) |
| `test_roc_auc` | `0.9763096206834215` (delta `+2.221e-05`) |
| Test blocks | 86,260; line count 11,167,740; 87 shards |

All FR-011 deltas are inside absolute `0.01`.
