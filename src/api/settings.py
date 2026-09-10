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
    object_store_root: Path = Path(".api/objects")
    object_store_endpoint: str | None = None
    object_store_bucket: str | None = None
    object_store_access_key_id: str | None = None
    object_store_secret_access_key: str | None = None
    object_store_region: str = "auto"

    @property
    def uses_bucket_object_store(self) -> bool:
        """True when Railway Bucket (or other S3-compatible) credentials are complete."""

        return self.object_store_endpoint is not None

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
        object_raw = os.environ.get("API_OBJECT_STORE_ROOT")
        if object_raw:
            object_store_root = Path(object_raw).resolve()
        else:
            object_store_root = (workspace_root.parent / ".api" / "objects").resolve()
        ttl_raw = os.environ.get("API_JWT_TTL_MINUTES", "30")
        try:
            jwt_ttl_minutes = int(ttl_raw)
        except ValueError as error:
            raise RuntimeError("API_JWT_TTL_MINUTES must be a positive integer.") from error
        if jwt_ttl_minutes <= 0:
            raise RuntimeError("API_JWT_TTL_MINUTES must be a positive integer.")
        endpoint, bucket, access_key, secret_key = _bucket_credentials_from_environment()
        region = _optional_env("API_OBJECT_STORE_REGION") or "auto"

        return cls(
            database_url=database_url,
            jwt_secret=secret,
            trusted_workspace_root=workspace_root,
            jwt_ttl_minutes=jwt_ttl_minutes,
            code_root=Path(os.environ.get("API_CODE_ROOT", ".")).resolve(),
            object_store_root=object_store_root,
            object_store_endpoint=endpoint,
            object_store_bucket=bucket,
            object_store_access_key_id=access_key,
            object_store_secret_access_key=secret_key,
            object_store_region=region,
        )


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _bucket_credentials_from_environment() -> tuple[str | None, str | None, str | None, str | None]:
    """Require endpoint, bucket, and both access keys together, or none of them."""

    endpoint = _optional_env("API_OBJECT_STORE_ENDPOINT")
    bucket = _optional_env("API_OBJECT_STORE_BUCKET")
    access_key = _optional_env("API_OBJECT_STORE_ACCESS_KEY_ID")
    secret_key = _optional_env("API_OBJECT_STORE_SECRET_ACCESS_KEY")
    present = [
        name
        for name, value in (
            ("API_OBJECT_STORE_ENDPOINT", endpoint),
            ("API_OBJECT_STORE_BUCKET", bucket),
            ("API_OBJECT_STORE_ACCESS_KEY_ID", access_key),
            ("API_OBJECT_STORE_SECRET_ACCESS_KEY", secret_key),
        )
        if value is not None
    ]
    if not present:
        return None, None, None, None
    if len(present) != 4:
        raise RuntimeError(
            "Bucket object-store settings must be set together: "
            "API_OBJECT_STORE_ENDPOINT, API_OBJECT_STORE_BUCKET, "
            "API_OBJECT_STORE_ACCESS_KEY_ID, and API_OBJECT_STORE_SECRET_ACCESS_KEY."
        )
    return endpoint, bucket, access_key, secret_key
