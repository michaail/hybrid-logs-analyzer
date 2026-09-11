from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from src.modules.inference_release import (
    HdfsReleaseIdentity,
    HdfsReleaseSource,
    InferenceReleaseError,
    export_hdfs_inference_release,
    inspect_inference_release,
)
from src.modules.parser import BGLParser

REPOSITORY_ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
RELEASE_IDENTITY = HdfsReleaseIdentity(
    model_identifier="attribute-gae",
    version="v2",
    bundle_identifier="attribute-gae-preprocessing",
    bundle_version="v2",
    pipeline_run_id="synthetic-hdfs-release",
)


def test_bgl_fixture_exposes_inline_anomaly_labels(tmp_path: Path) -> None:
    pytest.importorskip("drain3")
    parser = BGLParser(config_path=str(REPOSITORY_ROOT / "configs" / "drain_bgl.ini"))
    fixture = FIXTURES / "bgl_tiny.log"
    parser.fit_file(str(fixture))
    frame = parser.annotate_file(str(fixture))

    assert len(frame) == 4
    assert frame["is_anomaly"].tolist() == [False, True, False, True]


def test_exporter_rejects_bgl_configuration(tmp_path: Path) -> None:
    config = _load_hdfs_config(["experiment.dataset=bgl"])
    with pytest.raises(InferenceReleaseError, match="BGL"):
        export_hdfs_inference_release(
            config=config,
            source=_release_source(tmp_path),
            identity=RELEASE_IDENTITY,
            output_dir=tmp_path / "releases",
            code_root=REPOSITORY_ROOT,
        )


def test_exporter_rejects_smoke_test_run_configuration(tmp_path: Path) -> None:
    config = _load_hdfs_config(["training.test_run=true"])
    with pytest.raises(InferenceReleaseError, match="Smoke/test-run"):
        export_hdfs_inference_release(
            config=config,
            source=_release_source(tmp_path),
            identity=RELEASE_IDENTITY,
            output_dir=tmp_path / "releases",
            code_root=REPOSITORY_ROOT,
        )


def test_exporter_rejects_missing_hdfs_labels(tmp_path: Path) -> None:
    source = _release_source(tmp_path, omit="labels_path")
    with pytest.raises(InferenceReleaseError, match="labels"):
        export_hdfs_inference_release(
            config=_load_hdfs_config(),
            source=source,
            identity=RELEASE_IDENTITY,
            output_dir=tmp_path / "releases",
            code_root=REPOSITORY_ROOT,
        )


def test_exporter_rejects_missing_parser_snapshot(tmp_path: Path) -> None:
    source = _release_source(tmp_path, omit="parser_state_path")
    with pytest.raises(InferenceReleaseError, match="parser"):
        export_hdfs_inference_release(
            config=_load_hdfs_config(),
            source=source,
            identity=RELEASE_IDENTITY,
            output_dir=tmp_path / "releases",
            code_root=REPOSITORY_ROOT,
        )


def test_exporter_rejects_missing_embeddings(tmp_path: Path) -> None:
    source = _release_source(tmp_path, omit="embeddings_path")
    with pytest.raises(InferenceReleaseError, match="Embeddings"):
        export_hdfs_inference_release(
            config=_load_hdfs_config(),
            source=source,
            identity=RELEASE_IDENTITY,
            output_dir=tmp_path / "releases",
            code_root=REPOSITORY_ROOT,
        )


@pytest.mark.ml
def test_exporter_rejects_smoke_checkpoint_even_when_config_is_full(
    tmp_path: Path,
) -> None:
    pytest.importorskip("torch")
    import torch

    source = _release_source(tmp_path)
    torch.save(
        {
            "model_state_dict": {"weight": torch.ones(1)},
            "training": {"test_run": True, "alpha": 1.0, "beta": 1.0, "gamma": 1.0},
        },
        source.checkpoint_path,
    )
    with pytest.raises(InferenceReleaseError, match="Smoke/test-run"):
        export_hdfs_inference_release(
            config=_load_hdfs_config(["training.test_run=false"]),
            source=source,
            identity=RELEASE_IDENTITY,
            output_dir=tmp_path / "releases",
            code_root=REPOSITORY_ROOT,
        )


@pytest.mark.ml
def test_exporter_accepts_notebook_checkpoint_and_nested_metrics(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    import torch

    source = _release_source(tmp_path)
    source.metrics_path.write_text(
        json.dumps(
            {
                "best_threshold": 0.1922733336687088,
                "test": {
                    "f1": 0.9320466425412143,
                    "pr_auc": 0.9414181717698867,
                    "roc_auc": 0.9762874091865125,
                },
            }
        ),
        encoding="utf-8",
    )
    torch.save(
        {
            "model_state_dict": {"weight": torch.ones(1)},
            "node_dim": 2,
            "edge_dim": 1,
            "edge_mean": [0.0],
            "edge_std": [0.2],
            "experiment": {
                "hidden_dim": 2,
                "latent_dim": 2,
                "gine_aggregation": "sum",
                "node_transformation": "mlp",
                "alpha": 1.0,
                "beta": 1.0,
                "gamma": 1.0,
                "test_run": False,
            },
        },
        source.checkpoint_path,
    )
    exported = export_hdfs_inference_release(
        config=_load_hdfs_config(),
        source=source,
        identity=RELEASE_IDENTITY,
        output_dir=tmp_path / "releases",
        code_root=REPOSITORY_ROOT,
    )
    inspected = inspect_inference_release(
        exported.model_package_path, exported.preprocessing_bundle_path
    )
    assert inspected.model_manifest.metrics.best_threshold == 0.1922733336687088
    assert inspected.model_manifest.metrics.model_dump()["test_f1"] == 0.9320466425412143
    assert inspected.model_manifest.architecture.hidden_dim == 2
    assert inspected.model_manifest.architecture.node_dim == 2
    assert inspected.model_manifest.scoring.alpha == 1.0


@pytest.mark.ml
def test_enrichment_disabled_cpu_smoke_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise parse → sequence → graph → one CPU epoch without external APIs."""
    pytest.importorskip("torch")
    pytest.importorskip("torch_geometric")

    import run_ablation
    import torch

    _copy_tiny_hdfs_raw(tmp_path)
    monkeypatch.setattr(run_ablation, "get_device", lambda: torch.device("cpu"))

    config = run_ablation.apply_overrides(
        run_ablation.load_config(REPOSITORY_ROOT / "configs" / "ablation_base.yaml"),
        [
            "experiment.dataset=hdfs",
            "experiment.run_id=synthetic-smoke",
            "ablation.llm_enrichment_enabled=false",
            "ablation.embeddings.sbert_enabled=false",
            "ablation.embeddings.tfidf_enabled=true",
            "training.test_run=true",
            "training.test_samples=8",
            "training.epochs=1",
            "training.batch_size=4",
        ],
    )
    record = run_ablation.run_experiment(
        config,
        mode="smoke",
        workspace_root=tmp_path,
        code_root=REPOSITORY_ROOT,
    )

    assert record["metrics"]["n_train"] > 0
    assert (tmp_path / record["artifacts"]["graph_dataset"]).exists()
    assert (tmp_path / record["artifacts"]["checkpoint"]).exists()
    assert list((tmp_path / "artifacts" / "cache").rglob("_SUCCESS.json"))


@pytest.mark.ml
def test_export_validates_synthetic_hdfs_inference_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("torch_geometric")

    import run_ablation
    import torch

    _copy_tiny_hdfs_raw(tmp_path)
    monkeypatch.setattr(run_ablation, "get_device", lambda: torch.device("cpu"))
    config = _load_hdfs_config(
        [
            "experiment.run_id=synthetic-hdfs-release",
            "ablation.llm_enrichment_enabled=false",
            "ablation.embeddings.sbert_enabled=false",
            "ablation.embeddings.tfidf_enabled=true",
            "training.test_run=false",
            "training.epochs=1",
            "training.batch_size=4",
            "training.hidden_dim=8",
            "training.latent_dim=4",
        ]
    )
    run_ablation.run_experiment(
        config,
        mode="full",
        workspace_root=tmp_path,
        code_root=REPOSITORY_ROOT,
    )
    source = run_ablation.resolve_hdfs_release_source(
        config, workspace_root=tmp_path, code_root=REPOSITORY_ROOT
    )
    first = export_hdfs_inference_release(
        config=config,
        source=source,
        identity=RELEASE_IDENTITY,
        output_dir=tmp_path / "releases" / "first",
        code_root=REPOSITORY_ROOT,
    )
    inspected = inspect_inference_release(
        first.model_package_path, first.preprocessing_bundle_path
    )

    assert inspected.model_manifest.format == "attribute-aware-gae-v2"
    assert {item.name for item in inspected.model_files} == {"model.pt", "evidence.json"}
    assert {item.name for item in inspected.bundle_files} == {
        "drain.ini",
        "drain_parser.bin",
        "embeddings.npz",
    }
    for item in (*inspected.model_files, *inspected.bundle_files):
        assert item.sha256 == hashlib.sha256(
            _zip_member(first.model_package_path, item.name)
            if item.name in {"model.pt", "evidence.json"}
            else _zip_member(first.preprocessing_bundle_path, item.name)
        ).hexdigest()
        assert len(item.sha256) == 64

    with zipfile.ZipFile(first.model_package_path) as archive:
        names = set(archive.namelist())
        artifact = archive.read("model.pt")
        evidence = json.loads(archive.read("evidence.json"))
    assert names == {"manifest.json", "model.pt", "evidence.json"}
    assert "graph_dataset.pt" not in names
    state = torch.load(io.BytesIO(artifact), map_location="cpu", weights_only=True)
    assert isinstance(state, dict)
    assert "model_state_dict" not in state
    assert "training" not in state
    assert all(hasattr(value, "shape") and hasattr(value, "dtype") for value in state.values())
    assert evidence["kind"] == "hdfs-inference-release"

    with zipfile.ZipFile(first.preprocessing_bundle_path) as archive:
        bundle_names = set(archive.namelist())
        drain_config = archive.read("drain.ini")
        embeddings_bytes = archive.read("embeddings.npz")
    assert bundle_names == {
        "manifest.json",
        "drain.ini",
        "drain_parser.bin",
        "embeddings.npz",
    }
    assert drain_config == (REPOSITORY_ROOT / "configs" / "drain.ini").read_bytes()
    import numpy as np

    with np.load(io.BytesIO(embeddings_bytes), allow_pickle=False) as payload:
        cluster_ids = payload["cluster_ids"]
        embeddings = payload["embeddings"]
        assert np.issubdtype(cluster_ids.dtype, np.integer)
        assert cluster_ids.size == np.unique(cluster_ids).size
        assert embeddings.dtype == np.float32
        assert embeddings.ndim == 2
        assert embeddings.shape[0] == cluster_ids.size
        assert np.isfinite(embeddings).all()

    second = export_hdfs_inference_release(
        config=config,
        source=source,
        identity=RELEASE_IDENTITY,
        output_dir=tmp_path / "releases" / "second",
        code_root=REPOSITORY_ROOT,
    )
    second_inspected = inspect_inference_release(
        second.model_package_path, second.preprocessing_bundle_path
    )
    assert [item.sha256 for item in inspected.model_files] == [
        item.sha256 for item in second_inspected.model_files
    ]
    assert [item.sha256 for item in inspected.bundle_files] == [
        item.sha256 for item in second_inspected.bundle_files
    ]
    assert inspected.bundle_manifest.digest == second_inspected.bundle_manifest.digest
    assert inspected.model_manifest.preprocessing_bundle is not None
    assert (
        inspected.model_manifest.preprocessing_bundle.digest
        == inspected.bundle_manifest.digest
    )


def _load_hdfs_config(overrides: list[str] | None = None) -> dict:
    import run_ablation

    return run_ablation.apply_overrides(
        run_ablation.load_config(REPOSITORY_ROOT / "configs" / "hdfs_baseline.yaml"),
        overrides or [],
    )


def _copy_tiny_hdfs_raw(workspace: Path) -> None:
    raw_dir = workspace / "data" / "raw"
    raw_dir.mkdir(parents=True)
    shutil.copy2(FIXTURES / "hdfs_tiny.log", raw_dir / "HDFS_full.log")
    shutil.copy2(FIXTURES / "hdfs_tiny_labels.csv", raw_dir / "anomaly_label.csv")


def _release_source(tmp_path: Path, *, omit: str | None = None) -> HdfsReleaseSource:
    import numpy as np

    labels = tmp_path / "anomaly_label.csv"
    parser_state = tmp_path / "drain_parser.bin"
    embeddings = tmp_path / "embeddings.npz"
    drain_config = tmp_path / "drain.ini"
    checkpoint = tmp_path / "attribute_gae.pt"
    metrics = tmp_path / "metrics.json"
    files = {
        "labels_path": labels,
        "parser_state_path": parser_state,
        "embeddings_path": embeddings,
        "drain_config_path": drain_config,
        "checkpoint_path": checkpoint,
        "metrics_path": metrics,
    }
    shutil.copy2(FIXTURES / "hdfs_tiny_labels.csv", labels)
    parser_state.write_bytes(b"drain-snapshot")
    drain_config.write_bytes((REPOSITORY_ROOT / "configs" / "drain.ini").read_bytes())
    np.savez_compressed(
        embeddings,
        cluster_ids=np.asarray([1, 2], dtype=np.int64),
        embeddings=np.ones((2, 4), dtype=np.float32),
    )
    checkpoint.write_bytes(b"checkpoint")
    metrics.write_text(json.dumps({"best_threshold": 0.5, "test_f1": 0.9}), encoding="utf-8")
    if omit is not None:
        files[omit].unlink()
    return HdfsReleaseSource(
        checkpoint_path=checkpoint,
        parser_state_path=parser_state,
        drain_config_path=drain_config,
        embeddings_path=embeddings,
        labels_path=labels,
        metrics_path=metrics,
    )


def _zip_member(archive_path: Path, name: str) -> bytes:
    with zipfile.ZipFile(archive_path) as archive:
        return archive.read(name)
