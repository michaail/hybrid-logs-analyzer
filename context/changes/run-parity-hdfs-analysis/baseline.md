---
change_id: run-parity-hdfs-analysis
status: approved
updated: 2026-09-11
---

# HDFS baseline release

The selected run is `hdfs_gae_20260829_104013_baseline`. Of the three supplied Colab
results, it has the highest test F1, PR-AUC, and ROC-AUC. Metrics and source artefact
checksums were approved on 2026-09-11. The v2 ZIP pair has been exported from those
same files; human confirmation of the exported ZIP and member SHA-256 values is still
required before Phase 2.

Do not substitute newer artefacts or re-run preprocessing: the model, Drain snapshot,
INI, templates, embeddings, corpus, and labels below form one frozen baseline.

## Provenance

| Field | Value |
| --- | --- |
| Code commit | Not captured in supplied Colab output — required before approval |
| Source (`run_ablation.py` or notebook path) | `src/notebooks/6_GAE_Training_Colab.ipynb`, using `data/processed/hdfs/20260818_0002_1_parser_3_graph_dataset.pt.gz` |
| Configuration file | `configs/hdfs_baseline.yaml` |
| Pipeline run id | `hdfs_gae_20260829_104013_baseline` |
| Runtime notes (Python / Torch / Drain3) | CUDA recorded; versions not captured — required before approval |

## Resolved configuration

The training parameters below are copied from the selected run's `metrics.json`. The
parser and graph-preparation provenance is recorded under Artefact checksums.

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
```

## Artefact checksums (SHA-256)

| Artefact | Source path | SHA-256 |
| --- | --- |
| Training checkpoint containing `model_state_dict` | `artifacts_colab/hdfs_gae_20260829_104013_baseline/attribute_gae.pt` | `21091c2033a2800ef084f8f684283e7dcbe86a7e6fb17ba51a25006dbe48835d` |
| Baseline metrics | `artifacts_colab/hdfs_gae_20260829_104013_baseline/metrics.json` | `736b1859741f20584eaaff1c9512704a790a6de3f046507b6c83e18d2681c906` |
| Drain snapshot (`drain_parser.bin`) | `models/hdfs/20260818_0002_drain_parser.bin` | `098b3051263d8b88409381f788a789975441ee0b4d8887495cc216d3d2439b25` |
| Drain config (`drain.ini`) | `configs/drain.ini` | `ad472f32bac75f4884fc0f471776d991d65d51125e5424c13793e9f8b0bfb8e5` |
| Raw Drain templates | `data/processed/hdfs/20260818_0002_hdfs_templates.json` | `b93d52370f0326f32db271611c0b9fcb575c3a63b2c90e4e7ed1c9d2ce6ea86f` |
| Enriched templates | `data/processed/hdfs/20260818_0002_hdfs_2_templates_enriched.json` | `9f2aa1d1644ef55b421ae153e01680d56a5af149b0b4d2cc2addcb7ab3c1d11c` |
| Embeddings (`embeddings.npz`) | `data/processed/hdfs/20260818_0002_1_parser_3_embeddings.npz` | `5f255fd6274a9075e8da14770d8ec8df28e9f592ac6539a4e2dfbc2a6dfd57e5` |
| Raw HDFS corpus | `data/raw/hdfs/HDFS_full.log` | `e8987f909b97ce975d65f773a4e1eae7aadab455a38db2aa29ed30ae8b96f166` |
| HDFS labels | `data/raw/hdfs/anomaly_label.csv` | `1c711ed6c8848fc3243fb4d092f172f31d128c8a6ec7f26ebba72ab931885ed8` |
| Exported v2 model package ZIP | `releases/hdfs/attribute-gae-v2.zip` | `758c725533258a22c5f19e82c1362b4c43a5a78c7290dd56b6d825640b6071da` |
| Exported preprocessing-bundle ZIP | `releases/hdfs/attribute-gae-preprocessing-v2.zip` | `15bd9700fb13108ed1880c7c30de2d5dbf389f392c8be61309710154800b6ccb` |
| Exported `model.pt` (tensor-only state dict) | member of `attribute-gae-v2.zip` | `82a4a69acb3365be11aabecb2511812bcc4416a54660f0a487d393b31b5cd29d` |
| Canonical bundle `embeddings.npz` | member of `attribute-gae-preprocessing-v2.zip` | `957db8176d71b5b552382d28e6ff6b4a9d1e09c0aed11c02213747929eafcbc5` |
| Bundle digest (`files.checksums` material) | declared in both manifests | `d2a8991f1d0ce101c6fa879f983f32c0e917d1809acb1daa157ed7708cde195b` |

## Export command

The v2 archives were written with:

```bash
.venv/bin/python run_ablation.py \
  --mode export-inference-release \
  --config configs/hdfs_baseline.yaml \
  --code-root . \
  --workspace-root . \
  --output-dir releases/hdfs \
  --model-identifier attribute-gae \
  --model-version v2 \
  --run-id hdfs_gae_20260829_104013_baseline \
  --checkpoint artifacts_colab/hdfs_gae_20260829_104013_baseline/attribute_gae.pt \
  --parser-state models/hdfs/20260818_0002_drain_parser.bin \
  --drain-config configs/drain.ini \
  --embeddings data/processed/hdfs/20260818_0002_1_parser_3_embeddings.npz \
  --labels data/raw/hdfs/anomaly_label.csv \
  --metrics artifacts_colab/hdfs_gae_20260829_104013_baseline/metrics.json
```

`releases/` is gitignored. Re-export only from the frozen source paths above; do not pick a newer Colab folder.

## Ordered test block IDs

The supplied Colab result records `86,260` test blocks, but it does not include their
ordered block IDs. Recover and checksum that ordered list from the selected run before
approval; do not reconstruct it from a different run or a “newest” dataset file.

```text
Not yet recovered from the selected Colab run.
```

## Core metrics

Copied exactly from `artifacts_colab/hdfs_gae_20260829_104013_baseline/metrics.json`.

| Metric | Expected value |
| --- | --- |
| Decision threshold (`best_threshold`) | `0.1922733336687088` |
| Test F1 | `0.9320466425412143` |
| Test PR-AUC | `0.9414181717698867` |
| Test ROC-AUC | `0.9762874091865125` |

## Approval

| Field | Value |
| --- | --- |
| Approved by | Project owner |
| Approved at | 2026-09-11 |
| Notes | Approved as the metric and export baseline. Source artefact SHA-256 values were re-checked on export and still match this table. Bundle `drain.ini` and `drain_parser.bin` members match those source hashes exactly. Canonical bundle `embeddings.npz` differs from the source NPZ because export drops `tfidf_vocab` and rewrites embeddings as finite float32. Exported ZIP hashes were human-confirmed on 2026-09-11. Code commit, runtime versions, and ordered test block IDs remain unrecovered and are required before declaring FR-011 parity verified. |
