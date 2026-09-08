"""Safe validation of trusted pipeline references and HDFS log datasets."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HDFS_LINE = re.compile(
    r"^\d{6}\s+\d{6}\s+\S+\s+(?:TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+\S+:\s+\S.+$"
)
_MAX_EXAMPLES = 20


class ValidationError(ValueError):
    """A client-visible validation failure that never includes filesystem details."""


@dataclass(frozen=True)
class TrustedPipelineModel:
    """Validated provenance for a model that the API may register but never load."""

    run_id: str
    artifact_reference: str
    metrics: dict[str, Any]


def validate_pipeline_model(manifest_reference: str, workspace_root: Path) -> TrustedPipelineModel:
    """Validate a HDFS pipeline run manifest and its referenced model checkpoint."""
    manifest_path = _trusted_file(manifest_reference, workspace_root, "pipeline run manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError("Pipeline run manifest must be readable valid JSON.") from error
    if not isinstance(manifest, dict):
        raise ValidationError("Pipeline run manifest must contain a JSON object.")
    if manifest.get("dataset") != "hdfs":
        raise ValidationError("Only successful HDFS pipeline runs can be registered.")

    run_id = manifest.get("run_id")
    metrics = manifest.get("metrics")
    artifacts = manifest.get("artifacts")
    if not isinstance(run_id, str) or not run_id:
        raise ValidationError("Pipeline run manifest is missing its run_id.")
    if not isinstance(metrics, dict):
        raise ValidationError("Pipeline run manifest is missing evaluation metrics.")
    if (
        not isinstance(artifacts, dict)
        or not isinstance(artifacts.get("checkpoint"), str)
        or not isinstance(artifacts.get("metrics"), str)
    ):
        raise ValidationError("Pipeline run manifest is missing checkpoint or metrics references.")

    threshold = metrics.get("best_threshold")
    if not isinstance(threshold, (float, int)) or isinstance(threshold, bool) or not math.isfinite(threshold):
        raise ValidationError("Pipeline run metrics must include a finite best_threshold.")

    artifact_path = _trusted_file(artifacts["checkpoint"], workspace_root, "model artifact")
    _trusted_file(artifacts["metrics"], workspace_root, "pipeline metrics")
    expected_artifact = Path("outputs") / "hdfs" / run_id / "attribute_gae.pt"
    if artifact_path.relative_to(workspace_root.resolve()) != expected_artifact:
        raise ValidationError("Model artifact must be the canonical checkpoint from its HDFS pipeline run.")
    return TrustedPipelineModel(
        run_id=run_id,
        artifact_reference=str(artifact_path.relative_to(workspace_root.resolve())),
        metrics=metrics,
    )


def validate_hdfs_log(log_reference: str, workspace_root: Path) -> tuple[str, dict[str, Any]]:
    """Read every stored log record and return an HDFS validation report."""
    log_path = _trusted_file(log_reference, workspace_root, "HDFS log dataset")
    total_records = 0
    invalid_examples: list[dict[str, Any]] = []
    invalid_records = 0

    try:
        with log_path.open("r", encoding="utf-8", errors="strict") as log_file:
            for line_number, raw_line in enumerate(log_file, start=1):
                line = raw_line.rstrip("\r\n")
                if not line or not _HDFS_LINE.fullmatch(line):
                    invalid_records += 1
                    if len(invalid_examples) < _MAX_EXAMPLES:
                        invalid_examples.append(
                            {
                                "line_number": line_number,
                                "reason": "Does not match the supported HDFS log format.",
                            }
                        )
                total_records += 1
    except (OSError, UnicodeDecodeError) as error:
        raise ValidationError("HDFS log dataset must be a readable UTF-8 text file.") from error

    report: dict[str, Any] = {
        "total_records": total_records,
        "invalid_records": invalid_records,
        "examples": invalid_examples,
    }
    if total_records == 0:
        report["valid"] = False
        report["examples"] = [{"line_number": 0, "reason": "Dataset contains no records."}]
    else:
        report["valid"] = invalid_records == 0
    return str(log_path.relative_to(workspace_root.resolve())), report


def _trusted_file(reference: str, workspace_root: Path, resource_name: str) -> Path:
    root = workspace_root.resolve()
    candidate = Path(reference)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValidationError(f"{resource_name.capitalize()} must be inside the trusted workspace.") from error
    if not resolved.is_file():
        raise ValidationError(f"{resource_name.capitalize()} does not exist or is not a regular file.")
    return resolved
