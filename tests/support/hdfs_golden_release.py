"""Deterministic tiny v2 HDFS release used as the golden processing fixture."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

GOLDEN_LOG = """\
081109 203615 148 INFO dfs.DataNode$DataXceiver: Receiving block blk_1 src: /10.0.0.1:50010 dest: /10.0.0.2:50010
081109 203616 149 INFO dfs.DataNode$DataXceiver: Receiving block blk_1 src: /10.0.0.1:50011 dest: /10.0.0.2:50010
081109 203617 150 INFO dfs.DataNode$DataXceiver: Receiving block blk_2 src: /10.0.0.1:50010 dest: /10.0.0.2:50010
081109 203618 151 INFO dfs.DataNode$PacketResponder: PacketResponder 1 for block blk_2 terminating
"""
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "hdfs_inference_release"


def write_golden_hdfs_inference_release(destination: Path | None = None) -> Path:
    """Export a seeded tiny v2 release and freeze its processing/parity oracle."""

    import numpy as np
    import torch

    from src.modules.hdfs_inference import score_frozen_hdfs_log
    from src.modules.hdfs_parity import compute_detection_metrics, sha256_file
    from src.modules.inference_release import (
        HdfsReleaseIdentity,
        HdfsReleaseSource,
        export_hdfs_inference_release,
    )
    from src.modules.model_package import MANIFEST_NAME, ModelPackageManifest
    from src.modules.models.gae import AttributeAwareGAE
    from src.modules.parser.drain_parser import DrainParser

    output = (destination or FIXTURE_DIR).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    package_dir = output / "package"
    bundle_dir = output / "bundle"
    staging = output / ".staging"
    staging.mkdir()

    log_path = output / "hdfs.log"
    log_path.write_text(GOLDEN_LOG, encoding="utf-8")
    drain_config = REPO_ROOT / "configs" / "drain.ini"
    parser_state = staging / "drain_parser.bin"
    parser = DrainParser(config_path=str(drain_config), persistence_path=str(parser_state))
    parser.fit_file(str(log_path))
    parser.save()
    annotated = parser.annotate_file(str(log_path), unmatched="fail")
    cluster_ids = sorted({int(value) for value in annotated["cluster_id"].tolist()})
    vectors = np.zeros((len(cluster_ids), 2), dtype=np.float32)
    for index, _cluster_id in enumerate(cluster_ids):
        vectors[index, 0] = float(index + 1)
        vectors[index, 1] = float(index) * 0.5
    embeddings_path = staging / "embeddings.npz"
    np.savez_compressed(embeddings_path, cluster_ids=np.asarray(cluster_ids, dtype=np.int64), embeddings=vectors)

    torch.manual_seed(0)
    np.random.seed(0)
    node_dim = 11
    edge_dim = 10
    hidden_dim = 2
    latent_dim = 2
    gine_aggregation = "sum"
    node_transformation = "mlp"
    edge_mean = [0.0] * 10
    edge_std = [0.2] * 10
    model = AttributeAwareGAE(
        node_dim=node_dim,
        edge_dim=edge_dim,
        hidden_dim=hidden_dim,
        latent_dim=latent_dim,
        gine_aggregation=gine_aggregation,
        node_transformation=node_transformation,
    )
    checkpoint_path = staging / "attribute_gae.pt"
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "node_dim": node_dim,
            "edge_dim": edge_dim,
            "hidden_dim": hidden_dim,
            "latent_dim": latent_dim,
            "gine_aggregation": gine_aggregation,
            "node_transformation": node_transformation,
            "edge_mean": edge_mean,
            "edge_std": edge_std,
            "training": {
                "test_run": False,
                "alpha": 1.0,
                "beta": 1.0,
                "gamma": 1.0,
            },
        },
        checkpoint_path,
    )
    labels_path = staging / "anomaly_label.csv"
    labels_path.write_text("BlockId,Label\nblk_1,0\nblk_2,1\n", encoding="utf-8")
    metrics_path = staging / "metrics.json"
    metrics_path.write_text(
        json.dumps({"best_threshold": 0.0, "test_f1": 0.0, "test_pr_auc": 0.0, "test_roc_auc": 0.0}),
        encoding="utf-8",
    )
    exported = export_hdfs_inference_release(
        config={
            "experiment": {"dataset": "hdfs"},
            "training": {
                "test_run": False,
                "alpha": 1.0,
                "beta": 1.0,
                "gamma": 1.0,
            },
        },
        source=HdfsReleaseSource(
            checkpoint_path=checkpoint_path,
            parser_state_path=parser_state,
            drain_config_path=drain_config,
            embeddings_path=embeddings_path,
            labels_path=labels_path,
            metrics_path=metrics_path,
        ),
        identity=HdfsReleaseIdentity(
            model_identifier="attribute-gae",
            version="golden",
            bundle_identifier="attribute-gae-preprocessing",
            bundle_version="golden",
            pipeline_run_id="hdfs-golden-fixture",
        ),
        output_dir=staging / "zips",
        code_root=REPO_ROOT,
    )
    _extract_zip(exported.model_package_path, package_dir)
    _extract_zip(exported.preprocessing_bundle_path, bundle_dir)

    placeholder = ModelPackageManifest.model_validate(
        json.loads((package_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    )
    first = score_frozen_hdfs_log(
        manifest=placeholder,
        bundle_dir=bundle_dir,
        log_path=log_path,
        artifact_path=package_dir / "model.pt",
    )
    if len(first.blocks) != 2:
        raise RuntimeError("Golden fixture must contain exactly two HDFS blocks.")
    low, high = sorted(first.blocks, key=lambda block: block.score)
    if low.score == high.score:
        raise RuntimeError("Golden fixture blocks must have distinct scores.")
    threshold = (low.score + high.score) / 2.0
    _rewrite_threshold(package_dir / MANIFEST_NAME, threshold)
    manifest = ModelPackageManifest.model_validate(
        json.loads((package_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    )
    scored = score_frozen_hdfs_log(
        manifest=manifest,
        bundle_dir=bundle_dir,
        log_path=log_path,
        artifact_path=package_dir / "model.pt",
    )
    label_map = {low.block_id: 0, high.block_id: 1}
    labels_path = output / "labels.csv"
    labels_path.write_text(
        "BlockId,Label\n"
        + "".join(f"{block.block_id},{label_map[block.block_id]}\n" for block in scored.blocks),
        encoding="utf-8",
    )
    y_true = [label_map[block.block_id] for block in scored.blocks]
    y_score = [block.score for block in scored.blocks]
    metrics = compute_detection_metrics(y_true, y_score, scored.threshold)
    snapshot = scored.as_snapshot()
    checksums = dict(snapshot["checksums"])
    checksums.update(
        {
            "corpus": sha256_file(log_path),
            "labels": sha256_file(labels_path),
        }
    )
    expected: dict[str, Any] = {
        **snapshot,
        "checksums": checksums,
        "metrics": {
            "best_threshold": scored.threshold,
            "test_f1": metrics["test_f1"],
            "test_pr_auc": metrics["test_pr_auc"],
            "test_roc_auc": metrics["test_roc_auc"],
        },
        "test_block_ids": [block.block_id for block in scored.blocks],
        "metric_tolerance": 0.01,
    }
    (output / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    shutil.rmtree(staging)
    return output


def _extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(destination)


def _rewrite_threshold(manifest_path: Path, threshold: float) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["metrics"]["best_threshold"] = threshold
    payload["metrics"]["test_f1"] = 1.0
    payload["metrics"]["test_pr_auc"] = 1.0
    payload["metrics"]["test_roc_auc"] = 1.0
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_golden_hdfs_inference_release()
    print(f"Wrote {FIXTURE_DIR}")
