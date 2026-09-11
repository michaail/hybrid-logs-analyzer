"""Configuration for the private inference service. This process never signs JWTs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class InferenceSettings:
    """Runtime settings for isolated HDFS inference."""

    database_url: str
    internal_token: str
    code_root: Path
    object_store_root: Path
    object_store_endpoint: str | None = None
    object_store_bucket: str | None = None
    object_store_access_key_id: str | None = None
    object_store_secret_access_key: str | None = None
    object_store_region: str = "auto"

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
    def from_environment(cls) -> "InferenceSettings":
        """Build settings without requiring API_JWT_SECRET."""

        load_dotenv()
        token = os.environ.get("INFERENCE_INTERNAL_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "INFERENCE_INTERNAL_TOKEN must be set before starting inference."
            )
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL must be set before starting inference.")
        object_raw = os.environ.get("API_OBJECT_STORE_ROOT")
        if object_raw:
            object_store_root = Path(object_raw).resolve()
        else:
            object_store_root = (Path.cwd() / ".api" / "objects").resolve()
        endpoint, bucket, access_key, secret_key = _bucket_credentials()
        return cls(
            database_url=database_url,
            internal_token=token,
            code_root=Path(os.environ.get("API_CODE_ROOT", ".")).resolve(),
            object_store_root=object_store_root,
            object_store_endpoint=endpoint,
            object_store_bucket=bucket,
            object_store_access_key_id=access_key,
            object_store_secret_access_key=secret_key,
            object_store_region=_optional_env("API_OBJECT_STORE_REGION") or "auto",
        )


def _bucket_credentials() -> tuple[str | None, str | None, str | None, str | None]:
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


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None
