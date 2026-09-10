"""Immutable object-store protocol for admitted HDFS model packages."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol
from uuid import UUID


class ObjectStore(Protocol):
    """Put and delete POSIX object keys under a private prefix."""

    def put(self, key: str, payload: bytes) -> None:
        """Write ``payload`` at ``key``, replacing any existing object."""

    def delete_prefix(self, prefix: str) -> None:
        """Remove every object whose key equals ``prefix`` or starts with ``prefix/``."""


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


def _require_relative_posix(value: str) -> str:
    if not value or value.startswith("/") or "\\" in value or Path(value).is_absolute():
        raise ValueError("Object key must be a relative POSIX path")
    if ".." in Path(value).parts:
        raise ValueError("Object key must not contain '..' segments")
    return value
