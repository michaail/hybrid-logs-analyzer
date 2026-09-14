"""Users-tag routes for the HDFS control plane."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_current_user, get_database, unauthorized
from src.api.responses import user_response
from src.api.schemas import UserResponse
from src.api.storage import ApiDatabase

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=UserResponse)
def get_me(
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> UserResponse:
    """Return the identity represented by the bearer token."""
    stored_user = database.get_user_by_id(user.id)
    if stored_user is None:
        raise unauthorized()
    return user_response(stored_user)
