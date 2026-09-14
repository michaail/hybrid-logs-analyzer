"""FastAPI application factory for the HDFS anomaly-detection MVP."""

from __future__ import annotations

from fastapi import FastAPI

from src.api.frontend_mount import mount_frontend
from src.api.middleware import SecurityHeadersMiddleware
from src.api.object_store import build_object_store
from src.api.routers.administration import router as administration_router
from src.api.routers.analysis import router as analysis_router
from src.api.routers.authentication import router as authentication_router
from src.api.routers.datasets import router as datasets_router
from src.api.routers.health import router as health_router
from src.api.routers.models import router as models_router
from src.api.routers.projects import router as projects_router
from src.api.routers.users import router as users_router
from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Create a configured FastAPI app without importing legacy ML loaders."""
    resolved_settings = settings or ApiSettings.from_environment()
    database = ApiDatabase(resolved_settings.database_url)
    object_store = build_object_store(resolved_settings)
    app = FastAPI(
        title="HDFS Anomaly Detection API",
        version="0.1.0",
        description=(
            "HDFS-only model registration and analysis-run API. "
            "It never deserializes uploaded model artifacts."
        ),
    )
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.object_store = object_store
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health_router)
    app.include_router(authentication_router)
    app.include_router(users_router)
    app.include_router(administration_router)
    app.include_router(projects_router)
    app.include_router(models_router)
    app.include_router(analysis_router)
    app.include_router(datasets_router)
    mount_frontend(app)
    return app
