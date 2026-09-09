"""Safe validation of trusted workspace paths, packages, and HDFS log datasets."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.api.settings import ApiSettings
from src.modules.model_package import MANIFEST_NAME, ModelPackageManifest, PackageValidationResult

_HDFS_LINE = re.compile(
    r"^\d{6}\s+\d{6}\s+\S+\s+(?:TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+\S+:\s+\S.+$"
)
_MAX_EXAMPLES = 20
_SECRET_ENV_NAMES = frozenset(
    {
        "API_JWT_SECRET",
        "DATABASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "BUCKET_ACCESS_KEY_ID",
        "BUCKET_SECRET_ACCESS_KEY",
        "RAILWAY_TOKEN",
    }
)
_SECRET_ENV_PREFIXES = ("API_", "AWS_", "RAILWAY_", "BUCKET_")


class ValidationError(ValueError):
    """A client-visible validation failure that never includes filesystem details."""


class ValidatorUnavailableError(RuntimeError):
    """The private package-validation process failed, timed out, or returned garbage."""


@dataclass(frozen=True)
class AdmittedModelPackage:
    """Validated package identity persisted after a successful private probe."""

    model_identifier: str
    version: str
    pipeline_run_id: str
    package_reference: str
    artifact_reference: str
    artifact_sha256: str
    metrics: dict[str, Any]
    metadata: dict[str, Any]
    external_evaluation_evidence: str


def trusted_package_directory(reference: str, workspace_root: Path) -> Path:
    """Resolve a pre-staged package directory inside the trusted workspace."""

    resolved = _resolved_inside_workspace(reference, workspace_root, "package reference")
    if resolved.is_file():
        raise ValidationError("Package reference must be a directory, not a file or zip archive.")
    if not resolved.is_dir():
        raise ValidationError("Package reference does not exist or is not a directory.")
    return resolved


def run_private_package_validator(
    package_root: Path,
    settings: ApiSettings,
) -> PackageValidationResult:
    """Ask the isolated validator process for a typed report. Never load the artifact here."""

    command = list(settings.model_validator_command or (sys.executable, "-m", "src.model_validator"))
    command.append(str(package_root))
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=_scrubbed_subprocess_env(settings.code_root),
            cwd=str(settings.code_root),
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValidatorUnavailableError("Model package validator is unavailable.") from error
    if completed.returncode != 0:
        raise ValidatorUnavailableError("Model package validator is unavailable.")
    try:
        payload = json.loads(completed.stdout)
        return PackageValidationResult.model_validate(payload)
    except Exception as error:
        raise ValidatorUnavailableError("Model package validator returned a malformed report.") from error


def admit_validated_package(package_root: Path, workspace_root: Path) -> AdmittedModelPackage:
    """Re-read a validator-accepted directory and copy identity fields for persistence."""

    workspace = workspace_root.resolve()
    root = package_root.resolve()
    manifest_path = root / MANIFEST_NAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = ModelPackageManifest.model_validate(payload)
    except Exception as error:
        raise ValidatorUnavailableError("Validated package manifest could not be re-read.") from error
    artifact_path = (root / manifest.files.artifact).resolve()
    try:
        artifact_path.relative_to(workspace)
    except ValueError as error:
        raise ValidationError("Package artifact must stay inside the trusted workspace.") from error
    if not artifact_path.is_file() or artifact_path.is_symlink():
        raise ValidationError("Package artifact must be a regular file.")
    return AdmittedModelPackage(
        model_identifier=manifest.model_identifier,
        version=manifest.version,
        pipeline_run_id=manifest.pipeline_run_id or manifest.model_identifier,
        package_reference=root.relative_to(workspace).as_posix(),
        artifact_reference=artifact_path.relative_to(workspace).as_posix(),
        artifact_sha256=manifest.files.checksums[manifest.files.artifact],
        metrics=manifest.metrics.model_dump(),
        metadata={
            "format": manifest.format,
            "architecture": manifest.architecture.model_dump(),
            "scoring": manifest.scoring.model_dump(),
        },
        external_evaluation_evidence=manifest.files.evidence,
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
    resolved = _resolved_inside_workspace(reference, workspace_root, resource_name)
    if not resolved.is_file():
        raise ValidationError(f"{resource_name.capitalize()} does not exist or is not a regular file.")
    return resolved


def _resolved_inside_workspace(reference: str, workspace_root: Path, resource_name: str) -> Path:
    root = workspace_root.resolve()
    candidate = Path(reference)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValidationError(f"{resource_name.capitalize()} must be inside the trusted workspace.") from error
    return resolved


def _scrubbed_subprocess_env(code_root: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if _keep_env_key(key)}
    pythonpath = str(code_root.resolve())
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = pythonpath if not existing else pythonpath + os.pathsep + existing
    return env


def _keep_env_key(key: str) -> bool:
    return key not in _SECRET_ENV_NAMES and not key.startswith(_SECRET_ENV_PREFIXES)
