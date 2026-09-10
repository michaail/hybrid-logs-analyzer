"""Filesystem object-store tests. Non-ML tests never import Torch."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID

import pytest

from src.api.object_store import (
    FilesystemObjectStore,
    model_package_object_key,
    model_package_object_prefix,
)
from src.api.settings import ApiSettings


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


def test_object_store_root_defaults_and_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        jwt_secret="test-secret-not-for-production",
        trusted_workspace_root=tmp_path / "workspace",
    )
    assert settings.object_store_root == Path(".api/objects")

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
