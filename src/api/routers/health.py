"""Health-tag routes for the HDFS control plane."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.deps import get_database
from src.api.storage import ApiDatabase

router = APIRouter(tags=["health"])


@router.get("/health")
def health(database: ApiDatabase = Depends(get_database)) -> dict[str, str]:
    """Return a non-sensitive readiness result only when the database is reachable."""
    if not database.healthcheck():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        )
    return {"status": "ok"}
