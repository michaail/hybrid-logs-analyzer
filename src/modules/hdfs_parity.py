"""Controlled HDFS release parity: checksums, threshold equality, and metric deltas.

The labelled full-corpus gate is a release check, not a default web or CI test.
It never mutates the immutable expected values; it only writes a comparison report.
"""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.modules.inference_bundle import DRAIN_CONFIG_NAME, DRAIN_PARSER_NAME, EMBEDDINGS_NAME
from src.modules.model_package import MANIFEST_NAME, ModelPackageManifest, unpack_zip_bytes

METRIC_TOLERANCE = 0.01
METRIC_NAMES = ("test_f1", "test_pr_auc", "test_roc_auc")


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
    metric_tolerance: float = Field(default=METRIC_TOLERANCE, gt=0)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a regular file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    """Load BlockId → {0,1} labels from the HDFS anomaly CSV."""

    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ParityError("Labels CSV must include a header row.")
            columns = {name.lower(): name for name in reader.fieldnames if name}
            id_column = next(
                (columns[name] for name in ("blockid", "block_id") if name in columns),
                None,
            )
            label_column = next(
                (columns[name] for name in ("label", "anomaly", "is_anomaly") if name in columns),
                None,
            )
            if id_column is None or label_column is None:
                raise ParityError("Labels CSV must include BlockId and Label columns.")
            mapping: dict[str, int] = {}
            for row in reader:
                mapping[str(row[id_column])] = _to_binary_label(row[label_column])
    except ParityError:
        raise
    except OSError as error:
        raise ParityError("Labels file is missing or unreadable.") from error
    if not mapping:
        raise ParityError("Labels CSV does not contain any block rows.")
    return mapping


def load_test_block_ids(path: Path) -> list[str]:
    """Load an ordered test-split block ID list, one identifier per line."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ParityError("Test block-id file is missing or unreadable.") from error
    block_ids = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    if not block_ids:
        raise ParityError("Test block-id file does not contain any identifiers.")
    return block_ids


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


def verify_hdfs_release(
    *,
    model_package: Path,
    preprocessing_bundle: Path,
    corpus: Path,
    labels: Path,
    expected: ParityExpected,
    report_path: Path,
    test_block_ids: Sequence[str] | None = None,
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
            if checksums_ok:
                manifest = ModelPackageManifest.model_validate(
                    json.loads((package_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
                )
                scored = score_frozen_hdfs_log(
                    manifest=manifest,
                    bundle_dir=bundle_dir,
                    log_path=corpus,
                    artifact_path=package_dir / "model.pt",
                )
                label_map = load_hdfs_block_labels(labels)
                selected, y_true, y_score = align_test_scores(
                    block_ids=[block.block_id for block in scored.blocks],
                    scores=[block.score for block in scored.blocks],
                    labels=label_map,
                    test_block_ids=test_block_ids or expected.test_block_ids,
                )
                actual_metrics = compute_detection_metrics(
                    y_true, y_score, scored.threshold
                )
                gate = evaluate_metric_gate(
                    expected.metrics,
                    actual_metrics,
                    scored.threshold,
                    tolerance=expected.metric_tolerance,
                )
                if not gate["threshold"]["equal"]:
                    failures.append("threshold")
                for name, payload in gate["metrics"].items():
                    if not payload["within_tolerance"]:
                        failures.append(f"metrics.{name}")
                inference = {
                    "n_scored_blocks": len(scored.blocks),
                    "n_test_blocks": len(selected),
                    "threshold": scored.threshold,
                    "metrics": actual_metrics,
                }
    except (ParityError, HdfsInferenceError) as error:
        failures.append("parity_input")
        checksums = verify_artefact_checksums(files, expected.checksums)
        inference = {"error": str(error)}

    report = {
        "passed": not failures,
        "checksums": checksums,
        "threshold": None if gate is None else gate["threshold"],
        "metrics": None if gate is None else gate["metrics"],
        "tolerance": expected.metric_tolerance,
        "inference": inference,
        "failures": failures,
    }
    _write_report(report_path, report)
    return report


def _to_binary_label(value: str | int | bool | None) -> int:
    if isinstance(value, str):
        return int(value.strip().lower() in {"1", "true", "anomaly", "anomalous"})
    return int(bool(value))


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == "expected.json":
        raise ParityError("Refusing to overwrite the immutable expected parity record.")
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
