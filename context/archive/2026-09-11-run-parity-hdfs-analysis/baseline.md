---
change_id: run-parity-hdfs-analysis
status: approved
updated: 2026-09-11
---

# HDFS baseline release

The selected run is `hdfs_gae_20260829_104013_baseline`. Of the three supplied Colab
results, it has the highest test F1, PR-AUC, and ROC-AUC. Metrics and source artefact
checksums were approved on 2026-09-11. The immutable v3 release was exported from those
same files with the graph-feature contract used by the original Colab run; its comparison
report is the Phase 5 release evidence.

Do not substitute newer artefacts or re-run preprocessing: the model, Drain snapshot,
INI, templates, embeddings, corpus, and labels below form one frozen baseline.

## Provenance

| Field | Value |
| --- | --- |
| Code commit | Unrecovered — accepted exception (Colab output never recorded them) |
| Source (`run_ablation.py` or notebook path) | `src/notebooks/6_GAE_Training_Colab.ipynb`, using `data/processed/hdfs/20260818_0002_1_parser_3_graph_dataset.pt.gz` |
| Configuration file | `configs/hdfs_baseline.yaml` |
| Pipeline run id | `hdfs_gae_20260829_104013_baseline` |
| Runtime notes (Python / Torch / Drain3) | CUDA recorded; versions unrecovered — accepted exception |

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
  feature_contract: notebook_raw_v1
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
| Trusted Colab graph bundle | `data/processed/hdfs/20260818_0002_1_parser_3_graph_dataset.pt` | `95bdc790eb99deb495b4490b3306c0f4c18fdaf9c629749de79d46cd37beacc8` |
| Raw HDFS corpus | `data/raw/hdfs/HDFS_full.log` | `e8987f909b97ce975d65f773a4e1eae7aadab455a38db2aa29ed30ae8b96f166` |
| HDFS labels | `data/raw/hdfs/anomaly_label.csv` | `1c711ed6c8848fc3243fb4d092f172f31d128c8a6ec7f26ebba72ab931885ed8` |
| Exported v3 model package ZIP | `releases/hdfs/attribute-gae-v3.zip` | `7df39cb47490eca6c4af36b78ba9426904038f5d54654cb23661f80bef09181b` |
| Exported v3 preprocessing-bundle ZIP | `releases/hdfs/attribute-gae-preprocessing-v3.zip` | `e2af6e3a0321fc4c8fdd7a20648dbdd7d93838e170731b112c47163325c413d7` |
| Exported `model.pt` (tensor-only state dict) | member of `attribute-gae-v3.zip` | `82a4a69acb3365be11aabecb2511812bcc4416a54660f0a487d393b31b5cd29d` |
| Canonical bundle `embeddings.npz` | member of `attribute-gae-preprocessing-v3.zip` | `957db8176d71b5b552382d28e6ff6b4a9d1e09c0aed11c02213747929eafcbc5` |
| Bundle digest (`files.checksums` material) | declared in both manifests | `d2a8991f1d0ce101c6fa879f983f32c0e917d1809acb1daa157ed7708cde195b` |

## Export command

The v3 archives were written with:

```bash
.venv/bin/python run_ablation.py \
  --mode export-inference-release \
  --config configs/hdfs_baseline.yaml \
  --code-root . \
  --workspace-root . \
  --output-dir releases/hdfs \
  --model-identifier attribute-gae \
  --model-version v3 \
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

The ordered held-out IDs were recovered on 2026-09-12 from the user-confirmed trusted
Colab graph bundle above. The file contains `86,260` unique IDs and each has a label in
`anomaly_label.csv`. It must not be regenerated from a different or newer dataset file.

```text
releases/hdfs/test_block_ids.txt
SHA-256: d5b278a8b4cd4d85421dc3973efcd3b4edba6e43f98a477044096f85e5cfea26
```

## Core metrics

Copied exactly from `artifacts_colab/hdfs_gae_20260829_104013_baseline/metrics.json`.

| Metric | Expected value |
| --- | --- |
| Decision threshold (`best_threshold`) | `0.1922733336687088` |
| Test F1 | `0.9320466425412143` |
| Test PR-AUC | `0.9414181717698867` |
| Test ROC-AUC | `0.9762874091865125` |

## Controlled v3 parity verification

The controlled release gate completed successfully on 2026-09-12. Its immutable expected
record is `releases/hdfs/v3/expected.json`; the generated comparison evidence is
`releases/hdfs/v3/parity-report.json`.

- All corpus, label, model-package, bundle, parser, configuration, embedding, and state-dict
  SHA-256 checksums matched.
- The held-out split count (`86,260`) and SHA-256
  (`d5b278a8b4cd4d85421dc3973efcd3b4edba6e43f98a477044096f85e5cfea26`) matched.
- The frozen parser matched all `11,167,740` non-empty corpus lines.
- The release scored all `86,260` recovered held-out blocks in `87` bounded temporary shards.
- The exact threshold was `0.1922733336687088`.
- Test F1 was exactly `0.9320466425412143`; PR-AUC and ROC-AUC deltas were
  `+0.0000007738` and `+0.0000222115`, respectively—both below the `0.01` tolerance.

## Approval

| Field | Value |
| --- | --- |
| Approved by | Project owner |
| Approved at | 2026-09-11 |
| Phase 5 parity report approved by | Project owner |
| Phase 5 parity report approved at | 2026-09-12 |
| Notes | Approved as the metric and export baseline. Source artefact SHA-256 values were re-checked on export and still match this table. Bundle `drain.ini` and `drain_parser.bin` members match those source hashes exactly. Canonical bundle `embeddings.npz` differs from the source NPZ because export drops `tfidf_vocab` and rewrites embeddings as finite float32. The original notebook's raw graph features are declared as `notebook_raw_v1` in the v3 model manifest. Code commit and runtime versions were never captured in the Colab output and are waived as unrecoverable; FR-011 is treated as the metric gate only (exact threshold, F1/PR-AUC/ROC-AUC within 0.01). |
