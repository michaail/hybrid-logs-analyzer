"""Safe validation of trusted workspace paths, packages, and HDFS log datasets."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from src.api.object_store import (
    ObjectStore,
    dataset_object_key,
    dataset_object_prefix,
    model_package_object_key,
    model_package_object_prefix,
)
from src.api.settings import ApiSettings
from src.model_validator.runtime import allowed_validator_environment
from src.modules.model_package import (
    MANIFEST_NAME,
    MAX_ZIP_COMPRESSED_BYTES,
    ModelPackageManifest,
    PackageValidationIssue,
    PackageValidationResult,
    materialize_declared_package_files,
    unpack_zip_bytes,
)

_HDFS_LINE = re.compile(
    r"^\d{6}\s+\d{6}\s+\S+\s+(?:TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+\S+:\s+\S.+$"
)
_MAX_EXAMPLES = 20
MAX_HDFS_UPLOAD_BYTES = 32 * 1024 * 1024
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class ValidationError(ValueError):
    """A client-visible validation failure that never includes filesystem details."""


class ValidatorUnavailableError(RuntimeError):
    """The private package-validation process failed, timed out, or returned garbage."""


@dataclass(frozen=True)
class AdmittedHdfsDataset:
    """Validated HDFS log identity persisted after whole-file acceptance."""

    dataset_id: UUID
    object_reference: str
    checksum: str
    storage_kind: str = "object"


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
    model_id: UUID | None = None
    storage_kind: str = "workspace"


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
            env=allowed_validator_environment(os.environ, code_root=settings.code_root),
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


def admit_uploaded_zip_package(
    archive_bytes: bytes,
    *,
    settings: ApiSettings,
    object_store: ObjectStore,
    project_id: UUID,
) -> tuple[PackageValidationResult, AdmittedModelPackage | None]:
    """Validate a ZIP in a temp directory, then persist declared files only.

    Object-store credentials are never passed into the validator subprocess.
    Invalid packages return the typed report and put nothing.
    """

    if len(archive_bytes) > MAX_ZIP_COMPRESSED_BYTES:
        return (
            PackageValidationResult.from_issues(
                [
                    PackageValidationIssue(
                        path="package",
                        reason="Zip archive exceeds the 32 MiB compressed size limit.",
                    )
                ]
            ),
            None,
        )
    if not archive_bytes:
        return (
            PackageValidationResult.from_issues(
                [
                    PackageValidationIssue(
                        path="package",
                        reason="Package zip must contain a readable archive.",
                    )
                ]
            ),
            None,
        )

    with tempfile.TemporaryDirectory(prefix="model-upload-") as tmp:
        tmp_root = Path(tmp)
        extract_root = tmp_root / "extract"
        extract_root.mkdir()
        unpack_report = unpack_zip_bytes(archive_bytes, extract_root)
        if not unpack_report.valid:
            return unpack_report, None
        report = run_private_package_validator(extract_root, settings)
        if not report.valid:
            return report, None
        identity = _admitted_identity_from_directory(extract_root)
        model_id = uuid4()
        prefix = model_package_object_prefix(project_id, model_id, identity.version)
        persist_root = tmp_root / "declared"
        try:
            relatives = materialize_declared_package_files(extract_root, persist_root)
            for relative in relatives:
                object_store.put(
                    model_package_object_key(project_id, model_id, identity.version, relative),
                    (persist_root / relative).read_bytes(),
                )
        except ValueError as error:
            object_store.delete_prefix(prefix)
            raise ValidationError(str(error)) from error
        except Exception:
            object_store.delete_prefix(prefix)
            raise
        artifact_key = model_package_object_key(
            project_id,
            model_id,
            identity.version,
            identity.files.artifact,
        )
        admitted = AdmittedModelPackage(
            model_identifier=identity.model_identifier,
            version=identity.version,
            pipeline_run_id=identity.pipeline_run_id or identity.model_identifier,
            package_reference=prefix,
            artifact_reference=artifact_key,
            artifact_sha256=identity.files.checksums[identity.files.artifact],
            metrics=identity.metrics.model_dump(),
            metadata={
                "format": identity.format,
                "architecture": identity.architecture.model_dump(),
                "scoring": identity.scoring.model_dump(),
            },
            external_evaluation_evidence=identity.files.evidence,
            model_id=model_id,
            storage_kind="object",
        )
        return PackageValidationResult.from_issues([]), admitted


def admit_validated_package(package_root: Path, workspace_root: Path) -> AdmittedModelPackage:
    """Re-read a validator-accepted directory and copy identity fields for persistence."""

    workspace = workspace_root.resolve()
    root = package_root.resolve()
    manifest = _admitted_identity_from_directory(root)
    declared_artifact = root / manifest.files.artifact
    artifact_path = declared_artifact.resolve()
    try:
        artifact_path.relative_to(workspace)
    except ValueError as error:
        raise ValidationError("Package artifact must stay inside the trusted workspace.") from error
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


def _admitted_identity_from_directory(package_root: Path) -> ModelPackageManifest:
    """Re-read a validator-accepted directory and refuse a swapped artifact."""

    root = package_root.resolve()
    manifest_path = root / MANIFEST_NAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = ModelPackageManifest.model_validate(payload)
    except Exception as error:
        raise ValidatorUnavailableError("Validated package manifest could not be re-read.") from error
    declared_artifact = root / manifest.files.artifact
    if declared_artifact.is_symlink() or not declared_artifact.is_file():
        raise ValidationError("Package artifact must be a regular file.")
    artifact_path = declared_artifact.resolve()
    try:
        artifact_path.relative_to(root)
    except ValueError as error:
        raise ValidationError("Package artifact must stay inside the package root.") from error
    expected_sha256 = manifest.files.checksums[manifest.files.artifact]
    actual_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValidationError("Package artifact SHA-256 does not match the manifest.")
    return manifest


def admit_uploaded_hdfs_log(
    payload: bytes,
    *,
    object_store: ObjectStore,
    project_id: UUID,
    original_filename: str,
) -> tuple[dict[str, Any], AdmittedHdfsDataset | None]:
    """Validate uploaded HDFS bytes in process, then persist one object only if valid.

    Oversize, empty, non-UTF-8, or any non-matching line returns a report and puts nothing.
    """

    if len(payload) > MAX_HDFS_UPLOAD_BYTES:
        return (
            _hdfs_admission_report(
                valid=False,
                total_records=0,
                invalid_records=0,
                examples=[],
                issues=["HDFS log exceeds the 32 MiB size limit."],
            ),
            None,
        )
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return (
            _hdfs_admission_report(
                valid=False,
                total_records=0,
                invalid_records=0,
                examples=[],
                issues=["HDFS log dataset must be a readable UTF-8 text file."],
            ),
            None,
        )

    report = _hdfs_scan_report(text.splitlines())
    if not report["valid"]:
        return report, None

    dataset_id = uuid4()
    filename = _dataset_log_filename(original_filename)
    prefix = dataset_object_prefix(project_id, dataset_id)
    object_reference = dataset_object_key(project_id, dataset_id, filename)
    try:
        object_store.put(object_reference, payload)
    except Exception:
        object_store.delete_prefix(prefix)
        raise
    admitted = AdmittedHdfsDataset(
        dataset_id=dataset_id,
        object_reference=object_reference,
        checksum=hashlib.sha256(payload).hexdigest(),
    )
    return report, admitted


def validate_hdfs_log(log_reference: str, workspace_root: Path) -> tuple[str, dict[str, Any]]:
    """Read every stored log record and return an HDFS validation report."""
    log_path = _trusted_file(log_reference, workspace_root, "HDFS log dataset")
    try:
        with log_path.open("r", encoding="utf-8", errors="strict") as log_file:
            report = _hdfs_scan_report(line.rstrip("\r\n") for line in log_file)
    except (OSError, UnicodeDecodeError) as error:
        raise ValidationError("HDFS log dataset must be a readable UTF-8 text file.") from error
    report.pop("issues", None)
    return str(log_path.relative_to(workspace_root.resolve())), report


def _hdfs_scan_report(lines: Iterable[str]) -> dict[str, Any]:
    total_records = 0
    invalid_examples: list[dict[str, Any]] = []
    invalid_records = 0
    for line_number, raw_line in enumerate(lines, start=1):
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
    if total_records == 0:
        return _hdfs_admission_report(
            valid=False,
            total_records=0,
            invalid_records=0,
            examples=[{"line_number": 0, "reason": "Dataset contains no records."}],
            issues=["Dataset contains no records."],
        )
    return _hdfs_admission_report(
        valid=invalid_records == 0,
        total_records=total_records,
        invalid_records=invalid_records,
        examples=invalid_examples,
        issues=[str(example["reason"]) for example in invalid_examples],
    )


def _hdfs_admission_report(
    *,
    valid: bool,
    total_records: int,
    invalid_records: int,
    examples: list[dict[str, Any]],
    issues: list[str],
) -> dict[str, Any]:
    unique_issues: list[dict[str, str]] = []
    seen: set[str] = set()
    for reason in issues:
        if reason and reason not in seen:
            seen.add(reason)
            unique_issues.append({"reason": reason})
    return {
        "valid": valid,
        "total_records": total_records,
        "invalid_records": invalid_records,
        "examples": examples,
        "issues": unique_issues,
    }


def _dataset_log_filename(original_filename: str) -> str:
    segment = Path(str(original_filename or "").replace("\\", "/")).name
    candidate = _UNSAFE_FILENAME_CHARS.sub("_", segment).strip("_")
    if not candidate or candidate in {".", ".."}:
        return "hdfs.log"
    return candidate


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
