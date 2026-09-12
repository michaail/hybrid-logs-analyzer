"""Frozen HDFS inference runner. This module is the only production Torch loader."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from src.api.object_store import ObjectStore
from src.api.storage import ApiDatabase, DatabaseRow, RunStatusConflict
from src.inference_service.errors import InferenceExecutionError
from src.inference_service.settings import DEFAULT_STALE_RUNNING_SECONDS
from src.modules.inference_bundle import (
    DRAIN_CONFIG_NAME,
    DRAIN_PARSER_NAME,
    EMBEDDINGS_NAME,
    bundle_digest,
)
from src.modules.model_package import MANIFEST_NAME, ModelPackageManifest, PackageArchitecture
from src.modules.parser.drain_parser import UnmatchedLogLine

logger = logging.getLogger(__name__)


def execute_analysis_run(
    run_id: UUID,
    database: ApiDatabase,
    object_store: ObjectStore,
    *,
    stale_running_seconds: int = DEFAULT_STALE_RUNNING_SECONDS,
) -> dict[str, Any]:
    """Claim a queued run, score it, and persist a terminal outcome."""

    job = database.get_inference_execution(run_id)
    if job is None:
        return {"found": False}
    status = str(job["status"])
    if status != "queued":
        if status == "running":
            _reclaim_stale_run(database, run_id, stale_running_seconds)
            current = database.get_analysis_run(run_id)
            if current is None:
                return {"found": False}
            return {"found": True, "status": str(current["status"]), "id": str(current["id"])}
        return {"found": True, "status": status, "id": str(job["id"])}
    try:
        database.transition_analysis_run(
            run_id,
            expected_status="queued",
            next_status="running",
            actor_user_id=None,
        )
    except RunStatusConflict:
        current = database.get_analysis_run(run_id)
        if current is None:
            return {"found": False}
        return {"found": True, "status": str(current["status"]), "id": str(current["id"])}
    try:
        summary, anomalies = _score_job(job, object_store)
        database.transition_analysis_run(
            run_id,
            expected_status="running",
            next_status="completed",
            actor_user_id=None,
            results_summary_json=json.dumps(summary, sort_keys=True),
            anomaly_results=anomalies,
        )
    except InferenceExecutionError as error:
        logger.exception(
            "Inference failed for run %s with code %s: %s",
            run_id,
            error.code,
            error.cause or error.public_message,
        )
        _fail_run(database, run_id, error)
    except Exception as error:
        logger.exception("Unexpected inference failure for run %s", run_id)
        _fail_run(
            database,
            run_id,
            InferenceExecutionError("INFERENCE_FAILED", cause=type(error).__name__),
        )
    current = database.get_analysis_run(run_id)
    if current is None:
        return {"found": False}
    return {"found": True, "status": str(current["status"]), "id": str(current["id"])}


def _fail_run(database: ApiDatabase, run_id: UUID, error: InferenceExecutionError) -> None:
    report = json.dumps({"execution": error.public_message}, sort_keys=True)
    try:
        database.transition_analysis_run(
            run_id,
            expected_status="running",
            next_status="failed",
            actor_user_id=None,
            error_code=error.code,
            validation_report_json=report,
        )
    except RunStatusConflict:
        logger.warning("Could not mark run %s as failed after %s", run_id, error.code)


def reclaim_stale_running_runs(
    database: ApiDatabase,
    *,
    stale_running_seconds: int = DEFAULT_STALE_RUNNING_SECONDS,
) -> int:
    """Fail running claims whose analysis.running audit is older than the threshold."""

    reclaimed = 0
    for run_id in database.list_running_analysis_run_ids():
        if _reclaim_stale_run(database, run_id, stale_running_seconds):
            reclaimed += 1
    return reclaimed


def _reclaim_stale_run(
    database: ApiDatabase,
    run_id: UUID,
    stale_running_seconds: int,
) -> bool:
    if not _is_stale_running(database, run_id, stale_running_seconds):
        return False
    logger.warning("Reclaiming stale running analysis run %s", run_id)
    _fail_run(
        database,
        run_id,
        InferenceExecutionError("INFERENCE_FAILED", cause="stale running claim"),
    )
    return True


def _is_stale_running(
    database: ApiDatabase,
    run_id: UUID,
    stale_running_seconds: int,
) -> bool:
    started_at = database.latest_analysis_running_at(run_id)
    if started_at is None:
        return True
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - started.astimezone(timezone.utc)
    return age >= timedelta(seconds=stale_running_seconds)


def _score_job(
    job: DatabaseRow,
    object_store: ObjectStore,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if str(job.get("model_status")) != "published":
        raise InferenceExecutionError("INFERENCE_FAILED", cause="model is not published")
    bundle_prefix = job.get("bundle_object_prefix")
    if not bundle_prefix:
        raise InferenceExecutionError(
            "PREPROCESSING_BUNDLE_UNAVAILABLE",
            cause="model has no bound preprocessing bundle",
        )
    dataset_key = job.get("dataset_object_reference")
    if not dataset_key:
        raise InferenceExecutionError("INFERENCE_FAILED", cause="run has no dataset")

    with tempfile.TemporaryDirectory(prefix="hdfs-inference-") as tmp:
        root = Path(tmp)
        package_dir = root / "package"
        bundle_dir = root / "bundle"
        package_dir.mkdir()
        bundle_dir.mkdir()
        package_ref = str(job["model_package_reference"])
        try:
            _materialize_prefix(object_store, package_ref, package_dir, (MANIFEST_NAME,))
            manifest = _load_package_manifest(package_dir)
            _verify_persisted_model_binding(job, manifest)
            _materialize_prefix(
                object_store,
                package_ref,
                package_dir,
                (manifest.files.artifact, manifest.files.evidence),
            )
        except InferenceExecutionError:
            raise
        except (FileNotFoundError, ValueError) as error:
            raise InferenceExecutionError("MODEL_LOAD_FAILED", cause=type(error).__name__) from error
        try:
            _materialize_prefix(
                object_store,
                str(bundle_prefix),
                bundle_dir,
                (MANIFEST_NAME, DRAIN_CONFIG_NAME, DRAIN_PARSER_NAME, EMBEDDINGS_NAME),
            )
        except (FileNotFoundError, ValueError) as error:
            raise InferenceExecutionError(
                "PREPROCESSING_BUNDLE_UNAVAILABLE",
                cause=type(error).__name__,
            ) from error
        try:
            log_bytes = object_store.get(str(dataset_key))
        except (FileNotFoundError, ValueError) as error:
            raise InferenceExecutionError("INFERENCE_FAILED", cause=type(error).__name__) from error
        dataset_checksum = str(job.get("dataset_checksum") or "")
        if hashlib.sha256(log_bytes).hexdigest() != dataset_checksum:
            raise InferenceExecutionError(
                "INFERENCE_FAILED",
                cause="dataset checksum mismatch",
            )
        log_path = root / "dataset.log"
        log_path.write_bytes(log_bytes)
        _verify_package_checksums(package_dir, manifest)
        _verify_bundle_checksums(bundle_dir, str(job["bundle_manifest_checksum"]))
        artifact = package_dir / manifest.files.artifact
        _verify_artifact_checksum(artifact, str(job["model_artifact_sha256"]))
        try:
            return _infer_from_materialized(manifest, bundle_dir, log_path, artifact)
        except InferenceExecutionError:
            raise
        except UnmatchedLogLine as error:
            raise InferenceExecutionError(
                "UNMATCHED_TEMPLATE",
                cause=f"line {error.line_number}",
            ) from error
        except Exception as error:
            from src.modules.dataset import MissingClusterEmbedding

            if isinstance(error, MissingClusterEmbedding):
                raise InferenceExecutionError(
                    "MISSING_CLUSTER_EMBEDDING",
                    cause=str(error.cluster_id),
                ) from error
            raise


def _infer_from_materialized(
    manifest: ModelPackageManifest,
    bundle_dir: Path,
    log_path: Path,
    artifact: Path,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    from src.modules.dataset import MissingClusterEmbedding
    from src.modules.hdfs_inference import HdfsInferenceError, score_frozen_hdfs_log

    try:
        result = score_frozen_hdfs_log(
            manifest=manifest,
            bundle_dir=bundle_dir,
            log_path=log_path,
            artifact_path=artifact,
        )
    except UnmatchedLogLine:
        raise
    except MissingClusterEmbedding:
        raise
    except HdfsInferenceError as error:
        raise InferenceExecutionError(error.code, cause=error.cause) from error
    except Exception as error:
        raise InferenceExecutionError("INFERENCE_FAILED", cause=type(error).__name__) from error

    anomalies = [
        {
            "record_reference": block.block_id,
            "anomaly_score": block.score,
            "anomaly_level": "anomaly",
            "decision_threshold": result.threshold,
            "context": {
                "matched_line_count": block.matched_line_count,
                "source_lines": [
                    {"line_number": line.line_number, "raw": line.raw} for line in block.source_lines
                ],
            },
        }
        for block in result.blocks
        if block.decision
    ]
    return (
        {
            "anomaly_count": len(anomalies),
            "normal_count": len(result.blocks) - len(anomalies),
            "rejected_records": 0,
            "invalid_records": 0,
        },
        anomalies,
    )


def _materialize_prefix(
    object_store: ObjectStore,
    prefix: str,
    destination: Path,
    relatives: tuple[str, ...],
) -> None:
    for relative in relatives:
        payload = object_store.get(f"{prefix}/{relative}")
        target = destination / relative
        target.write_bytes(payload)


def _load_package_manifest(package_dir: Path) -> ModelPackageManifest:
    try:
        payload = json.loads((package_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
        return ModelPackageManifest.model_validate(payload)
    except Exception as error:
        raise InferenceExecutionError("MODEL_LOAD_FAILED", cause=type(error).__name__) from error


def _verify_package_checksums(package_dir: Path, manifest: ModelPackageManifest) -> None:
    for relative, expected in manifest.files.checksums.items():
        path = package_dir / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise InferenceExecutionError(
                "MODEL_LOAD_FAILED",
                cause=f"checksum mismatch for {relative}",
            )


def _verify_persisted_model_binding(job: DatabaseRow, manifest: ModelPackageManifest) -> None:
    """Ensure inference-relevant manifest fields match the admitted database record."""

    try:
        package_reference = str(job["model_package_reference"]).rstrip("/")
        artifact_reference = str(job["model_artifact_reference"])
        expected_artifact = artifact_reference.removeprefix(f"{package_reference}/")
        metadata = json.loads(str(job["model_metadata_json"]))
        metrics = json.loads(str(job["model_metrics_json"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise InferenceExecutionError("MODEL_LOAD_FAILED", cause="invalid persisted model metadata") from error
    if not isinstance(metadata, dict) or not isinstance(metrics, dict):
        raise InferenceExecutionError("MODEL_LOAD_FAILED", cause="invalid persisted model metadata")
    try:
        persisted_architecture = PackageArchitecture.model_validate(
            metadata.get("architecture")
        ).model_dump()
    except Exception as error:
        raise InferenceExecutionError(
            "MODEL_LOAD_FAILED", cause="invalid persisted model architecture"
        ) from error

    expected_bundle = {
        "identifier": str(job.get("bundle_identifier") or ""),
        "version": str(job.get("bundle_version") or ""),
        "digest": str(job.get("bundle_manifest_checksum") or ""),
    }
    actual_bundle = (
        manifest.preprocessing_bundle.model_dump() if manifest.preprocessing_bundle is not None else None
    )
    if (
        expected_artifact == artifact_reference
        or manifest.files.artifact != expected_artifact
        or manifest.format != metadata.get("format")
        or manifest.architecture.model_dump() != persisted_architecture
        or manifest.scoring.model_dump() != metadata.get("scoring")
        or manifest.metrics.model_dump() != metrics
        or actual_bundle != expected_bundle
    ):
        raise InferenceExecutionError("MODEL_LOAD_FAILED", cause="manifest differs from admitted metadata")


def _verify_artifact_checksum(artifact: Path, expected_checksum: str) -> None:
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected_checksum:
        raise InferenceExecutionError("MODEL_LOAD_FAILED", cause="artifact differs from admitted checksum")


def _verify_bundle_checksums(bundle_dir: Path, expected_digest: str) -> None:
    try:
        payload = json.loads((bundle_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
        checksums = payload["files"]["checksums"]
        for relative, expected in checksums.items():
            path = bundle_dir / relative
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise InferenceExecutionError(
                    "PREPROCESSING_BUNDLE_UNAVAILABLE",
                    cause=f"checksum mismatch for {relative}",
                )
        actual_digest = bundle_digest(checksums)
        if actual_digest != expected_digest or actual_digest != payload.get("digest"):
            raise InferenceExecutionError(
                "PREPROCESSING_BUNDLE_UNAVAILABLE",
                cause="bundle digest mismatch",
            )
    except InferenceExecutionError:
        raise
    except Exception as error:
        raise InferenceExecutionError(
            "PREPROCESSING_BUNDLE_UNAVAILABLE",
            cause=type(error).__name__,
        ) from error
