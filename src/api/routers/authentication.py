"""Authentication-tag routes for the HDFS control plane."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends

from src.api.deps import get_database, get_settings, unauthorized
from src.api.schemas import LoginRequest, TokenResponse
from src.api.security import create_access_token, verify_password
from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase

router = APIRouter(tags=["authentication"])


@router.post("/auth/token", response_model=TokenResponse)
def login(
    credentials: LoginRequest,
    database: ApiDatabase = Depends(get_database),
    settings: ApiSettings = Depends(get_settings),
) -> TokenResponse:
    """Authenticate a provisioned account and issue a signed bearer token."""
    user = database.get_user_by_username(credentials.username)
    if (
        user is None
        or not bool(user["is_active"])
        or not verify_password(credentials.password, str(user["password_hash"]))
    ):
        raise unauthorized()
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
        access_token=create_access_token(user_id, settings),
        expires_in_seconds=settings.jwt_ttl_minutes * 60,
    )
