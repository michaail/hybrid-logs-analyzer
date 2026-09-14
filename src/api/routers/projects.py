"""Projects-tag routes for the HDFS control plane."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.responses import Response

from src.api.deps import CurrentUser, get_current_user, get_database, not_found, require_administrator
from src.api.responses import membership_response, project_response
from src.api.schemas import (
    MembershipCreate,
    MembershipResponse,
    MembershipRoleUpdate,
    ProjectCreate,
    ProjectResponse,
)
from src.api.storage import ApiDatabase, DatabaseIntegrityError

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> list[ProjectResponse]:
    """List projects visible through the caller's membership or administration role."""
    return [
        project_response(project)
        for project in database.list_projects_for_user(user.id, user.is_administrator)
    ]


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    request: ProjectCreate,
    administrator: CurrentUser = Depends(require_administrator),
    database: ApiDatabase = Depends(get_database),
) -> ProjectResponse:
    """Create a project isolation boundary."""
    try:
        project = database.create_project_with_audit(
            name=request.name,
            actor_user_id=administrator.id,
        )
    except DatabaseIntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project name already exists.",
        ) from None
    return project_response(project)


@router.post(
    "/projects/{project_id}/members",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
def grant_project_membership(
    project_id: UUID,
    request: MembershipCreate,
    administrator: CurrentUser = Depends(require_administrator),
    database: ApiDatabase = Depends(get_database),
) -> MembershipResponse:
    """Grant project access to an existing account; duplicates are rejected."""
    if database.get_project(project_id) is None or database.get_user_by_id(request.user_id) is None:
        raise not_found("Project or user")
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
    return membership_response(membership)


@router.patch(
    "/projects/{project_id}/members/{user_id}",
    response_model=MembershipResponse,
)
def update_project_membership_role(
    project_id: UUID,
    user_id: UUID,
    request: MembershipRoleUpdate,
    administrator: CurrentUser = Depends(require_administrator),
    database: ApiDatabase = Depends(get_database),
) -> MembershipResponse:
    """Change the role of an existing project membership."""
    if database.get_project(project_id) is None:
        raise not_found("Project")
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
        raise not_found("Membership")
    return membership_response(membership)


@router.delete(
    "/projects/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def revoke_project_membership(
    project_id: UUID,
    user_id: UUID,
    administrator: CurrentUser = Depends(require_administrator),
    database: ApiDatabase = Depends(get_database),
) -> Response:
    """Revoke an existing project membership while preserving audit history."""
    if database.get_project(project_id) is None:
        raise not_found("Project")
    revoked = database.revoke_membership(
        project_id=project_id,
        user_id=user_id,
        actor_user_id=administrator.id,
    )
    if not revoked:
        raise not_found("Membership")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/members",
    response_model=list[MembershipResponse],
)
def list_project_memberships(
    project_id: UUID,
    administrator: CurrentUser = Depends(require_administrator),
    database: ApiDatabase = Depends(get_database),
) -> list[MembershipResponse]:
    """List memberships for one project to support Administrator oversight."""
    del administrator
    if database.get_project(project_id) is None:
        raise not_found("Project")
    return [membership_response(item) for item in database.list_memberships(project_id)]
