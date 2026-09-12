"""Controlled HDFS release parity: checksums, threshold equality, and metric deltas.

The labelled full-corpus gate is a release check, not a default web or CI test.
It never mutates the immutable expected values; it only writes a comparison report.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.modules.hdfs_evaluation_data import (
    EvaluationDataError,
    load_evaluation_labels,
    load_selected_block_ids,
    partition_selected_block_ids,
    write_evaluation_shards,
)
from src.modules.inference_bundle import DRAIN_CONFIG_NAME, DRAIN_PARSER_NAME, EMBEDDINGS_NAME
from src.modules.model_package import MANIFEST_NAME, ModelPackageManifest, unpack_zip_bytes

METRIC_TOLERANCE = 0.01
METRIC_NAMES = ("test_f1", "test_pr_auc", "test_roc_auc")
PARITY_SHARD_MAX_BLOCKS = 1_000
PARITY_SHARD_MAX_SOURCE_LINES = 50_000
PARITY_SCORE_BATCH_SIZE = 128


class ParityError(ValueError):
    """Raised when a parity input is missing, malformed, or cannot be aligned."""


class ParityMetrics(BaseModel):
    """Named baseline metrics gated by FR-011."""

    model_config = ConfigDict(extra="forbid")

    best_threshold: float
    test_f1: float
    test_pr_auc: float
    test_roc_auc: float


class ParityExpected(BaseModel):
    """Explicit expected checksums and metrics for one baseline release."""

    model_config = ConfigDict(extra="ignore")

    checksums: dict[str, str]
    metrics: ParityMetrics
    test_block_ids: list[str] | None = None
    test_block_ids_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    test_block_count: int | None = Field(default=None, gt=0)
    metric_tolerance: float = Field(default=METRIC_TOLERANCE, gt=0)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a regular file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_parity_expected(path: Path) -> ParityExpected:
    """Load and validate a machine-readable expected-parity record."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ParityError("Expected parity record must be readable UTF-8 JSON.") from error
    try:
        return ParityExpected.model_validate(payload)
    except Exception as error:
        raise ParityError("Expected parity record is missing required checksums or metrics.") from error


def load_hdfs_block_labels(path: Path) -> dict[str, int]:
    """Load unique BlockId → {0,1} labels from the HDFS anomaly CSV."""

    try:
        return load_evaluation_labels(path)
    except EvaluationDataError as error:
        raise ParityError(str(error)) from error


def load_test_block_ids(path: Path) -> list[str]:
    """Load an ordered test-split block ID list, one identifier per line."""

    try:
        return load_selected_block_ids(path)
    except EvaluationDataError as error:
        raise ParityError(str(error)) from error


def verify_artefact_checksums(
    files: Mapping[str, Path],
    expected: Mapping[str, str],
) -> dict[str, Any]:
    """Compare SHA-256 digests for every expected artefact name.

    ``files`` maps the same logical names used in ``expected`` to local paths.
    Missing files and digest mismatches are recorded; this function does not
    score a model.
    """

    results: dict[str, Any] = {}
    for name, digest in expected.items():
        path = files.get(name)
        if path is None or not path.is_file():
            results[name] = {
                "expected": digest,
                "actual": None,
                "matched": False,
                "error": "missing",
            }
            continue
        actual = sha256_file(path)
        results[name] = {
            "expected": digest,
            "actual": actual,
            "matched": actual == digest,
        }
    return results


def compute_detection_metrics(
    labels: Sequence[int],
    scores: Sequence[float],
    threshold: float,
) -> dict[str, float]:
    """Compute test F1, PR-AUC, and ROC-AUC using the training-runner contract."""

    import numpy as np
    from sklearn.metrics import average_precision_score, f1_score, roc_auc_score

    label_array = np.asarray(labels, dtype=int)
    score_array = np.asarray(scores, dtype=float)
    predictions = (score_array > threshold).astype(int)
    has_both_classes = len(np.unique(label_array)) == 2
    return {
        "test_f1": float(f1_score(label_array, predictions, zero_division=0)),
        "test_pr_auc": (
            float(average_precision_score(label_array, score_array)) if has_both_classes else 0.0
        ),
        "test_roc_auc": (
            float(roc_auc_score(label_array, score_array)) if has_both_classes else 0.0
        ),
    }


def evaluate_metric_gate(
    expected: ParityMetrics,
    actual_metrics: Mapping[str, float],
    actual_threshold: float,
    *,
    tolerance: float = METRIC_TOLERANCE,
) -> dict[str, Any]:
    """Compare threshold equality and core metric deltas without replacing expected values."""

    threshold_equal = float(actual_threshold) == float(expected.best_threshold)
    metrics: dict[str, Any] = {}
    for name in METRIC_NAMES:
        expected_value = float(getattr(expected, name))
        actual_value = float(actual_metrics[name])
        delta = actual_value - expected_value
        metrics[name] = {
            "expected": expected_value,
            "actual": actual_value,
            "delta": delta,
            "within_tolerance": abs(delta) <= tolerance,
        }
    return {
        "threshold": {
            "expected": float(expected.best_threshold),
            "actual": float(actual_threshold),
            "equal": threshold_equal,
        },
        "metrics": metrics,
        "tolerance": tolerance,
    }


def align_test_scores(
    *,
    block_ids: Sequence[str],
    scores: Sequence[float],
    labels: Mapping[str, int],
    test_block_ids: Sequence[str] | None,
) -> tuple[list[str], list[int], list[float]]:
    """Select the labelled evaluation split; default is every scored block."""

    if len(block_ids) != len(scores):
        raise ParityError("Score count does not match block count.")
    score_map = {str(block_id): float(score) for block_id, score in zip(block_ids, scores, strict=True)}
    selected = [str(block_id) for block_id in (test_block_ids or block_ids)]
    if not selected:
        raise ParityError("Parity evaluation requires at least one test block.")
    aligned_labels: list[int] = []
    aligned_scores: list[float] = []
    for block_id in selected:
        if block_id not in score_map:
            raise ParityError(f"Test block {block_id} was not scored by frozen inference.")
        if block_id not in labels:
            raise ParityError(f"Test block {block_id} has no label in the baseline CSV.")
        aligned_labels.append(int(labels[block_id]))
        aligned_scores.append(score_map[block_id])
    return selected, aligned_labels, aligned_scores


def unpack_release_zips(
    *,
    model_package: Path,
    preprocessing_bundle: Path,
    destination: Path,
) -> tuple[Path, Path]:
    """Unpack trusted v2 archives into package/ and bundle/ directories."""

    package_dir = destination / "package"
    bundle_dir = destination / "bundle"
    package_dir.mkdir()
    bundle_dir.mkdir()
    package_result = unpack_zip_bytes(model_package.read_bytes(), package_dir)
    if not package_result.valid:
        raise ParityError("Model package ZIP failed transport validation.")
    bundle_result = unpack_zip_bytes(preprocessing_bundle.read_bytes(), bundle_dir)
    if not bundle_result.valid:
        raise ParityError("Preprocessing-bundle ZIP failed transport validation.")
    return package_dir, bundle_dir


def write_zip(source_dir: Path, destination: Path) -> None:
    """Write declared regular files from a directory into a ZIP archive."""

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.iterdir()):
            if path.is_file():
                archive.write(path, arcname=path.name)


def _strictly_count_selected_block_lines(
    *,
    corpus: Path,
    bundle_dir: Path,
    selected_block_ids: Sequence[str],
) -> tuple[int, int, dict[str, int]]:
    """Validate all non-empty source lines and count records for selected blocks."""

    from src.modules.parser.drain_parser import DrainParser

    selected = set(selected_block_ids)
    parser_path = bundle_dir / DRAIN_PARSER_NAME
    config_path = bundle_dir / DRAIN_CONFIG_NAME
    try:
        parser = DrainParser.load(str(parser_path), config_path=str(config_path))
    except Exception as error:
        raise ParityError("Unable to load the frozen Drain parser for full-corpus validation.") from error

    source_line_count = 0
    selected_line_counts = {block_id: 0 for block_id in selected_block_ids}
    with corpus.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.rstrip("\n")
            if not line:
                continue
            source_line_count += 1
            content = parser._preprocess_line(line, parser._HEADER_TOKENS)
            if parser.miner.match(content) is None:
                raise ParityError(
                    f"Frozen parser did not match baseline corpus line {line_number}."
                )
            block_id = parser.extract_hdfs_block_id(line)
            if block_id is not None and block_id in selected:
                selected_line_counts[block_id] += 1
    return source_line_count, source_line_count, selected_line_counts


def _parity_shard_limits() -> tuple[int, int]:
    """Return source-line and block caps for temporary parity shards."""

    from src.modules.hdfs_inference import MAX_BLOCKS, MAX_SOURCE_LINES

    return (
        min(MAX_SOURCE_LINES, PARITY_SHARD_MAX_SOURCE_LINES),
        min(MAX_BLOCKS, PARITY_SHARD_MAX_BLOCKS),
    )


def _score_selected_test_blocks(
    *,
    corpus: Path,
    manifest: ModelPackageManifest,
    bundle_dir: Path,
    artifact_path: Path,
    test_block_ids: Sequence[str],
    destination: Path,
) -> tuple[dict[str, float], dict[str, int]]:
    """Strictly validate a full corpus and score its complete test blocks in shards."""

    if len(test_block_ids) != len(set(test_block_ids)):
        raise ParityError("The parity test-block ID list contains duplicates.")
    source_line_count, annotated_line_count, selected_line_counts = _strictly_count_selected_block_lines(
        corpus=corpus,
        bundle_dir=bundle_dir,
        selected_block_ids=test_block_ids,
    )
    source_line_limit, block_limit = _parity_shard_limits()
    try:
        partitions = partition_selected_block_ids(
            selected_block_ids=test_block_ids,
            selected_line_counts=selected_line_counts,
            max_source_lines=source_line_limit,
            max_blocks=block_limit,
        )
        shard_paths = write_evaluation_shards(
            corpus=corpus,
            partitions=partitions,
            destination=destination,
        )
    except EvaluationDataError as error:
        raise ParityError(str(error)) from error

    from src.modules.hdfs_inference import score_frozen_hdfs_log

    scores_by_block: dict[str, float] = {}
    for shard_path in shard_paths:
        scored = score_frozen_hdfs_log(
            manifest=manifest,
            bundle_dir=bundle_dir,
            log_path=shard_path,
            artifact_path=artifact_path,
            batch_size=PARITY_SCORE_BATCH_SIZE,
        )
        for block in scored.blocks:
            if block.block_id not in selected_line_counts:
                raise ParityError(f"Parity shard scored unexpected block {block.block_id}.")
            if block.block_id in scores_by_block:
                raise ParityError(f"Parity shard scored block {block.block_id} more than once.")
            scores_by_block[block.block_id] = block.score
    missing_scored_blocks = [block_id for block_id in test_block_ids if block_id not in scores_by_block]
    if missing_scored_blocks:
        raise ParityError(
            f"{len(missing_scored_blocks)} selected test blocks were not scored by the release."
        )
    return scores_by_block, {
        "source_line_count": source_line_count,
        "annotated_line_count": annotated_line_count,
        "n_shards": len(shard_paths),
    }


def _verify_test_split(
    *,
    expected: ParityExpected,
    test_block_ids: Sequence[str] | None,
    test_block_ids_sha256: str | None,
) -> tuple[dict[str, Any], bool]:
    """Verify the supplied split's declared order, count, and optional digest."""

    actual_count = None if test_block_ids is None else len(test_block_ids)
    expected_ids = expected.test_block_ids
    expected_count = expected.test_block_count
    expected_checksum = expected.test_block_ids_sha256
    content_matches = expected_ids is None or test_block_ids is None or list(test_block_ids) == expected_ids
    count_matches = expected_count is None or actual_count == expected_count
    checksum_matches = expected_checksum is None or test_block_ids_sha256 == expected_checksum
    evidence = {
        "content": {
            "enforced": expected_ids is not None,
            "matched": content_matches,
        },
        "count": {
            "expected": expected_count,
            "actual": actual_count,
            "matched": count_matches,
        },
        "checksum": {
            "expected": expected_checksum,
            "actual": test_block_ids_sha256,
            "matched": checksum_matches,
        },
    }
    return evidence, content_matches and count_matches and checksum_matches


def verify_hdfs_release(
    *,
    model_package: Path,
    preprocessing_bundle: Path,
    corpus: Path,
    labels: Path,
    expected: ParityExpected,
    report_path: Path,
    test_block_ids: Sequence[str] | None = None,
    test_block_ids_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify checksums, exact threshold, and metric deltas; write a comparison report."""

    from src.modules.hdfs_inference import HdfsInferenceError, score_frozen_hdfs_log

    files: dict[str, Path] = {
        "corpus": corpus,
        "labels": labels,
        "model_package": model_package,
        "preprocessing_bundle": preprocessing_bundle,
    }
    failures: list[str] = []
    inference: dict[str, Any] | None = None
    gate: dict[str, Any] | None = None
    selected_test_ids = list(test_block_ids) if test_block_ids is not None else expected.test_block_ids
    test_split, test_split_ok = _verify_test_split(
        expected=expected,
        test_block_ids=selected_test_ids,
        test_block_ids_sha256=test_block_ids_sha256,
    )
    checksums = verify_artefact_checksums(files, expected.checksums)
    try:
        with tempfile.TemporaryDirectory(prefix="hdfs-parity-") as tmp:
            package_dir, bundle_dir = unpack_release_zips(
                model_package=model_package,
                preprocessing_bundle=preprocessing_bundle,
                destination=Path(tmp),
            )
            files.update(
                {
                    "model.pt": package_dir / "model.pt",
                    "drain.ini": bundle_dir / DRAIN_CONFIG_NAME,
                    "drain_parser.bin": bundle_dir / DRAIN_PARSER_NAME,
                    "embeddings.npz": bundle_dir / EMBEDDINGS_NAME,
                }
            )
            checksums = verify_artefact_checksums(files, expected.checksums)
            checksums_ok = all(entry["matched"] for entry in checksums.values())
            if not checksums_ok:
                failures.extend(
                    f"checksums.{name}" for name, entry in checksums.items() if not entry["matched"]
                )
            if checksums_ok and test_split_ok:
                manifest = ModelPackageManifest.model_validate(
                    json.loads((package_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
                )
                label_map = load_hdfs_block_labels(labels)
                if selected_test_ids:
                    scores_by_block, parity_metadata = _score_selected_test_blocks(
                        corpus=corpus,
                        manifest=manifest,
                        bundle_dir=bundle_dir,
                        artifact_path=package_dir / "model.pt",
                        test_block_ids=selected_test_ids,
                        destination=Path(tmp) / "test-shards",
                    )
                    scored_block_ids = list(scores_by_block)
                    scored_values = list(scores_by_block.values())
                    threshold = float(manifest.metrics.best_threshold)
                    inference_metadata: dict[str, Any] = {
                        "n_scored_blocks": len(scores_by_block),
                        "n_shards": parity_metadata["n_shards"],
                        "source_line_count": parity_metadata["source_line_count"],
                        "annotated_line_count": parity_metadata["annotated_line_count"],
                    }
                else:
                    scored = score_frozen_hdfs_log(
                        manifest=manifest,
                        bundle_dir=bundle_dir,
                        log_path=corpus,
                        artifact_path=package_dir / "model.pt",
                    )
                    scored_block_ids = [block.block_id for block in scored.blocks]
                    scored_values = [block.score for block in scored.blocks]
                    threshold = scored.threshold
                    inference_metadata = {
                        "n_scored_blocks": len(scored.blocks),
                        "n_shards": 1,
                        "source_line_count": scored.source_line_count,
                        "annotated_line_count": scored.annotated_line_count,
                    }
                selected, y_true, y_score = align_test_scores(
                    block_ids=scored_block_ids,
                    scores=scored_values,
                    labels=label_map,
                    test_block_ids=selected_test_ids,
                )
                actual_metrics = compute_detection_metrics(
                    y_true, y_score, threshold
                )
                gate = evaluate_metric_gate(
                    expected.metrics,
                    actual_metrics,
                    threshold,
                    tolerance=expected.metric_tolerance,
                )
                if not gate["threshold"]["equal"]:
                    failures.append("threshold")
                for name, payload in gate["metrics"].items():
                    if not payload["within_tolerance"]:
                        failures.append(f"metrics.{name}")
                inference = {
                    **inference_metadata,
                    "n_test_blocks": len(selected),
                    "threshold": threshold,
                    "metrics": actual_metrics,
                }
            elif checksums_ok:
                for name, payload in test_split.items():
                    if not payload["matched"]:
                        failures.append(f"test_block_ids.{name}")
    except (ParityError, HdfsInferenceError) as error:
        failures.append("parity_input")
        inference = {"error": str(error)}

    report = {
        "passed": not failures,
        "checksums": checksums,
        "test_block_ids": test_split,
        "threshold": None if gate is None else gate["threshold"],
        "metrics": None if gate is None else gate["metrics"],
        "tolerance": expected.metric_tolerance,
        "inference": inference,
        "failures": failures,
    }
    _write_report(report_path, report)
    return report


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == "expected.json":
        raise ParityError("Refusing to overwrite the immutable expected parity record.")
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
