from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import project.run_ablation as run_ablation
from src.modules.parser import BGLParser

REPOSITORY_ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def test_bgl_fixture_exposes_inline_anomaly_labels(tmp_path: Path) -> None:
    pytest.importorskip("drain3")
    parser = BGLParser(config_path=str(REPOSITORY_ROOT / "configs" / "drain_bgl.ini"))
    fixture = FIXTURES / "bgl_tiny.log"
    parser.fit_file(str(fixture))
    frame = parser.annotate_file(str(fixture))

    assert len(frame) == 4
    assert frame["is_anomaly"].tolist() == [False, True, False, True]


def test_enrichment_disabled_cpu_smoke_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise parse → sequence → graph → one CPU epoch without external APIs."""
    pytest.importorskip("torch_geometric")
    import torch

    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)
    shutil.copy2(FIXTURES / "hdfs_tiny.log", raw_dir / "HDFS_full.log")
    shutil.copy2(FIXTURES / "hdfs_tiny_labels.csv", raw_dir / "anomaly_label.csv")
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
