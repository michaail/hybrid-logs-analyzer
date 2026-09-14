"""Models-tag routes for the HDFS control plane."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from src.api.deps import (
    CurrentUser,
    get_current_user,
    get_database,
    get_object_store,
    get_settings,
    not_found,
    require_project_access,
    require_project_role,
)
from src.api.object_store import ObjectStore
from src.api.responses import model_response
from src.api.schemas import ModelStatus, ModelVersionResponse, ProjectRole
from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase, DatabaseIntegrityError
from src.api.validation import (
    ValidationError,
    ValidatorUnavailableError,
    admit_uploaded_zip_package,
)
from src.modules.model_package import MAX_ZIP_COMPRESSED_BYTES

router = APIRouter(tags=["models"])


@router.get(
    "/projects/{project_id}/models",
    response_model=list[ModelVersionResponse],
)
def list_model_versions(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> list[ModelVersionResponse]:
    """List only model versions within an authorized project."""
    require_project_access(database, project_id, user)
    return [model_response(item) for item in database.list_model_versions(project_id)]


@router.post(
    "/projects/{project_id}/models",
    response_model=ModelVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_model_version(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
    object_store: ObjectStore = Depends(get_object_store),
    settings: ApiSettings = Depends(get_settings),
    package: UploadFile = File(..., description="Complete HDFS model package ZIP"),
    preprocessing_bundle: UploadFile | None = File(
        default=None,
        description="Companion preprocessing-bundle ZIP required for registration",
    ),
) -> ModelVersionResponse:
    """Admit a Publisher ZIP upload. Never loads the artifact in this process."""
    require_project_role(database, project_id, user, {ProjectRole.PUBLISHER})
    archive_bytes = package.file.read(MAX_ZIP_COMPRESSED_BYTES + 1)
    bundle_bytes = None
    if preprocessing_bundle is not None:
        bundle_bytes = preprocessing_bundle.file.read(MAX_ZIP_COMPRESSED_BYTES + 1)
    try:
        report, admitted = admit_uploaded_zip_package(
            archive_bytes,
            settings=settings,
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

    def _delete_admitted_prefixes() -> None:
        try:
            object_store.delete_prefix(admitted.package_reference)
        finally:
            if admitted.preprocessing_bundle is not None:
                object_store.delete_prefix(admitted.preprocessing_bundle.object_prefix)

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
        _delete_admitted_prefixes()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This model identifier and version already exists in the project.",
        ) from None
    except Exception:
        object_store.delete_prefix(admitted.package_reference)
        if admitted.preprocessing_bundle is not None:
            object_store.delete_prefix(admitted.preprocessing_bundle.object_prefix)
        raise
    return model_response(model)


@router.get(
    "/projects/{project_id}/models/{model_version_id}",
    response_model=ModelVersionResponse,
)
def get_model_version(
    project_id: UUID,
    model_version_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> ModelVersionResponse:
    """Get a model only after checking caller access to the requested project."""
    require_project_access(database, project_id, user)
    model = database.get_model_version(model_version_id)
    if model is None or model["project_id"] != str(project_id):
        raise not_found("Model version")
    return model_response(model)


@router.post(
    "/projects/{project_id}/models/{model_version_id}/publish",
    response_model=ModelVersionResponse,
)
def publish_model_version(
    project_id: UUID,
    model_version_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> ModelVersionResponse:
    """Explicitly publish an eligible model within its authorized project."""
    require_project_role(database, project_id, user, {ProjectRole.PUBLISHER})
    model = database.get_model_version(model_version_id)
    if model is None or model["project_id"] != str(project_id):
        raise not_found("Model version")
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
    return model_response(published_model)
