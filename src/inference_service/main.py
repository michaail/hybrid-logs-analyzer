"""Private FastAPI service that executes one queued HDFS analysis run."""

from __future__ import annotations

import hmac
import logging
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.object_store import build_object_store
from src.api.storage import ApiDatabase
from src.inference_service.settings import InferenceSettings

logger = logging.getLogger(__name__)


def create_app(settings: InferenceSettings | None = None) -> FastAPI:
    """Create the private inference app. The public API must not import this module."""

    resolved = settings or InferenceSettings.from_environment()
    database = ApiDatabase(resolved.database_url)
    object_store = build_object_store(resolved)
    bearer = HTTPBearer(auto_error=False)

    def require_internal_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        provided = credentials.credentials if credentials is not None else ""
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized()
        if not _tokens_match(provided, resolved.internal_token):
            raise _unauthorized()

    app = FastAPI(
        title="HDFS Inference Service",
        version="0.1.0",
        description="Private on-demand HDFS inference. Accepts a run UUID only.",
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Return readiness when the shared database is reachable."""

        if not database.healthcheck():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database is unavailable.",
            )
        try:
            from src.inference_service.runner import reclaim_stale_running_runs

            reclaim_stale_running_runs(
                database,
                stale_running_seconds=resolved.stale_running_seconds,
            )
        except Exception:
            logger.exception("Failed to reclaim stale running analysis runs")
        return {"status": "ok"}

    @app.post(
        "/internal/analysis-runs/{run_id}/execute",
        tags=["inference"],
    )
    def execute_run(
        run_id: UUID,
        _: None = Depends(require_internal_token),
    ) -> dict[str, str]:
        """Execute one queued analysis run. Duplicate calls are idempotent."""

        from src.inference_service.runner import execute_analysis_run

        result = execute_analysis_run(
            run_id,
            database,
            object_store,
            stale_running_seconds=resolved.stale_running_seconds,
        )
        if not result.get("found"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Analysis run was not found.",
            )
        return {"id": str(result["id"]), "status": str(result["status"])}

    return app


def _tokens_match(provided: str, expected: str) -> bool:
    if not expected:
        return False
    provided_bytes = provided.encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    if len(provided_bytes) != len(expected_bytes):
        return False
    return hmac.compare_digest(provided_bytes, expected_bytes)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid inference token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
