"""Focused tests for the pinned HDFS reference-membership catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.modules.hdfs_completeness import (
    CompletenessCatalogError,
    REFERENCE_MEMBERSHIP_POLICY,
    load_hdfs_reference_catalog,
)
from src.modules.hdfs_evaluation_data import (
    SELECTED_IDS_NAME,
    EvaluationDataManifest,
    materialize_hdfs_evaluation_data,
    sha256_file,
)


def _hdfs_line(date: str, time: str, thread: str, message: str) -> str:
    return f"{date} {time} {thread} INFO dfs.DataNode$DataXceiver: {message}"


def _write_corpus(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_labels(path: Path, rows: list[tuple[str, str]]) -> Path:
    body = "BlockId,Label\n" + "".join(f"{block_id},{label}\n" for block_id, label in rows)
    path.write_text(body, encoding="utf-8")
    return path


def _write_ids(path: Path, block_ids: list[str]) -> Path:
    path.write_text("".join(f"{block_id}\n" for block_id in block_ids), encoding="utf-8")
    return path


def _materialize_catalog(tmp_path: Path) -> Path:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [
            _hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1"),
            _hdfs_line("081109", "203616", "149", "Receiving block blk_2 src: /10.0.0.1"),
            _hdfs_line("081109", "203617", "150", "Receiving block blk_1 src: /10.0.0.2"),
        ],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "1"), ("blk_2", "0")])
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1", "blk_2"])
    destination = tmp_path / "evaluation-data"
    materialize_hdfs_evaluation_data(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected,
        destination=destination,
    )
    return destination / "manifest.json"


def _assert_error_hides_location(
    error: CompletenessCatalogError,
    tmp_path: Path,
    *,
    reason: str,
) -> None:
    message = str(error)
    assert error.reason == reason
    assert str(tmp_path) not in message
    assert "evaluation-data" not in message
    assert "AWS" not in message
    assert "SECRET" not in message


def test_catalog_loader_accepts_valid_f03_artifact(tmp_path: Path) -> None:
    manifest_path = _materialize_catalog(tmp_path)
    digest = sha256_file(manifest_path)

    catalog = load_hdfs_reference_catalog(
        manifest_path,
        expected_manifest_sha256=digest,
    )

    assert catalog.policy_id == REFERENCE_MEMBERSHIP_POLICY
    assert catalog.manifest_sha256 == digest
    assert catalog.selected_block_ids == frozenset({"blk_1", "blk_2"})
    manifest = EvaluationDataManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    assert catalog.corpus_sha256 == manifest.corpus_sha256
    assert catalog.selected_block_ids_sha256 == manifest.selected_block_ids_sha256
    assert catalog.selected_block_ids_order_sha256 == manifest.selected_block_ids_order_sha256


def test_changed_manifest_bytes_are_rejected(tmp_path: Path) -> None:
    manifest_path = _materialize_catalog(tmp_path)
    original_digest = sha256_file(manifest_path)
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace("\n", " \n", 1),
        encoding="utf-8",
    )

    with pytest.raises(CompletenessCatalogError) as raised:
        load_hdfs_reference_catalog(
            manifest_path,
            expected_manifest_sha256=original_digest,
        )

    _assert_error_hides_location(raised.value, tmp_path, reason="manifest_digest_mismatch")


def test_changed_selected_id_bytes_are_rejected(tmp_path: Path) -> None:
    manifest_path = _materialize_catalog(tmp_path)
    digest = sha256_file(manifest_path)
    selected_path = manifest_path.parent / SELECTED_IDS_NAME
    selected_path.write_text(selected_path.read_text(encoding="utf-8") + "blk_9\n", encoding="utf-8")

    with pytest.raises(CompletenessCatalogError) as raised:
        load_hdfs_reference_catalog(manifest_path, expected_manifest_sha256=digest)

    _assert_error_hides_location(raised.value, tmp_path, reason="selected_ids_digest_mismatch")


def test_duplicate_selected_ids_are_rejected(tmp_path: Path) -> None:
    manifest_path = _materialize_catalog(tmp_path)
    selected_path = manifest_path.parent / SELECTED_IDS_NAME
    selected_path.write_text("blk_1\nblk_1\n", encoding="utf-8")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["selected_block_ids_sha256"] = sha256_file(selected_path)
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(CompletenessCatalogError) as raised:
        load_hdfs_reference_catalog(
            manifest_path,
            expected_manifest_sha256=sha256_file(manifest_path),
        )

    _assert_error_hides_location(raised.value, tmp_path, reason="selected_ids_malformed")


def test_missing_selected_id_sibling_is_rejected(tmp_path: Path) -> None:
    manifest_path = _materialize_catalog(tmp_path)
    digest = sha256_file(manifest_path)
    (manifest_path.parent / SELECTED_IDS_NAME).unlink()

    with pytest.raises(CompletenessCatalogError) as raised:
        load_hdfs_reference_catalog(manifest_path, expected_manifest_sha256=digest)

    _assert_error_hides_location(raised.value, tmp_path, reason="selected_ids_missing")
