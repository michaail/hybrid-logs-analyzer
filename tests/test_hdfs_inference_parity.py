"""Golden HDFS processing fixture and controlled parity-command tests.

The labelled 11,167,740-line corpus build and full-release parity command are
documented manual checks. They are not pytest cases: the source data is
workspace-local, and ML/native execution is not a default test dependency.
Golden ``release_gate`` tests stay opt-in via ``pytest -m release_gate``.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from src.modules.hdfs_parity import (
    ParityExpected,
    ParityMetrics,
    evaluate_metric_gate,
    load_parity_expected,
    sha256_file,
    verify_artefact_checksums,
    verify_hdfs_release,
    write_zip,
)
from src.modules.model_package import MANIFEST_NAME, ModelPackageManifest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "hdfs_inference_release"
EXPECTED_PATH = FIXTURE / "expected.json"


def _expected() -> dict[str, Any]:
    payload = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _zip_fixture(tmp_path: Path) -> tuple[Path, Path]:
    model_zip = tmp_path / "attribute-gae-golden.zip"
    bundle_zip = tmp_path / "attribute-gae-preprocessing-golden.zip"
    write_zip(FIXTURE / "package", model_zip)
    write_zip(FIXTURE / "bundle", bundle_zip)
    return model_zip, bundle_zip


def test_inference_rejects_excess_source_lines_before_loading_ml_dependencies(
    tmp_path: Path,
) -> None:
    from src.modules.hdfs_inference import HdfsInferenceError, MAX_SOURCE_LINES, score_frozen_hdfs_log

    log_path = tmp_path / "too-many-lines.log"
    log_path.write_text("line\n" * (MAX_SOURCE_LINES + 1), encoding="utf-8")
    manifest = ModelPackageManifest.model_validate(
        json.loads((FIXTURE / "package" / MANIFEST_NAME).read_text(encoding="utf-8"))
    )

    with pytest.raises(HdfsInferenceError, match="source line limit exceeded"):
        score_frozen_hdfs_log(
            manifest=manifest,
            bundle_dir=FIXTURE / "bundle",
            log_path=log_path,
            artifact_path=FIXTURE / "package" / "model.pt",
        )


def _mutate_graph_feature(expected: dict[str, Any]) -> dict[str, Any]:
    blocks = expected["blocks"]
    assert isinstance(blocks, list)
    blocks[0]["node_features"][0][0] += 1.0
    return expected


def _mutate_score(expected: dict[str, Any]) -> dict[str, Any]:
    blocks = expected["blocks"]
    assert isinstance(blocks, list)
    blocks[0]["score"] = float(blocks[0]["score"]) + 10.0
    return expected


def _mutate_ordered_blocks(expected: dict[str, Any]) -> dict[str, Any]:
    block_ids = list(expected["ordered_block_ids"])
    block_ids.reverse()
    expected["ordered_block_ids"] = block_ids
    return expected


def _mutate_parser_checksum(expected: dict[str, Any]) -> dict[str, Any]:
    checksums = expected["checksums"]
    assert isinstance(checksums, dict)
    checksums["drain_parser.bin"] = "0" * 64
    return expected


def _mutate_threshold(expected: dict[str, Any]) -> dict[str, Any]:
    expected["threshold"] = float(expected["threshold"]) + 1.0
    return expected


def test_parity_checksums_fail_when_corpus_or_artefact_is_missing(tmp_path: Path) -> None:
    expected = load_parity_expected(EXPECTED_PATH)
    files = {
        "corpus": tmp_path / "missing.log",
        "labels": FIXTURE / "labels.csv",
        "model.pt": FIXTURE / "package" / "model.pt",
    }
    results = verify_artefact_checksums(files, {"corpus": expected.checksums["corpus"]})
    assert results["corpus"]["matched"] is False
    assert results["corpus"]["error"] == "missing"


def test_parity_checksums_fail_when_digest_changes() -> None:
    expected = load_parity_expected(EXPECTED_PATH)
    results = verify_artefact_checksums(
        {"corpus": FIXTURE / "hdfs.log"},
        {"corpus": "0" * 64},
    )
    assert results["corpus"]["matched"] is False
    assert results["corpus"]["actual"] == expected.checksums["corpus"]


def test_hdfs_block_identity_uses_the_first_block_in_a_log_line() -> None:
    from src.modules.parser.drain_parser import DrainParser

    assert (
        DrainParser.extract_hdfs_block_id("INFO copy blk_2 linked to blk_1")
        == "blk_2"
    )


def test_metric_gate_fails_when_core_metric_delta_exceeds_tolerance() -> None:
    expected = ParityMetrics(
        best_threshold=0.5,
        test_f1=0.93,
        test_pr_auc=0.94,
        test_roc_auc=0.97,
    )
    gate = evaluate_metric_gate(
        expected,
        {"test_f1": 0.91, "test_pr_auc": 0.94, "test_roc_auc": 0.97},
        0.5,
    )
    assert gate["threshold"]["equal"] is True
    assert gate["metrics"]["test_f1"]["within_tolerance"] is False
    assert abs(gate["metrics"]["test_f1"]["delta"]) > 0.01
    assert gate["metrics"]["test_pr_auc"]["within_tolerance"] is True


def test_metric_gate_requires_exact_threshold_equality() -> None:
    expected = ParityMetrics(
        best_threshold=0.1922733336687088,
        test_f1=0.93,
        test_pr_auc=0.94,
        test_roc_auc=0.97,
    )
    gate = evaluate_metric_gate(
        expected,
        {"test_f1": 0.93, "test_pr_auc": 0.94, "test_roc_auc": 0.97},
        0.1922733336687089,
    )
    assert gate["threshold"]["equal"] is False


def test_parity_command_rejects_changed_corpus_checksum(tmp_path: Path) -> None:
    model_zip, bundle_zip = _zip_fixture(tmp_path)
    expected_payload = _expected()
    checksums = expected_payload["checksums"]
    assert isinstance(checksums, dict)
    checksums["corpus"] = "0" * 64
    report = verify_hdfs_release(
        model_package=model_zip,
        preprocessing_bundle=bundle_zip,
        corpus=FIXTURE / "hdfs.log",
        labels=FIXTURE / "labels.csv",
        expected=ParityExpected.model_validate(expected_payload),
        report_path=tmp_path / "parity-report.json",
    )
    assert report["passed"] is False
    assert "checksums.corpus" in report["failures"]
    assert (tmp_path / "parity-report.json").is_file()


def test_parity_command_rejects_changed_test_split_checksum(tmp_path: Path) -> None:
    model_zip, bundle_zip = _zip_fixture(tmp_path)
    test_ids_path = tmp_path / "test-block-ids.txt"
    test_ids_path.write_text("blk_1\nblk_2\n", encoding="utf-8")
    expected_payload = _expected()
    expected_payload.pop("test_block_ids")
    expected_payload["test_block_count"] = 2
    expected_payload["test_block_ids_sha256"] = "0" * 64

    report = verify_hdfs_release(
        model_package=model_zip,
        preprocessing_bundle=bundle_zip,
        corpus=FIXTURE / "hdfs.log",
        labels=FIXTURE / "labels.csv",
        expected=ParityExpected.model_validate(expected_payload),
        report_path=tmp_path / "parity-report.json",
        test_block_ids=["blk_1", "blk_2"],
        test_block_ids_sha256=sha256_file(test_ids_path),
    )

    assert report["passed"] is False
    assert "test_block_ids.checksum" in report["failures"]
    assert report["test_block_ids"]["checksum"]["matched"] is False


def test_fixture_checksums_are_self_consistent() -> None:
    expected = _expected()
    checksums = expected["checksums"]
    assert isinstance(checksums, dict)
    assert checksums["corpus"] == sha256_file(FIXTURE / "hdfs.log")
    assert checksums["labels"] == sha256_file(FIXTURE / "labels.csv")
    assert checksums["model.pt"] == sha256_file(FIXTURE / "package" / "model.pt")
    assert checksums["drain_parser.bin"] == sha256_file(FIXTURE / "bundle" / "drain_parser.bin")


def test_verify_parity_script_exits_nonzero_on_checksum_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "verify_hdfs_parity", REPO_ROOT / "scripts" / "verify_hdfs_parity.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    model_zip, bundle_zip = _zip_fixture(tmp_path)
    expected_payload = _expected()
    checksums = expected_payload["checksums"]
    assert isinstance(checksums, dict)
    checksums["corpus"] = "0" * 64
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps(expected_payload), encoding="utf-8")
    monkeypatch.chdir(REPO_ROOT)
    exit_code = module.main(
        [
            "--model-package",
            str(model_zip),
            "--preprocessing-bundle",
            str(bundle_zip),
            "--corpus",
            str(FIXTURE / "hdfs.log"),
            "--labels",
            str(FIXTURE / "labels.csv"),
            "--expected",
            str(expected_path),
            "--report",
            str(tmp_path / "parity-report.json"),
        ]
    )
    assert exit_code == 1


def test_verify_parity_script_imports_project_without_pythonpath(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_hdfs_parity.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Verify a labelled HDFS baseline release" in result.stdout


def test_parity_report_preserves_extracted_checksums_after_scoring_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.modules.hdfs_inference as hdfs_inference

    monkeypatch.setattr(hdfs_inference, "MAX_SOURCE_LINES", 4)
    model_zip, bundle_zip = _zip_fixture(tmp_path)
    corpus = tmp_path / "too-many-lines.log"
    first_line = (FIXTURE / "hdfs.log").read_text(encoding="utf-8").splitlines()[0]
    corpus.write_text((first_line + "\n") * 5, encoding="utf-8")
    expected_payload = _expected()
    expected_payload.pop("test_block_ids")
    checksums = expected_payload["checksums"]
    assert isinstance(checksums, dict)
    checksums["corpus"] = sha256_file(corpus)

    report = verify_hdfs_release(
        model_package=model_zip,
        preprocessing_bundle=bundle_zip,
        corpus=corpus,
        labels=FIXTURE / "labels.csv",
        expected=ParityExpected.model_validate(expected_payload),
        report_path=tmp_path / "parity-report.json",
    )

    assert report["passed"] is False
    assert report["inference"] == {"error": "source line limit exceeded"}
    for name in ("model.pt", "drain.ini", "drain_parser.bin", "embeddings.npz"):
        assert report["checksums"][name]["matched"] is True
        assert report["checksums"][name]["actual"] is not None


@pytest.mark.ml
def test_golden_fixture_matches_frozen_inference() -> None:
    from src.modules.hdfs_inference import compare_processing_parity, score_frozen_hdfs_log

    expected = _expected()
    manifest = ModelPackageManifest.model_validate(
        json.loads((FIXTURE / "package" / MANIFEST_NAME).read_text(encoding="utf-8"))
    )
    actual = score_frozen_hdfs_log(
        manifest=manifest,
        bundle_dir=FIXTURE / "bundle",
        log_path=FIXTURE / "hdfs.log",
        artifact_path=FIXTURE / "package" / "model.pt",
    )
    snapshot = actual.as_snapshot()
    assert actual.source_line_count == actual.annotated_line_count
    assert actual.source_line_count == 4
    mismatches = compare_processing_parity(snapshot, expected)
    assert mismatches == []
    for block in snapshot["blocks"]:
        assert isinstance(block, dict)
        assert block["decision"] == (block["score"] > snapshot["threshold"])


@pytest.mark.ml
def test_notebook_raw_feature_contract_preserves_pre_stabilization_features() -> None:
    from datetime import datetime, timedelta

    import numpy as np
    import pandas as pd

    from src.modules.dataset import build_pyg_dataset

    sequence = pd.DataFrame(
        {
            "block_id": ["blk_1", "blk_1"],
            "cluster_id": [1, 1],
            "parameters": [["-5"], ["not-a-number"]],
            "timestamp": [datetime(2009, 11, 8), datetime(2009, 11, 8) + timedelta(seconds=10)],
        }
    )
    embeddings = {1: np.array([1.0, 2.0], dtype=np.float32)}

    raw_graph = build_pyg_dataset(
        {"blk_1": sequence},
        {"blk_1": 0},
        embeddings,
        dataset="hdfs",
        hdfs_feature_contract="notebook_raw_v1",
        on_graph_error="fail",
    )[0]
    stabilized_graph = build_pyg_dataset(
        {"blk_1": sequence},
        {"blk_1": 0},
        embeddings,
        dataset="hdfs",
        hdfs_feature_contract="stabilized_v2",
        on_graph_error="fail",
    )[0]

    assert raw_graph.x[0, 2:6].tolist() == [2.0, 2.0, -5.0, -5.0]
    assert raw_graph.edge_attr[0, :7].tolist() == [1.0, 10.0, 10.0, 10.0, 10.0, 10.0, 0.0]
    assert stabilized_graph.x[0, 2:6].tolist() != raw_graph.x[0, 2:6].tolist()
    assert stabilized_graph.edge_attr[0, :7].tolist() != raw_graph.edge_attr[0, :7].tolist()


@pytest.mark.ml
@pytest.mark.parametrize(
    ("mutator", "prefix"),
    [
        (_mutate_graph_feature, "GRAPH_FEATURES"),
        (_mutate_score, "SCORES"),
        (_mutate_ordered_blocks, "ORDERED_BLOCKS"),
        (_mutate_parser_checksum, "PARSER_CHECKSUM"),
        (_mutate_threshold, "THRESHOLD"),
    ],
)
def test_golden_fixture_fails_when_oracle_is_altered(
    mutator: Callable[[dict[str, Any]], dict[str, Any]], prefix: str
) -> None:
    from src.modules.hdfs_inference import compare_processing_parity, score_frozen_hdfs_log

    expected = mutator(copy.deepcopy(_expected()))
    manifest = ModelPackageManifest.model_validate(
        json.loads((FIXTURE / "package" / MANIFEST_NAME).read_text(encoding="utf-8"))
    )
    actual = score_frozen_hdfs_log(
        manifest=manifest,
        bundle_dir=FIXTURE / "bundle",
        log_path=FIXTURE / "hdfs.log",
        artifact_path=FIXTURE / "package" / "model.pt",
    )
    mismatches = compare_processing_parity(actual.as_snapshot(), expected)
    assert mismatches
    assert any(item.startswith(prefix) for item in mismatches)


@pytest.mark.ml
def test_golden_fixture_fails_when_parser_bytes_change(tmp_path: Path) -> None:
    from src.modules.hdfs_inference import compare_processing_parity, score_frozen_hdfs_log

    workspace = tmp_path / "release"
    shutil.copytree(FIXTURE, workspace)
    parser = workspace / "bundle" / "drain_parser.bin"
    parser.write_bytes(parser.read_bytes() + b"\x00")
    expected = _expected()
    manifest = ModelPackageManifest.model_validate(
        json.loads((workspace / "package" / MANIFEST_NAME).read_text(encoding="utf-8"))
    )
    try:
        actual = score_frozen_hdfs_log(
            manifest=manifest,
            bundle_dir=workspace / "bundle",
            log_path=workspace / "hdfs.log",
            artifact_path=workspace / "package" / "model.pt",
        )
    except Exception:
        return
    mismatches = compare_processing_parity(actual.as_snapshot(), expected)
    assert any(item.startswith("PARSER_CHECKSUM") for item in mismatches)


# Golden-fixture release_gate tests remain opt-in. The approved 11-million-line
# corpus is a documented manual release check, not a default pytest dependency.
@pytest.mark.ml
@pytest.mark.release_gate
def test_parity_command_shards_complete_test_blocks_under_service_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.modules.hdfs_inference as hdfs_inference
    import src.modules.hdfs_parity as hdfs_parity

    shard_writes: list[Path] = []
    original_write = hdfs_parity.write_evaluation_shards

    def _record_write(
        *,
        corpus: Path,
        partitions: Sequence[Sequence[str]],
        destination: Path,
    ) -> list[Path]:
        shard_writes.append(destination)
        return original_write(corpus=corpus, partitions=partitions, destination=destination)

    monkeypatch.setattr(hdfs_inference, "MAX_SOURCE_LINES", 2)
    monkeypatch.setattr(hdfs_inference, "MAX_BLOCKS", 1)
    monkeypatch.setattr(hdfs_parity, "write_evaluation_shards", _record_write)
    model_zip, bundle_zip = _zip_fixture(tmp_path)
    report = verify_hdfs_release(
        model_package=model_zip,
        preprocessing_bundle=bundle_zip,
        corpus=FIXTURE / "hdfs.log",
        labels=FIXTURE / "labels.csv",
        expected=load_parity_expected(EXPECTED_PATH),
        report_path=tmp_path / "parity-report.json",
    )

    assert shard_writes, "parity scoring must materialize shards through the shared builder"
    assert report["passed"] is True
    assert report["inference"]["n_shards"] == 2
    assert report["inference"]["source_line_count"] == 4
    assert report["inference"]["annotated_line_count"] == 4


@pytest.mark.ml
@pytest.mark.release_gate
def test_parity_command_accepts_golden_release(tmp_path: Path) -> None:
    model_zip, bundle_zip = _zip_fixture(tmp_path)
    report = verify_hdfs_release(
        model_package=model_zip,
        preprocessing_bundle=bundle_zip,
        corpus=FIXTURE / "hdfs.log",
        labels=FIXTURE / "labels.csv",
        expected=load_parity_expected(EXPECTED_PATH),
        report_path=tmp_path / "parity-report.json",
    )
    assert report["passed"] is True
    assert report["failures"] == []
    assert report["threshold"]["equal"] is True
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    for payload in metrics.values():
        assert payload["within_tolerance"] is True


@pytest.mark.ml
@pytest.mark.release_gate
def test_parity_command_fails_metric_and_threshold_drift(tmp_path: Path) -> None:
    model_zip, bundle_zip = _zip_fixture(tmp_path)
    expected_payload = _expected()
    metrics = expected_payload["metrics"]
    assert isinstance(metrics, dict)
    metrics["test_f1"] = 0.0
    metrics["best_threshold"] = float(metrics["best_threshold"]) + 1.0
    report = verify_hdfs_release(
        model_package=model_zip,
        preprocessing_bundle=bundle_zip,
        corpus=FIXTURE / "hdfs.log",
        labels=FIXTURE / "labels.csv",
        expected=ParityExpected.model_validate(expected_payload),
        report_path=tmp_path / "parity-report.json",
    )
    assert report["passed"] is False
    assert "threshold" in report["failures"]
    assert "metrics.test_f1" in report["failures"]
