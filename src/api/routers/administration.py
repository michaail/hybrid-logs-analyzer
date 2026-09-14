"""Administration-tag routes for the HDFS control plane."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.deps import CurrentUser, get_database, not_found, require_administrator
from src.api.responses import account_summary, audit_response, membership_response
from src.api.schemas import (
    AccountActivationUpdate,
    AccountSummary,
    AuditEventResponse,
    ProjectAccountCreate,
    ProjectAccountResponse,
)
from src.api.security import hash_password
from src.api.storage import ApiDatabase, DatabaseIntegrityError

router = APIRouter(tags=["administration"])


@router.post(
    "/admin/project-accounts",
    response_model=ProjectAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def provision_project_account(
    request: ProjectAccountCreate,
    administrator: CurrentUser = Depends(require_administrator),
    database: ApiDatabase = Depends(get_database),
) -> ProjectAccountResponse:
    """Create a non-administrator account and its initial project membership atomically."""
    if database.get_project(request.project_id) is None:
        raise not_found("Project")
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
        account=account_summary(created_user),
        membership=membership_response(membership),
    )


@router.get("/admin/users", response_model=list[AccountSummary])
def list_users(
    administrator: CurrentUser = Depends(require_administrator),
    database: ApiDatabase = Depends(get_database),
) -> list[AccountSummary]:
    """List provisioned accounts and their active state for Administrator oversight."""
    del administrator
    return [account_summary(user) for user in database.list_users()]


@router.patch(
    "/admin/users/{user_id}/activation",
    response_model=AccountSummary,
)
def set_user_activation(
    user_id: UUID,
    request: AccountActivationUpdate,
    administrator: CurrentUser = Depends(require_administrator),
    database: ApiDatabase = Depends(get_database),
) -> AccountSummary:
    """Activate or deactivate a non-administrator account."""
    if database.get_user_by_id(user_id) is None:
        raise not_found("User")
    try:
        updated = database.set_user_active(
            user_id=user_id,
            is_active=request.is_active,
            actor_user_id=administrator.id,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None
    if updated is None:
        raise not_found("User")
    return account_summary(updated)


@router.get(
    "/admin/audit-events",
    response_model=list[AuditEventResponse],
)
def list_system_audit_events(
    administrator: CurrentUser = Depends(require_administrator),
    database: ApiDatabase = Depends(get_database),
) -> list[AuditEventResponse]:
    """Return Administrator-visible user-resource audit events across the system."""
    del administrator
    return [audit_response(event) for event in database.list_user_audit_events()]


@router.get(
    "/projects/{project_id}/audit-events",
    response_model=list[AuditEventResponse],
)
def list_audit_events(
    project_id: UUID,
    administrator: CurrentUser = Depends(require_administrator),
    database: ApiDatabase = Depends(get_database),
) -> list[AuditEventResponse]:
    """Return immutable audit records for Administrator review."""
    del administrator
    if database.get_project(project_id) is None:
        raise not_found("Project")
    return [audit_response(event) for event in database.list_audit_events(project_id)]
