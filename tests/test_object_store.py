"""Object-store adapter tests. Non-ML tests never import Torch or a live Bucket."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from src.api.object_store import (
    BucketObjectStore,
    FilesystemObjectStore,
    build_object_store,
    model_package_object_key,
    model_package_object_prefix,
)
from src.api.settings import ApiSettings


class FakeS3Client:
    """In-memory S3 stub. CI must not require MinIO or network access."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> object:
        payload = Body if isinstance(Body, bytes) else bytes(Body)
        self.objects[(Bucket, Key)] = payload
        return {}

    def list_objects_v2(
        self,
        *,
        Bucket: str,
        Prefix: str,
        ContinuationToken: str | None = None,
    ) -> Mapping[str, Any]:
        del ContinuationToken
        contents = [
            {"Key": key}
            for bucket_name, key in sorted(self.objects)
            if bucket_name == Bucket and key.startswith(Prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}

    def delete_objects(self, *, Bucket: str, Delete: Mapping[str, Any]) -> object:
        for item in Delete.get("Objects", []):
            self.objects.pop((Bucket, item["Key"]), None)
        return {}


def test_object_store_source_does_not_import_torch() -> None:
    source = Path("src/api/object_store.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(
                alias.name != "torch" and not alias.name.startswith("torch.")
                for alias in node.names
            )
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("torch")


def test_model_package_object_key_is_posix_prefix() -> None:
    project_id = UUID("11111111-1111-4111-8111-111111111111")
    model_id = UUID("22222222-2222-4222-8222-222222222222")
    assert model_package_object_prefix(project_id, model_id, "v1") == (
        "projects/11111111-1111-4111-8111-111111111111/"
        "models/22222222-2222-4222-8222-222222222222/v1"
    )
    assert model_package_object_key(project_id, model_id, "v1", "manifest.json") == (
        "projects/11111111-1111-4111-8111-111111111111/"
        "models/22222222-2222-4222-8222-222222222222/v1/manifest.json"
    )


def test_filesystem_put_and_delete_prefix(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FilesystemObjectStore(tmp_path / ".api" / "objects")
    project_id = "proj-a"
    model_id = "model-a"
    prefix = model_package_object_prefix(project_id, model_id, "v1")
    store.put(model_package_object_key(project_id, model_id, "v1", "manifest.json"), b"{}")
    store.put(model_package_object_key(project_id, model_id, "v1", "model.pt"), b"weights")
    store.put(
        model_package_object_key(project_id, model_id, "v1", "evidence.json"),
        b'{"status":"ok"}',
    )
    other = model_package_object_key(project_id, "model-b", "v1", "manifest.json")
    store.put(other, b'{"keep":true}')

    root = tmp_path / ".api" / "objects"
    version_dir = root.joinpath(*prefix.split("/"))
    names = {
        path.relative_to(version_dir).as_posix()
        for path in version_dir.rglob("*")
        if path.is_file()
    }
    assert names == {"manifest.json", "model.pt", "evidence.json"}
    assert list(workspace.rglob("*")) == []

    store.delete_prefix(prefix)
    assert not version_dir.exists()
    kept = root / "projects" / project_id / "models" / "model-b" / "v1" / "manifest.json"
    assert kept.read_bytes() == b'{"keep":true}'


def test_filesystem_rejects_path_escape(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path / "objects")
    with pytest.raises(ValueError, match="relative POSIX"):
        store.put("/etc/passwd", b"secret")
    with pytest.raises(ValueError, match=r"\.\."):
        store.put("../escape.bin", b"secret")
    with pytest.raises(ValueError, match=r"\.\."):
        store.put("projects/x/../../etc/passwd", b"secret")
    with pytest.raises(ValueError, match=r"\.\."):
        store.delete_prefix("projects/../outside")
    assert list((tmp_path / "objects").rglob("*")) == []
    assert not (tmp_path / "escape.bin").exists()


def _clear_bucket_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "API_OBJECT_STORE_ENDPOINT",
        "API_OBJECT_STORE_BUCKET",
        "API_OBJECT_STORE_ACCESS_KEY_ID",
        "API_OBJECT_STORE_SECRET_ACCESS_KEY",
        "API_OBJECT_STORE_REGION",
    ):
        monkeypatch.setenv(name, "")


def test_object_store_root_defaults_and_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        jwt_secret="test-secret-not-for-production",
        trusted_workspace_root=tmp_path / "workspace",
    )
    assert settings.object_store_root == Path(".api/objects")

    _clear_bucket_env(monkeypatch)
    monkeypatch.setenv("API_JWT_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}")
    monkeypatch.setenv("API_TRUSTED_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("API_OBJECT_STORE_ROOT", "")
    loaded = ApiSettings.from_environment()
    assert loaded.object_store_root == (tmp_path / ".api" / "objects").resolve()

    override = tmp_path / "bucket-local"
    monkeypatch.setenv("API_OBJECT_STORE_ROOT", str(override))
    overridden = ApiSettings.from_environment()
    assert overridden.object_store_root == override.resolve()
    assert overridden.uses_bucket_object_store is False


def test_build_object_store_defaults_to_filesystem(tmp_path: Path) -> None:
    settings = ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        jwt_secret="test-secret-not-for-production",
        trusted_workspace_root=tmp_path / "workspace",
        object_store_root=tmp_path / "objects",
    )
    store = build_object_store(settings)
    assert isinstance(store, FilesystemObjectStore)


def test_incomplete_bucket_settings_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_bucket_env(monkeypatch)
    monkeypatch.setenv("API_JWT_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}")
    monkeypatch.setenv("API_TRUSTED_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("API_OBJECT_STORE_ENDPOINT", "https://storage.example.test")
    with pytest.raises(RuntimeError, match="must be set together"):
        ApiSettings.from_environment()


def test_bucket_settings_select_bucket_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_bucket_env(monkeypatch)
    monkeypatch.setenv("API_JWT_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}")
    monkeypatch.setenv("API_TRUSTED_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("API_OBJECT_STORE_ENDPOINT", "https://storage.example.test")
    monkeypatch.setenv("API_OBJECT_STORE_BUCKET", "models-test")
    monkeypatch.setenv("API_OBJECT_STORE_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("API_OBJECT_STORE_SECRET_ACCESS_KEY", "secret-key")
    monkeypatch.setenv("API_OBJECT_STORE_REGION", "ams")
    loaded = ApiSettings.from_environment()
    assert loaded.uses_bucket_object_store is True
    assert loaded.object_store_bucket == "models-test"
    assert loaded.object_store_region == "ams"
    fake = FakeS3Client()
    store = build_object_store(loaded, s3_client=fake)
    assert isinstance(store, BucketObjectStore)


def test_bucket_put_and_delete_prefix() -> None:
    fake = FakeS3Client()
    store = BucketObjectStore(fake, "models-test")
    project_id = "proj-a"
    model_id = "model-a"
    prefix = model_package_object_prefix(project_id, model_id, "v1")
    store.put(model_package_object_key(project_id, model_id, "v1", "manifest.json"), b"{}")
    store.put(model_package_object_key(project_id, model_id, "v1", "model.pt"), b"weights")
    store.put(
        model_package_object_key(project_id, model_id, "v1", "evidence.json"),
        b'{"status":"ok"}',
    )
    sibling = model_package_object_key(project_id, "model-b", "v1", "manifest.json")
    store.put(sibling, b'{"keep":true}')
    overlapping = model_package_object_key(project_id, model_id, "v1-extra", "manifest.json")
    store.put(overlapping, b'{"overlap":true}')

    stored = {
        key
        for bucket_name, key in fake.objects
        if bucket_name == "models-test" and (key == prefix or key.startswith(f"{prefix}/"))
    }
    assert stored == {
        f"{prefix}/manifest.json",
        f"{prefix}/model.pt",
        f"{prefix}/evidence.json",
    }

    store.delete_prefix(prefix)
    remaining = {key for _bucket, key in fake.objects}
    assert f"{prefix}/manifest.json" not in remaining
    assert sibling in remaining
    assert overlapping in remaining
    assert fake.objects[("models-test", sibling)] == b'{"keep":true}'


def test_bucket_rejects_path_escape() -> None:
    fake = FakeS3Client()
    store = BucketObjectStore(fake, "models-test")
    with pytest.raises(ValueError, match="relative POSIX"):
        store.put("/etc/passwd", b"secret")
    with pytest.raises(ValueError, match=r"\.\."):
        store.put("../escape.bin", b"secret")
    with pytest.raises(ValueError, match=r"\.\."):
        store.delete_prefix("projects/../outside")
    assert fake.objects == {}
