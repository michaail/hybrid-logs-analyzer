"""Request identity, app state, and authorization helpers for the HDFS control plane."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import Request

from src.api.object_store import ObjectStore
from src.api.schemas import ProjectRole
from src.api.security import decode_access_token
from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated user identity available to a request."""

    id: UUID
    username: str
    is_administrator: bool


def get_settings(request: Request) -> ApiSettings:
    """Return API settings attached to the FastAPI app."""
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, ApiSettings):
        raise RuntimeError("API settings are not configured.")
    return settings


def get_database(request: Request) -> ApiDatabase:
    """Return the request-scoped API database."""
    database = getattr(request.app.state, "database", None)
    if not isinstance(database, ApiDatabase):
        raise RuntimeError("API database is not configured.")
    return database


def get_object_store(request: Request) -> ObjectStore:
    """Return the request-scoped object store."""
    object_store = getattr(request.app.state, "object_store", None)
    if object_store is None:
        raise RuntimeError("Object store is not configured.")
    return object_store


def unauthorized() -> HTTPException:
    """Return the shared 401 used by login and bearer-token gates."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def not_found(resource_name: str) -> HTTPException:
    """Return a 404 whose detail names the missing resource."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource_name} was not found.",
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """Resolve the bearer token to an active provisioned account."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    settings = get_settings(request)
    user_id = decode_access_token(credentials.credentials, settings)
    if user_id is None:
        raise unauthorized()
    user = get_database(request).get_user_by_id(user_id)
    if user is None or not bool(user["is_active"]):
        raise unauthorized()
    return CurrentUser(
        id=UUID(str(user["id"])),
        username=str(user["username"]),
        is_administrator=bool(user["is_administrator"]),
    )


def require_administrator(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Reject non-administrator callers with 403."""
    if not user.is_administrator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return user


def require_project_access(
    database: ApiDatabase,
    project_id: UUID,
    user: CurrentUser,
) -> ProjectRole | None:
    """Return the caller's project role, or None for administrators.

    Missing membership is a 404 so project existence is not leaked.
    """
    if user.is_administrator:
        if database.get_project(project_id) is None:
            raise not_found("Project")
        return None
    membership = database.get_membership(project_id, user.id)
    if membership is None:
        raise not_found("Project")
    return ProjectRole(str(membership["role"]))


def require_project_role(
    database: ApiDatabase,
    project_id: UUID,
    user: CurrentUser,
    allowed_roles: set[ProjectRole],
) -> None:
    """Require a project role, treating Publisher as satisfying Operator."""
    role = require_project_access(database, project_id, user)
    if role is None:
        return
    if role is ProjectRole.PUBLISHER and ProjectRole.OPERATOR in allowed_roles:
        return
    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient project role.",
        )
