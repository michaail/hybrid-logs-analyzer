"""Configuration for the FastAPI application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class ApiSettings:
    """Runtime settings with paths intentionally outside versioned source code."""

    database_url: str
    jwt_secret: str
    trusted_workspace_root: Path
    jwt_ttl_minutes: int = 30
    code_root: Path = Path(".")
    model_validator_command: tuple[str, ...] | None = None

    @classmethod
    def from_environment(cls) -> "ApiSettings":
        """Build settings from environment variables and reject an unset signing key."""
        load_dotenv()
        secret = os.environ.get("API_JWT_SECRET")
        if not secret:
            raise RuntimeError(
                "API_JWT_SECRET must be set before starting the API. "
                "Generate a high-entropy value and keep it outside version control."
            )

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL must be set before starting the API. "
                "Use a PostgreSQL URL in Railway or a sqlite URL for local development."
            )
        workspace_root = Path(
            os.environ.get("API_TRUSTED_WORKSPACE_ROOT", "workspace")
        ).resolve()
        ttl_raw = os.environ.get("API_JWT_TTL_MINUTES", "30")
        try:
            jwt_ttl_minutes = int(ttl_raw)
        except ValueError as error:
            raise RuntimeError("API_JWT_TTL_MINUTES must be a positive integer.") from error
        if jwt_ttl_minutes <= 0:
            raise RuntimeError("API_JWT_TTL_MINUTES must be a positive integer.")

        return cls(
            database_url=database_url,
            jwt_secret=secret,
            trusted_workspace_root=workspace_root,
            jwt_ttl_minutes=jwt_ttl_minutes,
            code_root=Path(os.environ.get("API_CODE_ROOT", ".")).resolve(),
        )
