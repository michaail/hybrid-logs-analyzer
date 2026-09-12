"""Validated HTTP contracts for the HDFS-only API."""

from __future__ import annotations

import math
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from src.api.security import canonical_username


def _canonical_username(value: str) -> str:
    return canonical_username(value)


def _finite_number(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("must be a finite number")
    return value


CanonicalUsername = Annotated[str, AfterValidator(_canonical_username)]
"""A login identity validated against the canonical lowercase username contract."""

FiniteNumber = Annotated[float, AfterValidator(_finite_number)]
"""A JSON number that is not NaN or infinity."""


class ProjectRole(str, Enum):
    """Roles granted through a project membership."""

    OPERATOR = "operator"
    PUBLISHER = "publisher"


class ModelStatus(str, Enum):
    """A model version's allowed lifecycle states."""

    ELIGIBLE = "eligible"
    PUBLISHED = "published"


class AnalysisRunStatus(str, Enum):
    """Statuses exposed by the safe analysis-run foundation."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    NOT_SUPPORTED = "not_supported"


class StorageKind(str, Enum):
    """Kinded pointer for a stored model or dataset object."""

    WORKSPACE = "workspace"
    OBJECT = "object"


class ApiModel(BaseModel):
    """Base API contract that rejects unspecified request fields."""

    model_config = ConfigDict(extra="forbid")


class LoginRequest(ApiModel):
    """Credentials for an administrator-provisioned account."""

    username: CanonicalUsername
    password: str = Field(min_length=12, max_length=256)


class TokenResponse(ApiModel):
    """A bearer access token."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_seconds: int


class UserResponse(ApiModel):
    """A non-secret user record for the authenticated caller."""

    id: UUID
    username: str
    is_administrator: bool
    created_at: str


class AccountSummary(ApiModel):
    """Administrator-visible non-secret account lifecycle state."""

    id: UUID
    username: str
    is_active: bool
    created_at: str


class ProjectAccountCreate(ApiModel):
    """Administrator request to provision a project-authorized account atomically."""

    username: CanonicalUsername
    password: str = Field(min_length=12, max_length=256)
    project_id: UUID
    role: ProjectRole


class AccountActivationUpdate(ApiModel):
    """Administrator request to activate or deactivate a non-administrator account."""

    is_active: bool


class ProjectCreate(ApiModel):
    """Administrator request to create an isolation boundary."""

    name: str = Field(min_length=1, max_length=128)


class ProjectResponse(ApiModel):
    """Project visible to an authorized user."""

    id: UUID
    name: str
    created_at: str


class MembershipCreate(ApiModel):
    """Administrator request to grant project access to an existing account."""

    user_id: UUID
    role: ProjectRole


class MembershipRoleUpdate(ApiModel):
    """Administrator request to change an existing project membership role."""

    role: ProjectRole


class MembershipResponse(ApiModel):
    """A project membership with associated non-secret account state."""

    project_id: UUID
    user_id: UUID
    role: ProjectRole
    username: str
    is_active: bool


class ProjectAccountResponse(ApiModel):
    """Result of atomic project-account provisioning."""

    account: AccountSummary
    membership: MembershipResponse


class PreprocessingBundleIdentity(ApiModel):
    """Non-sensitive identity of a project-scoped preprocessing bundle."""

    identifier: str
    version: str
    digest: str


class ModelVersionResponse(ApiModel):
    """Traceable model version metadata; never exposes artifact contents."""

    id: UUID
    project_id: UUID
    model_identifier: str
    version: str
    source_compatibility: Literal["hdfs"]
    status: ModelStatus
    pipeline_run_id: str
    artifact_reference: str
    package_reference: str
    artifact_sha256: str
    metrics: dict[str, Any]
    metadata: dict[str, Any]
    external_evaluation_evidence: str
    created_at: str
    published_at: str | None
    published_by_user_id: UUID | None
    storage_kind: StorageKind
    checksum: str | None
    inference_ready: bool = False
    preprocessing_bundle: PreprocessingBundleIdentity | None = None


class DatasetResponse(ApiModel):
    """A project-owned reusable HDFS source pointer."""

    id: UUID
    project_id: UUID
    storage_kind: StorageKind
    object_reference: str
    checksum: str | None
    source_compatibility: Literal["hdfs"]
    created_at: str


class AnalysisRunCreate(ApiModel):
    """Operator request to start analysis of an admitted same-project dataset."""

    model_version_id: UUID
    dataset_id: UUID


class AnalysisRunResponse(ApiModel):
    """A durable analysis-run record and terminal validation outcome."""

    id: UUID
    project_id: UUID
    model_version_id: UUID
    requested_by_user_id: UUID
    source_compatibility: Literal["hdfs"]
    log_reference: str
    status: AnalysisRunStatus
    validation_report: dict[str, Any] | None
    error_code: str | None
    created_at: str
    completed_at: str | None
    dataset_id: UUID | None
    storage_kind: StorageKind | None
    checksum: str | None


class ResultSort(str, Enum):
    """Whitelisted keyset orders for HDFS anomaly result pages."""

    SCORE_DESC = "score_desc"
    BLOCK_ID_ASC = "block_id_asc"


class AnalysisResultsQuery(ApiModel):
    """Accepted result-page controls for a project-scoped HDFS run."""

    limit: int = Field(default=50, ge=1, le=100)
    sort: ResultSort = ResultSort.SCORE_DESC
    block_id_prefix: str | None = Field(default=None, min_length=1)
    min_score: FiniteNumber | None = None
    cursor: str | None = Field(default=None, min_length=1)


class HdfsSourceLine(ApiModel):
    """One stored raw log line retained as HDFS block evidence."""

    line_number: int | None
    raw: str


class HdfsAnomalyContext(ApiModel):
    """Bounded source evidence projected from a stored anomaly context."""

    matched_line_count: int = Field(default=0, ge=0)
    source_lines: list[HdfsSourceLine] = Field(default_factory=list)


class HdfsAnomalyResult(ApiModel):
    """One detected HDFS block anomaly with a compatibility record alias."""

    block_id: str
    record_reference: str
    anomaly_score: float | None = None
    anomaly_level: str | None = None
    decision_threshold: float | None = None
    context: HdfsAnomalyContext = Field(default_factory=HdfsAnomalyContext)

    @model_validator(mode="after")
    def _block_id_matches_record_reference(self) -> HdfsAnomalyResult:
        if self.block_id != self.record_reference:
            raise ValueError("block_id must equal record_reference")
        return self


class AnalysisResultSummary(ApiModel):
    """Run-wide outcome counts; independent of the current result page."""

    anomaly_count: int = Field(ge=0)
    normal_count: int = Field(ge=0)
    rejected_records: int = Field(ge=0)
    invalid_records: int = Field(ge=0)


class AnalysisResultTrace(ApiModel):
    """Same-project model, dataset, and bundle provenance for a result page."""

    model_identifier: str
    version: str
    model_version_id: UUID
    pipeline_run_id: str
    dataset_checksum: str | None = None
    artifact_checksum: str | None = None
    preprocessing_bundle: PreprocessingBundleIdentity | None = None


class AnalysisResultsResponse(ApiModel):
    """Typed, paginated HDFS anomaly result contract."""

    run: AnalysisRunResponse
    summary: AnalysisResultSummary
    trace: AnalysisResultTrace
    anomalies: list[HdfsAnomalyResult]
    next_cursor: str | None = None
    query: AnalysisResultsQuery


class AuditEventResponse(ApiModel):
    """An immutable record of a significant project-scoped action."""

    id: UUID
    actor_user_id: UUID | None
    project_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    details: dict[str, Any]
    created_at: str

