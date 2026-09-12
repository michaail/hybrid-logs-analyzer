"""Configuration for the FastAPI application."""

from __future__ import annotations

import math
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
    inference_service_url: str | None = None
    inference_internal_token: str | None = None
    inference_connect_timeout_seconds: float = 2.0
    inference_read_timeout_seconds: float = 5.0
    inference_retry_attempts: int = 5
    inference_retry_backoff_seconds: float = 2.0

    @property
    def uses_bucket_object_store(self) -> bool:
        """True when endpoint, bucket name, and both access keys are present."""

        return bool(
            self.object_store_endpoint
            and self.object_store_bucket
            and self.object_store_access_key_id
            and self.object_store_secret_access_key
        )

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
        inference_url, inference_token = _inference_credentials_from_environment()

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
            inference_service_url=inference_url,
            inference_internal_token=inference_token,
            inference_connect_timeout_seconds=_positive_float_env(
                "INFERENCE_CONNECT_TIMEOUT_SECONDS", 2.0
            ),
            inference_read_timeout_seconds=_positive_float_env(
                "INFERENCE_READ_TIMEOUT_SECONDS", 5.0
            ),
            inference_retry_attempts=_positive_int_env("INFERENCE_RETRY_ATTEMPTS", 5),
            inference_retry_backoff_seconds=_non_negative_float_env(
                "INFERENCE_RETRY_BACKOFF_SECONDS", 2.0
            ),
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


def _inference_credentials_from_environment() -> tuple[str | None, str | None]:
    """Require the private service URL and invocation token together, or neither."""

    url = _optional_env("INFERENCE_SERVICE_URL")
    token = _optional_env("INFERENCE_INTERNAL_TOKEN")
    present = [
        name
        for name, value in (
            ("INFERENCE_SERVICE_URL", url),
            ("INFERENCE_INTERNAL_TOKEN", token),
        )
        if value is not None
    ]
    if not present:
        return None, None
    if len(present) != 2:
        raise RuntimeError(
            "Inference dispatch settings must be set together: "
            "INFERENCE_SERVICE_URL and INFERENCE_INTERNAL_TOKEN."
        )
    return url, token


def _positive_int_env(name: str, default: int) -> int:
    raw = _optional_env(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive integer.") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


def _positive_float_env(name: str, default: float) -> float:
    return _float_env(name, default, minimum=0.0, exclusive_minimum=True)


def _non_negative_float_env(name: str, default: float) -> float:
    return _float_env(name, default, minimum=0.0, exclusive_minimum=False)


def _float_env(
    name: str,
    default: float,
    *,
    minimum: float,
    exclusive_minimum: bool,
) -> float:
    raw = _optional_env(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a finite number.") from error
    if not math.isfinite(value):
        raise RuntimeError(f"{name} must be a finite number.")
    if exclusive_minimum:
        if value <= minimum:
            raise RuntimeError(f"{name} must be greater than {minimum}.")
    elif value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}.")
    return value
