"""Datasets-tag routes for the HDFS control plane."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from src.api.deps import (
    CurrentUser,
    get_current_user,
    get_database,
    get_object_store,
    not_found,
    require_project_role,
)
from src.api.object_store import ObjectStore, dataset_object_prefix
from src.api.responses import dataset_response
from src.api.schemas import DatasetResponse, ProjectRole
from src.api.storage import ApiDatabase, DatabaseIntegrityError
from src.api.validation import MAX_HDFS_UPLOAD_BYTES, admit_uploaded_hdfs_log

router = APIRouter(tags=["datasets"])


@router.get(
    "/projects/{project_id}/datasets",
    response_model=list[DatasetResponse],
)
def list_datasets(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> list[DatasetResponse]:
    """List reusable HDFS sources owned by an authorized project."""
    require_project_role(database, project_id, user, {ProjectRole.OPERATOR})
    return [dataset_response(item) for item in database.list_datasets(project_id)]


@router.post(
    "/projects/{project_id}/datasets",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_dataset(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
    object_store: ObjectStore = Depends(get_object_store),
    log: UploadFile = File(..., description="UTF-8 HDFS log dataset"),
) -> DatasetResponse:
    """Admit an Operator HDFS log upload. Persist an object only when the whole file is valid."""
    require_project_role(database, project_id, user, {ProjectRole.OPERATOR})
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
    return dataset_response(dataset)


@router.get(
    "/projects/{project_id}/datasets/{dataset_id}",
    response_model=DatasetResponse,
)
def get_dataset(
    project_id: UUID,
    dataset_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> DatasetResponse:
    """Get a single project-owned dataset pointer."""
    require_project_role(database, project_id, user, {ProjectRole.OPERATOR})
    dataset = database.get_dataset(dataset_id)
    if dataset is None or dataset["project_id"] != str(project_id):
        raise not_found("Dataset")
    return dataset_response(dataset)
