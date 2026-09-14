"""Row-to-schema mappers for the HDFS control-plane HTTP responses."""

from __future__ import annotations

import json
import math
from typing import Any
from uuid import UUID

from src.api.schemas import (
    AccountSummary,
    AnalysisResultSummary,
    AnalysisResultTrace,
    AnalysisRunResponse,
    AnalysisRunStatus,
    AuditEventResponse,
    DatasetResponse,
    HdfsAnomalyContext,
    HdfsAnomalyResult,
    HdfsProvisionalContext,
    HdfsProvisionalResult,
    HdfsSourceLine,
    MembershipResponse,
    ModelStatus,
    ModelVersionResponse,
    PreprocessingBundleIdentity,
    ProjectResponse,
    ProjectRole,
    UserResponse,
)

NOT_IN_REFERENCE_CATALOG_REASON = (
    "This block is not in the pinned reference catalog, so its anomaly decision is provisional."
)


def stored_results_summary(
    status: AnalysisRunStatus,
    validation_report: dict[str, Any],
    anomaly_count: int = 0,
) -> str:
    """Serialize a fallback results summary when a run stored none."""
    invalid_records = int(validation_report.get("invalid_records", 0))
    return json.dumps(
        {
            "anomaly_count": anomaly_count,
            "normal_count": 0,
            "rejected_records": invalid_records if status is AnalysisRunStatus.REJECTED else 0,
            "invalid_records": invalid_records,
        },
        sort_keys=True,
    )


def user_response(row: Any) -> UserResponse:
    """Map a stored user row to the public user schema."""
    return UserResponse(
        id=UUID(str(row["id"])),
        username=str(row["username"]),
        is_administrator=bool(row["is_administrator"]),
        created_at=str(row["created_at"]),
    )


def account_summary(row: Any) -> AccountSummary:
    """Map a stored user row to the administrator account summary."""
    return AccountSummary(
        id=UUID(str(row["id"])),
        username=str(row["username"]),
        is_active=bool(row["is_active"]),
        created_at=str(row["created_at"]),
    )


def project_response(row: Any) -> ProjectResponse:
    """Map a stored project row to the public project schema."""
    return ProjectResponse(
        id=UUID(str(row["id"])),
        name=str(row["name"]),
        created_at=str(row["created_at"]),
    )


def membership_response(row: Any) -> MembershipResponse:
    """Map a stored membership row to the public membership schema."""
    return MembershipResponse(
        project_id=UUID(str(row["project_id"])),
        user_id=UUID(str(row["user_id"])),
        role=ProjectRole(str(row["role"])),
        username=str(row["username"]),
        is_active=bool(row["is_active"]),
    )


def model_response(row: Any) -> ModelVersionResponse:
    """Map a stored model version row to the public model schema."""
    return ModelVersionResponse(
        id=UUID(str(row["id"])),
        project_id=UUID(str(row["project_id"])),
        model_identifier=str(row["model_identifier"]),
        version=str(row["version"]),
        source_compatibility="hdfs",
        status=ModelStatus(str(row["status"])),
        pipeline_run_id=str(row["pipeline_run_id"]),
        artifact_reference=str(row["artifact_reference"]),
        package_reference=str(row["package_reference"]),
        artifact_sha256=str(row["artifact_sha256"]),
        metrics=json.loads(str(row["metrics_json"])),
        metadata=json.loads(str(row["metadata_json"])),
        external_evaluation_evidence=str(row["external_evaluation_evidence"]),
        created_at=str(row["created_at"]),
        published_at=str(row["published_at"]) if row["published_at"] else None,
        published_by_user_id=(
            UUID(str(row["published_by_user_id"])) if row["published_by_user_id"] else None
        ),
        storage_kind=row["storage_kind"],
        checksum=str(row["checksum"]) if row["checksum"] else None,
        inference_ready=bool(row.get("preprocessing_bundle_id")),
        preprocessing_bundle=(
            PreprocessingBundleIdentity(
                identifier=str(row["preprocessing_bundle_identifier"]),
                version=str(row["preprocessing_bundle_version"]),
                digest=str(row["preprocessing_bundle_digest"]),
            )
            if row.get("preprocessing_bundle_identifier")
            else None
        ),
    )


def analysis_run_from_store(row: Any) -> AnalysisRunResponse:
    """Map a stored analysis-run row, including optional dataset identity."""
    dataset = None
    if row["dataset_storage_kind"] is not None:
        dataset = {
            "storage_kind": row["dataset_storage_kind"],
            "checksum": row["dataset_checksum"],
        }
    return analysis_run_response(row, dataset)


def analysis_run_response(row: Any, dataset: Any | None = None) -> AnalysisRunResponse:
    """Map a stored analysis-run row to the public run schema."""
    validation_report = row["validation_report_json"]
    return AnalysisRunResponse(
        id=UUID(str(row["id"])),
        project_id=UUID(str(row["project_id"])),
        model_version_id=UUID(str(row["model_version_id"])),
        requested_by_user_id=UUID(str(row["requested_by_user_id"])),
        source_compatibility="hdfs",
        log_reference=str(row["log_reference"]),
        status=AnalysisRunStatus(str(row["status"])),
        validation_report=json.loads(str(validation_report)) if validation_report else None,
        error_code=str(row["error_code"]) if row["error_code"] else None,
        created_at=str(row["created_at"]),
        completed_at=str(row["completed_at"]) if row["completed_at"] else None,
        dataset_id=UUID(str(row["dataset_id"])) if row["dataset_id"] else None,
        storage_kind=str(dataset["storage_kind"]) if dataset is not None else None,
        checksum=str(dataset["checksum"]) if dataset is not None and dataset["checksum"] else None,
    )


def dataset_response(row: Any) -> DatasetResponse:
    """Map a stored dataset row to the public dataset schema."""
    return DatasetResponse(
        id=UUID(str(row["id"])),
        project_id=UUID(str(row["project_id"])),
        storage_kind=str(row["storage_kind"]),
        object_reference=str(row["object_reference"]),
        checksum=str(row["checksum"]) if row["checksum"] else None,
        source_compatibility="hdfs",
        created_at=str(row["created_at"]),
    )


def anomaly_response(row: Any) -> HdfsAnomalyResult:
    """Map a stored anomaly result row to the public HDFS anomaly schema."""
    try:
        stored_context = json.loads(str(row["context_json"]))
    except json.JSONDecodeError:
        stored_context = {}
    block_id = str(row["record_reference"])
    level = row["anomaly_level"]
    context = hdfs_anomaly_context(stored_context)
    return HdfsAnomalyResult(
        block_id=block_id,
        record_reference=block_id,
        anomaly_score=optional_finite_float(row["anomaly_score"]),
        anomaly_level=str(level) if isinstance(level, str) else None,
        decision_threshold=optional_finite_float(row["decision_threshold"]),
        context=context,
    )


def provisional_response(row: Any) -> HdfsProvisionalResult:
    """Map a stored provisional result row to the public provisional schema."""
    try:
        stored_context = json.loads(str(row["context_json"]))
    except json.JSONDecodeError:
        stored_context = {}
    block_id = str(row["record_reference"])
    context = hdfs_provisional_context(stored_context)
    return HdfsProvisionalResult(
        block_id=block_id,
        record_reference=block_id,
        reason_code="not_in_reference_catalog",
        reason=NOT_IN_REFERENCE_CATALOG_REASON,
        context=context,
    )


def analysis_result_summary(run: Any, response: AnalysisRunResponse) -> AnalysisResultSummary:
    """Build the public results summary for one analysis run."""
    if run["results_summary_json"]:
        payload = json.loads(str(run["results_summary_json"]))
    else:
        payload = json.loads(
            stored_results_summary(response.status, response.validation_report or {}, 0)
        )
    if not isinstance(payload, dict):
        payload = {}
    payload["provisional_count"] = int(run["provisional_count"] or 0)
    payload["unassigned_context_line_count"] = int(run["unassigned_context_line_count"] or 0)
    return AnalysisResultSummary.model_validate(payload)


def analysis_result_trace(run: Any, model: Any) -> AnalysisResultTrace:
    """Build the public provenance trace for one analysis run."""
    artifact = model.get("artifact_sha256")
    dataset_checksum = run.get("dataset_checksum")
    policy = run.get("classification_policy")
    catalog_digest = run.get("classification_catalog_sha256")
    return AnalysisResultTrace(
        model_identifier=str(model["model_identifier"]),
        version=str(model["version"]),
        model_version_id=UUID(str(model["id"])),
        pipeline_run_id=str(model["pipeline_run_id"]),
        dataset_checksum=str(dataset_checksum) if dataset_checksum else None,
        artifact_checksum=str(artifact) if artifact else None,
        preprocessing_bundle=(
            PreprocessingBundleIdentity(
                identifier=str(model["preprocessing_bundle_identifier"]),
                version=str(model["preprocessing_bundle_version"]),
                digest=str(model["preprocessing_bundle_digest"]),
            )
            if model.get("preprocessing_bundle_identifier")
            else None
        ),
        classification_policy=str(policy) if policy else None,
        classification_catalog_sha256=str(catalog_digest) if catalog_digest else None,
    )


def hdfs_anomaly_context(value: Any) -> HdfsAnomalyContext:
    """Project stored JSON context onto the public HDFS anomaly context schema."""
    if not isinstance(value, dict):
        return HdfsAnomalyContext()
    matched = value.get("matched_line_count", 0)
    if not isinstance(matched, int) or isinstance(matched, bool) or matched < 0:
        matched = 0
    lines: list[HdfsSourceLine] = []
    raw_lines = value.get("source_lines")
    if isinstance(raw_lines, list):
        for item in raw_lines:
            projected = hdfs_source_line(item)
            if projected is not None:
                lines.append(projected)
    return HdfsAnomalyContext(matched_line_count=matched, source_lines=lines)


def hdfs_provisional_context(value: Any) -> HdfsProvisionalContext:
    """Project stored JSON context onto the public provisional context schema."""
    context = hdfs_anomaly_context(value)
    return HdfsProvisionalContext(
        matched_line_count=context.matched_line_count,
        source_lines=context.source_lines,
    )


def hdfs_source_line(item: Any) -> HdfsSourceLine | None:
    """Return a source line when the stored payload has a raw string."""
    if not isinstance(item, dict) or not isinstance(item.get("raw"), str):
        return None
    line_number = item.get("line_number")
    if line_number is not None and (
        not isinstance(line_number, int) or isinstance(line_number, bool)
    ):
        line_number = None
    return HdfsSourceLine(line_number=line_number, raw=str(item["raw"]))


def optional_finite_float(value: Any) -> float | None:
    """Coerce a stored numeric to a finite float, otherwise None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def audit_response(row: Any) -> AuditEventResponse:
    """Map a stored audit row to the public audit schema."""
    return AuditEventResponse(
        id=UUID(str(row["id"])),
        actor_user_id=UUID(str(row["actor_user_id"])) if row["actor_user_id"] else None,
        project_id=UUID(str(row["project_id"])) if row["project_id"] else None,
        action=str(row["action"]),
        resource_type=str(row["resource_type"]),
        resource_id=UUID(str(row["resource_id"])) if row["resource_id"] else None,
        details=json.loads(str(row["details_json"])),
        created_at=str(row["created_at"]),
    )
