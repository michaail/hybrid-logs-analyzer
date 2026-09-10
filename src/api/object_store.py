"""Immutable object-store protocol for admitted HDFS model packages and datasets."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from src.api.settings import ApiSettings

_DELETE_BATCH_SIZE = 1000


class ObjectStore(Protocol):
    """Put and delete POSIX object keys under a private prefix."""

    def put(self, key: str, payload: bytes) -> None:
        """Write ``payload`` at ``key``, replacing any existing object."""

    def delete_prefix(self, prefix: str) -> None:
        """Remove every object whose key equals ``prefix`` or starts with ``prefix/``."""


class S3Client(Protocol):
    """Minimal S3 surface used by the Bucket backend. Tests inject a stub."""

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> object:
        """Upload one object."""

    def list_objects_v2(
        self,
        *,
        Bucket: str,
        Prefix: str,
        ContinuationToken: str | None = None,
    ) -> Mapping[str, Any]:
        """List object keys under ``Prefix``."""

    def delete_objects(self, *, Bucket: str, Delete: Mapping[str, Any]) -> object:
        """Delete a batch of object keys."""


def model_package_object_key(
    project_id: UUID | str,
    model_id: UUID | str,
    version: str,
    relative: str,
) -> str:
    """Build ``projects/<project-id>/models/<model-id>/<version>/<relative>``."""

    member = _require_relative_posix(relative)
    return f"projects/{project_id}/models/{model_id}/{version}/{member}"


def model_package_object_prefix(project_id: UUID | str, model_id: UUID | str, version: str) -> str:
    """Return the directory prefix for one model version's declared files."""

    return f"projects/{project_id}/models/{model_id}/{version}"


def dataset_object_prefix(project_id: UUID | str, dataset_id: UUID | str) -> str:
    """Return the directory prefix for one admitted HDFS dataset."""

    return f"projects/{project_id}/datasets/{dataset_id}"


def dataset_object_key(project_id: UUID | str, dataset_id: UUID | str, relative: str) -> str:
    """Build ``projects/<project-id>/datasets/<dataset-id>/<relative>``."""

    member = _require_relative_posix(relative)
    return f"projects/{project_id}/datasets/{dataset_id}/{member}"


def build_object_store(
    settings: ApiSettings,
    *,
    s3_client: S3Client | None = None,
) -> ObjectStore:
    """Return the Bucket backend when configured, otherwise the filesystem backend."""

    if settings.uses_bucket_object_store:
        bucket = settings.object_store_bucket
        if not bucket:
            raise RuntimeError("API_OBJECT_STORE_BUCKET must be set for the Bucket backend.")
        client = s3_client if s3_client is not None else create_s3_client(settings)
        return BucketObjectStore(client, bucket)
    return FilesystemObjectStore(settings.object_store_root)


def create_s3_client(settings: ApiSettings) -> S3Client:
    """Build an S3-compatible client from Bucket settings. Imported only when needed."""

    if not settings.uses_bucket_object_store:
        raise RuntimeError("Bucket object-store settings are not configured.")
    try:
        import boto3
        from botocore.config import Config
    except ImportError as error:
        raise RuntimeError(
            "boto3 must be installed to use the Bucket object-store backend. "
            "Install requirements-api.txt in the API runtime."
        ) from error
    return boto3.client(
        "s3",
        endpoint_url=settings.object_store_endpoint,
        aws_access_key_id=settings.object_store_access_key_id,
        aws_secret_access_key=settings.object_store_secret_access_key,
        region_name=settings.object_store_region,
        config=Config(
            s3={"addressing_style": "virtual"},
            signature_version="s3v4",
        ),
    )


class FilesystemObjectStore:
    """Local object store rooted outside the Publisher-staged workspace tree."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, payload: bytes) -> None:
        target = self._resolved_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    def delete_prefix(self, prefix: str) -> None:
        target = self._resolved_key(prefix.rstrip("/"))
        if target.is_dir():
            shutil.rmtree(target)
            return
        if target.is_file():
            target.unlink()

    def _resolved_key(self, key: str) -> Path:
        relative = _require_relative_posix(key)
        target = (self._root / relative).resolve()
        try:
            target.relative_to(self._root)
        except ValueError as error:
            raise ValueError("Object key must stay inside the object store root.") from error
        return target


class BucketObjectStore:
    """S3-compatible Railway Bucket backend. Never deserializes ``.pt`` payloads."""

    def __init__(self, client: S3Client, bucket: str) -> None:
        if not bucket:
            raise ValueError("Bucket name must be non-empty.")
        self._client = client
        self._bucket = bucket

    def put(self, key: str, payload: bytes) -> None:
        relative = _require_relative_posix(key)
        self._client.put_object(Bucket=self._bucket, Key=relative, Body=payload)

    def delete_prefix(self, prefix: str) -> None:
        relative = _require_relative_posix(prefix.rstrip("/"))
        keys = [
            key
            for key in _list_keys(self._client, self._bucket, relative)
            if key == relative or key.startswith(f"{relative}/")
        ]
        for index in range(0, len(keys), _DELETE_BATCH_SIZE):
            batch = [{"Key": key} for key in keys[index : index + _DELETE_BATCH_SIZE]]
            self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": batch})


def _list_keys(client: S3Client, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token is not None:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for item in page.get("Contents") or []:
            key = item.get("Key")
            if isinstance(key, str):
                keys.append(key)
        if not page.get("IsTruncated"):
            break
        next_token = page.get("NextContinuationToken")
        if not isinstance(next_token, str) or not next_token:
            break
        token = next_token
    return keys


def _require_relative_posix(value: str) -> str:
    if not value or value.startswith("/") or "\\" in value or Path(value).is_absolute():
        raise ValueError("Object key must be a relative POSIX path")
    if ".." in Path(value).parts:
        raise ValueError("Object key must not contain '..' segments")
    return value
