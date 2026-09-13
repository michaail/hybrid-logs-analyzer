---
project: "Log Anomaly Detection System"
status: approved
created: 2026-09-13
updated: 2026-09-13
purpose: Active checksum-pinned HDFS FR-011 baseline for the v3 AttributeAwareGAE release.
---

# HDFS parity baseline

Active pin for FR-011. Generated artefacts stay in ignored workspace paths; this
file records identities, SHA-256 checksums, and the metric gate.

The immutable evidence pack, including waived Colab provenance, is
[`context/archive/2026-09-11-run-parity-hdfs-analysis/baseline.md`](../archive/2026-09-11-run-parity-hdfs-analysis/baseline.md).
Do not substitute newer Colab folders or re-run preprocessing.

`feature_contract: notebook_raw_v1` names the original notebook graph-feature
semantics. It is not a model-package format. The accepted Publisher package for
this baseline is `attribute-aware-gae-v2` bound to its immutable preprocessing
bundle.

## Provenance

| Field | Value |
| --- | --- |
| Notebook | `src/notebooks/6_GAE_Training_Colab.ipynb` |
| Configuration | `configs/hdfs_baseline.yaml` |
| Pipeline run id | `hdfs_gae_20260829_104013_baseline` |
| Code commit | Unrecovered — waived (Colab output never recorded it) |
| Runtime (Python / Torch / Drain3) | CUDA recorded; versions unrecovered — waived |

## Resolved configuration

Copied from the selected run's `metrics.json`:

```yaml
experiment:
  name: baseline
  dataset: hdfs
  run_id: hdfs_gae_20260829_104013_baseline
  seed: 42
training:
  train_mode: clean
  test_run: false
  test_samples: 5000
  hidden_dim: 128
  latent_dim: 64
  batch_size: 256
  epochs: 25
  learning_rate: 0.01
  alpha: 1.0
  beta: 1.0
  gamma: 1.0
  pre_normalize_edges: true
  minimum_edge_std: 0.1
graph:
  node_dim: 530
  edge_dim: 10
  embedding_dim: 521
  gine_aggregation: sum
  node_transformation: mlp
  feature_contract: notebook_raw_v1
```

## Artefact checksums (SHA-256)

Workspace paths below are gitignored. Re-export only from the frozen source
paths in the archive baseline.

| Artefact | Source path | SHA-256 |
| --- | --- |
| Training checkpoint containing `model_state_dict` | `artifacts_colab/hdfs_gae_20260829_104013_baseline/attribute_gae.pt` | `21091c2033a2800ef084f8f684283e7dcbe86a7e6fb17ba51a25006dbe48835d` |
| Baseline metrics | `artifacts_colab/hdfs_gae_20260829_104013_baseline/metrics.json` | `736b1859741f20584eaaff1c9512704a790a6de3f046507b6c83e18d2681c906` |
| Drain snapshot (`drain_parser.bin`) | `models/hdfs/20260818_0002_drain_parser.bin` | `098b3051263d8b88409381f788a789975441ee0b4d8887495cc216d3d2439b25` |
| Drain config (`drain.ini`) | `configs/drain.ini` | `ad472f32bac75f4884fc0f471776d991d65d51125e5424c13793e9f8b0bfb8e5` |
| Raw Drain templates | `data/processed/hdfs/20260818_0002_hdfs_templates.json` | `b93d52370f0326f32db271611c0b9fcb575c3a63b2c90e4e7ed1c9d2ce6ea86f` |
| Enriched templates | `data/processed/hdfs/20260818_0002_hdfs_2_templates_enriched.json` | `9f2aa1d1644ef55b421ae153e01680d56a5af149b0b4d2cc2addcb7ab3c1d11c` |
| Embeddings (`embeddings.npz`) | `data/processed/hdfs/20260818_0002_1_parser_3_embeddings.npz` | `5f255fd6274a9075e8da14770d8ec8df28e9f592ac6539a4e2dfbc2a6dfd57e5` |
| Trusted Colab graph bundle | `data/processed/hdfs/20260818_0002_1_parser_3_graph_dataset.pt` | `95bdc790eb99deb495b4490b3306c0f4c18fdaf9c629749de79d46cd37beacc8` |
| Raw HDFS corpus | `data/raw/hdfs/HDFS_full.log` | `e8987f909b97ce975d65f773a4e1eae7aadab455a38db2aa29ed30ae8b96f166` |
| HDFS labels | `data/raw/hdfs/anomaly_label.csv` | `1c711ed6c8848fc3243fb4d092f172f31d128c8a6ec7f26ebba72ab931885ed8` |
| Exported v3 model package ZIP | `releases/hdfs/attribute-gae-v3.zip` | `7df39cb47490eca6c4af36b78ba9426904038f5d54654cb23661f80bef09181b` |
| Exported v3 preprocessing-bundle ZIP | `releases/hdfs/attribute-gae-preprocessing-v3.zip` | `e2af6e3a0321fc4c8fdd7a20648dbdd7d93838e170731b112c47163325c413d7` |
| Exported `model.pt` (tensor-only state dict) | member of `attribute-gae-v3.zip` | `82a4a69acb3365be11aabecb2511812bcc4416a54660f0a487d393b31b5cd29d` |
| Canonical bundle `embeddings.npz` | member of `attribute-gae-preprocessing-v3.zip` | `957db8176d71b5b552382d28e6ff6b4a9d1e09c0aed11c02213747929eafcbc5` |
| Bundle digest (`files.checksums` material) | declared in both manifests | `d2a8991f1d0ce101c6fa879f983f32c0e917d1809acb1daa157ed7708cde195b` |
| Ordered held-out test block IDs | `releases/hdfs/test_block_ids.txt` (`86,260` unique IDs) | `d5b278a8b4cd4d85421dc3973efcd3b4edba6e43f98a477044096f85e5cfea26` |
| Immutable expected parity record | `releases/hdfs/v3/expected.json` | pin by path; do not overwrite |

## FR-011 metric gate

Controlled labelled release gate only. A passing Operator upload is not FR-011
proof. Default CI does not run this command.

| Metric | Expected value | Rule |
| --- | --- | --- |
| Decision threshold (`best_threshold`) | `0.1922733336687088` | exact equality |
| Test F1 (`test_f1`) | `0.9320466425412143` | absolute tolerance `0.01` |
| Test PR-AUC (`test_pr_auc`) | `0.9414181717698867` | absolute tolerance `0.01` |
| Test ROC-AUC (`test_roc_auc`) | `0.9762874091865125` | absolute tolerance `0.01` |

Not FR-011 acceptance metrics, even when present in `metrics.json`:
`test_precision`, `test_recall`, `val_*`, and `test_confusion_matrix`.

Approved comparison evidence (workspace-only): `releases/hdfs/v3/parity-report.json`.
On 2026-09-12 the gate passed with exact F1 and threshold; PR-AUC / ROC-AUC
deltas were `+0.0000007738` and `+0.0000222115`.

## Verification command

```bash
python scripts/verify_hdfs_parity.py \
  --model-package releases/hdfs/attribute-gae-v3.zip \
  --preprocessing-bundle releases/hdfs/attribute-gae-preprocessing-v3.zip \
  --corpus data/raw/hdfs/HDFS_full.log \
  --labels data/raw/hdfs/anomaly_label.csv \
  --expected releases/hdfs/v3/expected.json \
  --report releases/hdfs/v3/parity-report.json \
  --test-block-ids releases/hdfs/test_block_ids.txt
```

`--test-block-ids` is required for this baseline's held-out split. Run in the
Linux inference environment or a local ML venv, not in Cursor's restricted
native-library sandbox.
