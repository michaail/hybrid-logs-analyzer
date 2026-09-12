"""FastAPI application factory for the HDFS anomaly-detection MVP."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.api.schemas import (
    AccountActivationUpdate,
    AccountSummary,
    AnalysisResultSummary,
    AnalysisResultTrace,
    AnalysisResultsQuery,
    AnalysisResultsResponse,
    AnalysisRunCreate,
    AnalysisRunResponse,
    AnalysisRunStatus,
    AuditEventResponse,
    DatasetResponse,
    HdfsAnomalyContext,
    HdfsAnomalyResult,
    HdfsSourceLine,
    LoginRequest,
    MembershipCreate,
    MembershipResponse,
    MembershipRoleUpdate,
    ModelStatus,
    ModelVersionResponse,
    PreprocessingBundleIdentity,
    ProjectAccountCreate,
    ProjectAccountResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectRole,
    TokenResponse,
    UserResponse,
)
from src.api.inference_dispatch import dispatch_analysis_run
from src.api.object_store import build_object_store, dataset_object_prefix
from src.api.security import create_access_token, decode_access_token, hash_password, verify_password
from src.api.settings import ApiSettings
from src.api.storage import AnomalyResultPageQuery, ApiDatabase, DatabaseIntegrityError, ResultCursorError
from src.api.validation import (
    MAX_HDFS_UPLOAD_BYTES,
    ValidationError,
    ValidatorUnavailableError,
    admit_uploaded_hdfs_log,
    admit_uploaded_zip_package,
)
from src.modules.model_package import MAX_ZIP_COMPRESSED_BYTES


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated user identity available to a request."""

    id: UUID
    username: str
    is_administrator: bool


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Create a configured FastAPI app without importing legacy ML loaders."""
    resolved_settings = settings or ApiSettings.from_environment()
    database = ApiDatabase(resolved_settings.database_url)
    object_store = build_object_store(resolved_settings)
    bearer = HTTPBearer(auto_error=False)

    def get_current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> CurrentUser:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized()
        user_id = decode_access_token(credentials.credentials, resolved_settings)
        if user_id is None:
            raise _unauthorized()
        user = database.get_user_by_id(user_id)
        if user is None or not bool(user["is_active"]):
            raise _unauthorized()
        return CurrentUser(
            id=UUID(str(user["id"])),
            username=str(user["username"]),
            is_administrator=bool(user["is_administrator"]),
        )

    def require_administrator(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.is_administrator:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required.")
        return user

    def require_project_access(project_id: UUID, user: CurrentUser) -> ProjectRole | None:
        if user.is_administrator:
            if database.get_project(project_id) is None:
                raise _not_found("Project")
            return None
        membership = database.get_membership(project_id, user.id)
        if membership is None:
            raise _not_found("Project")
        return ProjectRole(str(membership["role"]))

    def require_project_role(
        project_id: UUID,
        user: CurrentUser,
        allowed_roles: set[ProjectRole],
    ) -> None:
        role = require_project_access(project_id, user)
        if role is None:
            return
        if role is ProjectRole.PUBLISHER and ProjectRole.OPERATOR in allowed_roles:
            return
        if role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient project role.")

    def _dispatch_queued_run(run_id: UUID) -> None:
        dispatch_analysis_run(run_id, resolved_settings)

    app = FastAPI(
        title="HDFS Anomaly Detection API",
        version="0.1.0",
        description=(
            "HDFS-only model registration and analysis-run API. "
            "It never deserializes uploaded model artifacts."
        ),
    )
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Return a non-sensitive readiness result only when the database is reachable."""
        if not database.healthcheck():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database is unavailable.",
            )
        return {"status": "ok"}

    @app.post("/auth/token", response_model=TokenResponse, tags=["authentication"])
    def login(credentials: LoginRequest) -> TokenResponse:
        """Authenticate a provisioned account and issue a signed bearer token."""
        user = database.get_user_by_username(credentials.username)
        if (
            user is None
            or not bool(user["is_active"])
            or not verify_password(credentials.password, str(user["password_hash"]))
        ):
            raise _unauthorized()
        user_id = UUID(str(user["id"]))
        database.add_audit_event(
            actor_user_id=user_id,
            project_id=None,
            action="user.signed_in",
            resource_type="user",
            resource_id=user_id,
            details_json=json.dumps({"username": str(user["username"])}, sort_keys=True),
        )
        return TokenResponse(
            access_token=create_access_token(user_id, resolved_settings),
            expires_in_seconds=resolved_settings.jwt_ttl_minutes * 60,
        )

    @app.get("/users/me", response_model=UserResponse, tags=["users"])
    def get_me(user: CurrentUser = Depends(get_current_user)) -> UserResponse:
        """Return the identity represented by the bearer token."""
        stored_user = database.get_user_by_id(user.id)
        if stored_user is None:
            raise _unauthorized()
        return _user_response(stored_user)

    @app.post(
        "/admin/project-accounts",
        response_model=ProjectAccountResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["administration"],
    )
    def provision_project_account(
        request: ProjectAccountCreate,
        administrator: CurrentUser = Depends(require_administrator),
    ) -> ProjectAccountResponse:
        """Create a non-administrator account and its initial project membership atomically."""
        if database.get_project(request.project_id) is None:
            raise _not_found("Project")
        try:
            created_user, membership = database.provision_project_account(
                username=request.username,
                password_hash=hash_password(request.password),
                project_id=request.project_id,
                role=request.role.value,
                actor_user_id=administrator.id,
            )
        except DatabaseIntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username is already provisioned.",
            ) from None
        return ProjectAccountResponse(
            account=_account_summary(created_user),
            membership=_membership_response(membership),
        )

    @app.get("/admin/users", response_model=list[AccountSummary], tags=["administration"])
    def list_users(administrator: CurrentUser = Depends(require_administrator)) -> list[AccountSummary]:
        """List provisioned accounts and their active state for Administrator oversight."""
        del administrator
        return [_account_summary(user) for user in database.list_users()]

    @app.patch(
        "/admin/users/{user_id}/activation",
        response_model=AccountSummary,
        tags=["administration"],
    )
    def set_user_activation(
        user_id: UUID,
        request: AccountActivationUpdate,
        administrator: CurrentUser = Depends(require_administrator),
    ) -> AccountSummary:
        """Activate or deactivate a non-administrator account."""
        if database.get_user_by_id(user_id) is None:
            raise _not_found("User")
        try:
            updated = database.set_user_active(
                user_id=user_id,
                is_active=request.is_active,
                actor_user_id=administrator.id,
            )
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None
        if updated is None:
            raise _not_found("User")
        return _account_summary(updated)

    @app.get(
        "/admin/audit-events",
        response_model=list[AuditEventResponse],
        tags=["administration"],
    )
    def list_system_audit_events(
        administrator: CurrentUser = Depends(require_administrator),
    ) -> list[AuditEventResponse]:
        """Return Administrator-visible user-resource audit events across the system."""
        del administrator
        return [_audit_response(event) for event in database.list_user_audit_events()]

    @app.get("/projects", response_model=list[ProjectResponse], tags=["projects"])
    def list_projects(user: CurrentUser = Depends(get_current_user)) -> list[ProjectResponse]:
        """List projects visible through the caller's membership or administration role."""
        return [
            _project_response(project)
            for project in database.list_projects_for_user(user.id, user.is_administrator)
        ]

    @app.post(
        "/projects",
        response_model=ProjectResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["projects"],
    )
    def create_project(
        request: ProjectCreate,
        administrator: CurrentUser = Depends(require_administrator),
    ) -> ProjectResponse:
        """Create a project isolation boundary."""
        try:
            project = database.create_project_with_audit(
                name=request.name,
                actor_user_id=administrator.id,
            )
        except DatabaseIntegrityError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project name already exists.") from None
        return _project_response(project)

    @app.post(
        "/projects/{project_id}/members",
        response_model=MembershipResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["projects"],
    )
    def grant_project_membership(
        project_id: UUID,
        request: MembershipCreate,
        administrator: CurrentUser = Depends(require_administrator),
    ) -> MembershipResponse:
        """Grant project access to an existing account; duplicates are rejected."""
        if database.get_project(project_id) is None or database.get_user_by_id(request.user_id) is None:
            raise _not_found("Project or user")
        try:
            membership = database.create_membership(
                project_id=project_id,
                user_id=request.user_id,
                role=request.role.value,
                actor_user_id=administrator.id,
            )
        except DatabaseIntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Membership already exists for this project and user.",
            ) from None
        return _membership_response(membership)

    @app.patch(
        "/projects/{project_id}/members/{user_id}",
        response_model=MembershipResponse,
        tags=["projects"],
    )
    def update_project_membership_role(
        project_id: UUID,
        user_id: UUID,
        request: MembershipRoleUpdate,
        administrator: CurrentUser = Depends(require_administrator),
    ) -> MembershipResponse:
        """Change the role of an existing project membership."""
        if database.get_project(project_id) is None:
            raise _not_found("Project")
        try:
            membership = database.update_membership_role(
                project_id=project_id,
                user_id=user_id,
                role=request.role.value,
                actor_user_id=administrator.id,
            )
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None
        if membership is None:
            raise _not_found("Membership")
        return _membership_response(membership)

    @app.delete(
        "/projects/{project_id}/members/{user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        tags=["projects"],
    )
    def revoke_project_membership(
        project_id: UUID,
        user_id: UUID,
        administrator: CurrentUser = Depends(require_administrator),
    ) -> Response:
        """Revoke an existing project membership while preserving audit history."""
        if database.get_project(project_id) is None:
            raise _not_found("Project")
        revoked = database.revoke_membership(
            project_id=project_id,
            user_id=user_id,
            actor_user_id=administrator.id,
        )
        if not revoked:
            raise _not_found("Membership")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/projects/{project_id}/members",
        response_model=list[MembershipResponse],
        tags=["projects"],
    )
    def list_project_memberships(
        project_id: UUID,
        administrator: CurrentUser = Depends(require_administrator),
    ) -> list[MembershipResponse]:
        """List memberships for one project to support Administrator oversight."""
        del administrator
        if database.get_project(project_id) is None:
            raise _not_found("Project")
        return [_membership_response(item) for item in database.list_memberships(project_id)]

    @app.get(
        "/projects/{project_id}/models",
        response_model=list[ModelVersionResponse],
        tags=["models"],
    )
    def list_model_versions(
        project_id: UUID,
        user: CurrentUser = Depends(get_current_user),
    ) -> list[ModelVersionResponse]:
        """List only model versions within an authorized project."""
        require_project_access(project_id, user)
        return [_model_response(item) for item in database.list_model_versions(project_id)]

    @app.post(
        "/projects/{project_id}/models",
        response_model=ModelVersionResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["models"],
    )
    def register_model_version(
        project_id: UUID,
        user: CurrentUser = Depends(get_current_user),
        package: UploadFile = File(..., description="Complete HDFS model package ZIP"),
        preprocessing_bundle: UploadFile | None = File(
            default=None,
            description="Companion preprocessing-bundle ZIP required for v2 packages",
        ),
    ) -> ModelVersionResponse:
        """Admit a Publisher ZIP upload. Never loads the artifact in this process."""
        require_project_role(project_id, user, {ProjectRole.PUBLISHER})
        archive_bytes = package.file.read(MAX_ZIP_COMPRESSED_BYTES + 1)
        bundle_bytes = None
        if preprocessing_bundle is not None:
            bundle_bytes = preprocessing_bundle.file.read(MAX_ZIP_COMPRESSED_BYTES + 1)
        try:
            report, admitted = admit_uploaded_zip_package(
                archive_bytes,
                settings=resolved_settings,
                object_store=object_store,
                project_id=project_id,
                preprocessing_bundle_bytes=bundle_bytes,
            )
        except ValidatorUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from None
        except ValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"valid": False, "issues": [{"path": "package", "reason": str(error)}]},
            ) from None
        if not report.valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=report.model_dump(),
            )
        if admitted is None or admitted.model_id is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Model package validator is unavailable.",
            )
        try:
            model = database.create_model_version(
                project_id=project_id,
                model_identifier=admitted.model_identifier,
                version=admitted.version,
                pipeline_run_id=admitted.pipeline_run_id,
                artifact_reference=admitted.artifact_reference,
                package_reference=admitted.package_reference,
                artifact_sha256=admitted.artifact_sha256,
                metrics_json=json.dumps(admitted.metrics, sort_keys=True),
                metadata_json=json.dumps(admitted.metadata, sort_keys=True),
                external_evaluation_evidence=admitted.external_evaluation_evidence,
                storage_kind=admitted.storage_kind,
                checksum=admitted.artifact_sha256,
                actor_user_id=user.id,
                model_id=admitted.model_id,
                preprocessing_bundle=(
                    {
                        "id": str(admitted.preprocessing_bundle.bundle_id),
                        "identifier": admitted.preprocessing_bundle.identifier,
                        "version": admitted.preprocessing_bundle.version,
                        "object_prefix": admitted.preprocessing_bundle.object_prefix,
                        "manifest_checksum": admitted.preprocessing_bundle.manifest_checksum,
                        "metadata_json": json.dumps(
                            admitted.preprocessing_bundle.metadata, sort_keys=True
                        ),
                    }
                    if admitted.preprocessing_bundle is not None
                    else None
                ),
            )
        except DatabaseIntegrityError:
            object_store.delete_prefix(admitted.package_reference)
            if admitted.preprocessing_bundle is not None:
                object_store.delete_prefix(admitted.preprocessing_bundle.object_prefix)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This model identifier and version already exists in the project.",
            ) from None
        return _model_response(model)

    @app.get(
        "/projects/{project_id}/models/{model_version_id}",
        response_model=ModelVersionResponse,
        tags=["models"],
    )
    def get_model_version(
        project_id: UUID,
        model_version_id: UUID,
        user: CurrentUser = Depends(get_current_user),
    ) -> ModelVersionResponse:
        """Get a model only after checking caller access to the requested project."""
        require_project_access(project_id, user)
        model = database.get_model_version(model_version_id)
        if model is None or model["project_id"] != str(project_id):
            raise _not_found("Model version")
        return _model_response(model)

    @app.post(
        "/projects/{project_id}/models/{model_version_id}/publish",
        response_model=ModelVersionResponse,
        tags=["models"],
    )
    def publish_model_version(
        project_id: UUID,
        model_version_id: UUID,
        user: CurrentUser = Depends(get_current_user),
    ) -> ModelVersionResponse:
        """Explicitly publish an eligible model within its authorized project."""
        require_project_role(project_id, user, {ProjectRole.PUBLISHER})
        model = database.get_model_version(model_version_id)
        if model is None or model["project_id"] != str(project_id):
            raise _not_found("Model version")
        if model["status"] != ModelStatus.ELIGIBLE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only eligible model versions can be published.",
            )
        try:
            published_model = database.publish_model_version(
                model_version_id,
                user.id,
                actor_user_id=user.id,
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only eligible model versions can be published.",
            ) from None
        return _model_response(published_model)

    @app.get(
        "/projects/{project_id}/analysis-runs",
        response_model=list[AnalysisRunResponse],
        tags=["analysis"],
    )
    def list_analysis_runs(
        project_id: UUID,
        user: CurrentUser = Depends(get_current_user),
    ) -> list[AnalysisRunResponse]:
        """List analysis runs scoped to an authorized project."""
        require_project_role(project_id, user, {ProjectRole.OPERATOR})
        return [_analysis_run_from_store(item) for item in database.list_analysis_runs(project_id)]

    @app.post(
        "/projects/{project_id}/analysis-runs",
        response_model=AnalysisRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["analysis"],
    )
    def create_analysis_run(
        project_id: UUID,
        request: AnalysisRunCreate,
        background_tasks: BackgroundTasks,
        user: CurrentUser = Depends(get_current_user),
    ) -> AnalysisRunResponse:
        """Queue analysis of an admitted same-project dataset without re-scanning the log."""
        require_project_role(project_id, user, {ProjectRole.OPERATOR})
        model = database.get_model_version(request.model_version_id)
        if model is None or model["project_id"] != str(project_id):
            raise _not_found("Model version")
        if model["status"] != ModelStatus.PUBLISHED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only published model versions can start analysis.",
            )
        if not model.get("preprocessing_bundle_id"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Published model is not inference-ready.",
            )
        dataset = database.get_dataset(request.dataset_id)
        if dataset is None or dataset["project_id"] != str(project_id):
            raise _not_found("Dataset")

        run = database.create_analysis_run(
            project_id=project_id,
            model_version_id=request.model_version_id,
            requested_by_user_id=user.id,
            log_reference=str(dataset["object_reference"]),
            status=AnalysisRunStatus.QUEUED.value,
            validation_report_json=None,
            error_code=None,
            completed_at=None,
            actor_user_id=user.id,
            results_summary_json=None,
            dataset_id=request.dataset_id,
        )
        background_tasks.add_task(_dispatch_queued_run, UUID(str(run["id"])))
        return _analysis_run_from_store(run)

    @app.get(
        "/projects/{project_id}/analysis-runs/{analysis_run_id}",
        response_model=AnalysisRunResponse,
        tags=["analysis"],
    )
    def get_analysis_run(
        project_id: UUID,
        analysis_run_id: UUID,
        user: CurrentUser = Depends(get_current_user),
    ) -> AnalysisRunResponse:
        """Get a single project-scoped analysis run."""
        require_project_role(project_id, user, {ProjectRole.OPERATOR})
        run = database.get_analysis_run(analysis_run_id)
        if run is None or run["project_id"] != str(project_id):
            raise _not_found("Analysis run")
        return _analysis_run_from_store(run)

    @app.get(
        "/projects/{project_id}/analysis-runs/{analysis_run_id}/results",
        response_model=AnalysisResultsResponse,
        tags=["analysis"],
    )
    def get_analysis_results(
        project_id: UUID,
        analysis_run_id: UUID,
        results_query: Annotated[AnalysisResultsQuery, Query()],
        user: CurrentUser = Depends(get_current_user),
    ) -> AnalysisResultsResponse:
        """Return one typed page of HDFS anomalies without executing untrusted models."""
        require_project_role(project_id, user, {ProjectRole.OPERATOR})
        run = database.get_analysis_run(analysis_run_id)
        if run is None or run["project_id"] != str(project_id):
            raise _not_found("Analysis run")
        model = database.get_model_version(UUID(str(run["model_version_id"])))
        if model is None or str(model["project_id"]) != str(project_id):
            raise _not_found("Analysis run")
        response = _analysis_run_from_store(run)
        try:
            page = database.list_anomaly_result_page(
                analysis_run_id,
                AnomalyResultPageQuery(
                    limit=results_query.limit,
                    sort=results_query.sort.value,
                    block_id_prefix=results_query.block_id_prefix,
                    min_score=results_query.min_score,
                    cursor=results_query.cursor,
                ),
            )
        except ResultCursorError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Result cursor is invalid.",
            ) from None
        return AnalysisResultsResponse(
            run=response,
            summary=_analysis_result_summary(run, response),
            trace=_analysis_result_trace(run, model),
            anomalies=[_anomaly_response(item) for item in page.rows],
            next_cursor=page.next_cursor,
            query=results_query,
        )

    @app.get(
        "/projects/{project_id}/datasets",
        response_model=list[DatasetResponse],
        tags=["datasets"],
    )
    def list_datasets(
        project_id: UUID,
        user: CurrentUser = Depends(get_current_user),
    ) -> list[DatasetResponse]:
        """List reusable HDFS sources owned by an authorized project."""
        require_project_role(project_id, user, {ProjectRole.OPERATOR})
        return [_dataset_response(item) for item in database.list_datasets(project_id)]

    @app.post(
        "/projects/{project_id}/datasets",
        response_model=DatasetResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["datasets"],
    )
    def upload_dataset(
        project_id: UUID,
        user: CurrentUser = Depends(get_current_user),
        log: UploadFile = File(..., description="UTF-8 HDFS log dataset"),
    ) -> DatasetResponse:
        """Admit an Operator HDFS log upload. Persist an object only when the whole file is valid."""
        require_project_role(project_id, user, {ProjectRole.OPERATOR})
        payload = log.file.read(MAX_HDFS_UPLOAD_BYTES + 1)
        report, admitted = admit_uploaded_hdfs_log(
            payload,
            object_store=object_store,
            project_id=project_id,
            original_filename=log.filename or "",
        )
        if not report["valid"] or admitted is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=report,
            )
        try:
            dataset = database.create_dataset(
                project_id=project_id,
                storage_kind=admitted.storage_kind,
                object_reference=admitted.object_reference,
                checksum=admitted.checksum,
                actor_user_id=user.id,
                dataset_id=admitted.dataset_id,
            )
        except DatabaseIntegrityError:
            object_store.delete_prefix(dataset_object_prefix(project_id, admitted.dataset_id))
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This dataset object already exists in the project.",
            ) from None
        return _dataset_response(dataset)

    @app.get(
        "/projects/{project_id}/datasets/{dataset_id}",
        response_model=DatasetResponse,
        tags=["datasets"],
    )
    def get_dataset(
        project_id: UUID,
        dataset_id: UUID,
        user: CurrentUser = Depends(get_current_user),
    ) -> DatasetResponse:
        """Get a single project-owned dataset pointer."""
        require_project_role(project_id, user, {ProjectRole.OPERATOR})
        dataset = database.get_dataset(dataset_id)
        if dataset is None or dataset["project_id"] != str(project_id):
            raise _not_found("Dataset")
        return _dataset_response(dataset)

    @app.get(
        "/projects/{project_id}/audit-events",
        response_model=list[AuditEventResponse],
        tags=["administration"],
    )
    def list_audit_events(
        project_id: UUID,
        administrator: CurrentUser = Depends(require_administrator),
    ) -> list[AuditEventResponse]:
        """Return immutable audit records for Administrator review."""
        del administrator
        if database.get_project(project_id) is None:
            raise _not_found("Project")
        return [_audit_response(event) for event in database.list_audit_events(project_id)]

    _mount_frontend(app)
    return app


def _stored_results_summary(
    status: AnalysisRunStatus,
    validation_report: dict[str, Any],
    anomaly_count: int = 0,
) -> str:
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


def _mount_frontend(app: FastAPI) -> None:
    """Serve the compiled React client when it is included in the deployed image."""
    frontend_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    assets_dir = frontend_dir / "assets"
    if not frontend_dir.is_dir() or not assets_dir.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{requested_path:path}", include_in_schema=False)
    def serve_frontend(requested_path: str) -> FileResponse:
        """Return static assets or the SPA entry point without masking API 404 responses."""
        if requested_path.startswith(("admin/", "auth/", "health", "projects/", "users/")):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource was not found.")
        requested_file = (frontend_dir / requested_path).resolve()
        try:
            requested_file.relative_to(frontend_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource was not found.") from None
        if requested_path and requested_file.is_file():
            return FileResponse(requested_file)
        return FileResponse(frontend_dir / "index.html", media_type="text/html")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply browser protections without breaking FastAPI's interactive documentation."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=()",
        )
        if request.url.path not in {"/docs", "/openapi.json", "/redoc"}:
            response.headers.setdefault(
                "Content-Security-Policy",
                "base-uri 'self'; connect-src 'self'; default-src 'self'; form-action 'self'; "
                "frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; "
                "script-src 'self'; style-src 'self'",
            )
        return response


def _user_response(row: Any) -> UserResponse:
    return UserResponse(
        id=UUID(str(row["id"])),
        username=str(row["username"]),
        is_administrator=bool(row["is_administrator"]),
        created_at=str(row["created_at"]),
    )


def _account_summary(row: Any) -> AccountSummary:
    return AccountSummary(
        id=UUID(str(row["id"])),
        username=str(row["username"]),
        is_active=bool(row["is_active"]),
        created_at=str(row["created_at"]),
    )


def _project_response(row: Any) -> ProjectResponse:
    return ProjectResponse(id=UUID(str(row["id"])), name=str(row["name"]), created_at=str(row["created_at"]))


def _membership_response(row: Any) -> MembershipResponse:
    return MembershipResponse(
        project_id=UUID(str(row["project_id"])),
        user_id=UUID(str(row["user_id"])),
        role=ProjectRole(str(row["role"])),
        username=str(row["username"]),
        is_active=bool(row["is_active"]),
    )


def _model_response(row: Any) -> ModelVersionResponse:
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


def _analysis_run_from_store(row: Any) -> AnalysisRunResponse:
    dataset = None
    if row["dataset_storage_kind"] is not None:
        dataset = {
            "storage_kind": row["dataset_storage_kind"],
            "checksum": row["dataset_checksum"],
        }
    return _analysis_run_response(row, dataset)


def _analysis_run_response(row: Any, dataset: Any | None = None) -> AnalysisRunResponse:
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


def _dataset_response(row: Any) -> DatasetResponse:
    return DatasetResponse(
        id=UUID(str(row["id"])),
        project_id=UUID(str(row["project_id"])),
        storage_kind=str(row["storage_kind"]),
        object_reference=str(row["object_reference"]),
        checksum=str(row["checksum"]) if row["checksum"] else None,
        source_compatibility="hdfs",
        created_at=str(row["created_at"]),
    )


def _anomaly_response(row: Any) -> HdfsAnomalyResult:
    try:
        stored_context = json.loads(str(row["context_json"]))
    except json.JSONDecodeError:
        stored_context = {}
    block_id = str(row["record_reference"])
    level = row["anomaly_level"]
    return HdfsAnomalyResult(
        block_id=block_id,
        record_reference=block_id,
        anomaly_score=_optional_finite_float(row["anomaly_score"]),
        anomaly_level=str(level) if isinstance(level, str) else None,
        decision_threshold=_optional_finite_float(row["decision_threshold"]),
        context=_hdfs_anomaly_context(stored_context),
    )


def _analysis_result_summary(run: Any, response: AnalysisRunResponse) -> AnalysisResultSummary:
    if run["results_summary_json"]:
        payload = json.loads(str(run["results_summary_json"]))
    else:
        payload = json.loads(
            _stored_results_summary(response.status, response.validation_report or {}, 0)
        )
    return AnalysisResultSummary.model_validate(payload)


def _analysis_result_trace(run: Any, model: Any) -> AnalysisResultTrace:
    artifact = model.get("artifact_sha256")
    dataset_checksum = run.get("dataset_checksum")
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
    )


def _hdfs_anomaly_context(value: Any) -> HdfsAnomalyContext:
    if not isinstance(value, dict):
        return HdfsAnomalyContext()
    matched = value.get("matched_line_count", 0)
    if not isinstance(matched, int) or isinstance(matched, bool) or matched < 0:
        matched = 0
    lines: list[HdfsSourceLine] = []
    raw_lines = value.get("source_lines")
    if isinstance(raw_lines, list):
        for item in raw_lines:
            projected = _hdfs_source_line(item)
            if projected is not None:
                lines.append(projected)
    return HdfsAnomalyContext(matched_line_count=matched, source_lines=lines)


def _hdfs_source_line(item: Any) -> HdfsSourceLine | None:
    if not isinstance(item, dict) or not isinstance(item.get("raw"), str):
        return None
    line_number = item.get("line_number")
    if line_number is not None and (
        not isinstance(line_number, int) or isinstance(line_number, bool)
    ):
        line_number = None
    return HdfsSourceLine(line_number=line_number, raw=str(item["raw"]))


def _optional_finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _audit_response(row: Any) -> AuditEventResponse:
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


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _not_found(resource_name: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource_name} was not found.")
