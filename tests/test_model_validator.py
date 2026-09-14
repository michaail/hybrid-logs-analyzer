"""Isolated package-validation process tests."""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.model_validator.runtime import report_json, scrub_environment
from src.model_validator.service import create_app
from src.model_validator.settings import ValidatorSettings
from src.modules.model_package import PackageValidationIssue, PackageValidationResult
from tests.test_model_package import _write_package

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_TOKEN = "validator-test-token"
_FORBIDDEN_VALIDATOR_ENV = (
    "API_JWT_SECRET",
    "DATABASE_URL",
    "API_OBJECT_STORE_ENDPOINT",
    "API_OBJECT_STORE_BUCKET",
    "API_OBJECT_STORE_ACCESS_KEY_ID",
    "API_OBJECT_STORE_SECRET_ACCESS_KEY",
)


def _import_nodes(path: Path) -> list[ast.AST]:
    return list(ast.walk(ast.parse(path.read_text(encoding="utf-8"))))


def test_model_package_and_api_sources_do_not_import_torch() -> None:
    for path in (
        Path("src/modules/model_package.py"),
        Path("src/modules/inference_bundle.py"),
        Path("src/api/main.py"),
        Path("src/api/validation.py"),
        Path("src/api/validator_client.py"),
    ):
        for node in _import_nodes(path):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name != "torch" and not alias.name.startswith("torch.")
                    for alias in node.names
                )
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("torch")


def test_importing_model_package_does_not_load_torch() -> None:
    script = (
        "import sys; "
        "from src.modules import model_package; "
        "assert 'torch' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
    )
    assert completed.returncode == 0, completed.stderr


def test_scrub_environment_removes_application_secrets() -> None:
    environ = {
        "API_JWT_SECRET": "secret",
        "DATABASE_URL": "sqlite:///tmp.db",
        "AZURE_OPENAI_API_KEY": "azure",
        "AWS_SECRET_ACCESS_KEY": "aws",
        "AWS_ACCESS_KEY_ID": "aws-id",
        "API_OBJECT_STORE_SECRET_ACCESS_KEY": "bucket-secret",
        "API_OBJECT_STORE_ACCESS_KEY_ID": "bucket-id",
        "PATH": "/usr/bin",
        "SAFE_FLAG": "drop-me",
    }
    removed = scrub_environment(environ)
    assert "API_JWT_SECRET" in removed
    assert "AZURE_OPENAI_API_KEY" in removed
    assert "AWS_SECRET_ACCESS_KEY" in removed
    assert "AWS_ACCESS_KEY_ID" in removed
    assert "API_OBJECT_STORE_SECRET_ACCESS_KEY" in removed
    assert "API_OBJECT_STORE_ACCESS_KEY_ID" in removed
    assert "DATABASE_URL" not in environ
    assert "SAFE_FLAG" not in environ
    assert environ["PATH"] == "/usr/bin"


def test_report_json_is_typed_and_stable() -> None:
    result = PackageValidationResult.from_issues(
        [PackageValidationIssue(path="manifest.json", reason="broken")]
    )
    payload = json.loads(report_json(result))
    assert payload == {
        "issues": [{"path": "manifest.json", "reason": "broken"}],
        "valid": False,
    }


def test_validator_process_prints_typed_report_for_invalid_package(tmp_path: Path) -> None:
    package = _write_package(tmp_path, manifest=None)
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["source_compatibility"] = "bgl"
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["API_JWT_SECRET"] = "must-be-stripped"
    completed = subprocess.run(
        [sys.executable, "-m", "src.model_validator", str(package)],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["valid"] is False
    assert payload["issues"]
    assert all("path" in issue and "reason" in issue for issue in payload["issues"])


def test_validator_process_accepts_optional_bundle_root(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [sys.executable, "-m", "src.model_validator", str(package), str(tmp_path / "missing-bundle")],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["valid"] is False
    assert payload["issues"]


def _zip_directory(root: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for file in root.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(root).as_posix())
    return buffer.getvalue()


def _validator_client(token: str = VALIDATOR_TOKEN) -> TestClient:
    return TestClient(create_app(ValidatorSettings(internal_token=token)))


def _validate_zips(
    client: TestClient,
    package_bytes: bytes,
    bundle_bytes: bytes,
    *,
    token: str | None = VALIDATOR_TOKEN,
):
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/internal/packages/validate",
        headers=headers,
        files={
            "package": ("package.zip", package_bytes, "application/zip"),
            "preprocessing_bundle": ("bundle.zip", bundle_bytes, "application/zip"),
        },
    )


def _v2_release_zips(workspace: Path, **package_kwargs: object) -> tuple[bytes, bytes]:
    from tests.test_inference_bundle import _v2_package, _write_bundle

    bundle_dir = _write_bundle(workspace)
    digest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))["digest"]
    package_dir = _v2_package(workspace, digest, **package_kwargs)
    return _zip_directory(package_dir), _zip_directory(bundle_dir)


def test_validator_health_does_not_require_a_token() -> None:
    client = _validator_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_validator_http_rejects_missing_token(tmp_path: Path) -> None:
    client = _validator_client()
    package_zip, bundle_zip = _v2_release_zips(tmp_path)
    response = _validate_zips(client, package_zip, bundle_zip, token=None)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid validator token."


def test_validator_http_rejects_wrong_token(tmp_path: Path) -> None:
    client = _validator_client()
    package_zip, bundle_zip = _v2_release_zips(tmp_path)
    response = _validate_zips(client, package_zip, bundle_zip, token="wrong-token")
    assert response.status_code == 401


def test_validator_http_returns_typed_invalid_for_v1_oracle(tmp_path: Path) -> None:
    from tests.test_inference_bundle import _write_bundle

    client = _validator_client()
    package_zip = _zip_directory(REPO_ROOT / "tests" / "fixtures" / "model_packages" / "rejected_v1")
    bundle_zip = _zip_directory(_write_bundle(tmp_path))
    response = _validate_zips(client, package_zip, bundle_zip)
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert payload["issues"]
    assert all("path" in issue and "reason" in issue for issue in payload["issues"])


def test_validator_http_returns_typed_invalid_for_empty_evidence(tmp_path: Path) -> None:
    client = _validator_client()
    package_zip, bundle_zip = _v2_release_zips(tmp_path, evidence={})
    response = _validate_zips(client, package_zip, bundle_zip)
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert any("evidence" in issue["path"] for issue in payload["issues"])


def test_validator_http_valid_true_when_probe_is_stubbed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.model_validator.service.validate_release_with_probe",
        lambda package_root, bundle_root=None: PackageValidationResult.from_issues([]),
    )
    client = _validator_client()
    package_zip, bundle_zip = _v2_release_zips(tmp_path)
    response = _validate_zips(client, package_zip, bundle_zip)
    assert response.status_code == 200
    assert response.json() == {"valid": True, "issues": []}


def test_validator_settings_reject_application_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _FORBIDDEN_VALIDATOR_ENV:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("MODEL_VALIDATOR_INTERNAL_TOKEN", "tok")
    loaded = ValidatorSettings.from_environment()
    assert loaded.internal_token == "tok"

    monkeypatch.setenv("API_JWT_SECRET", "jwt-secret")
    with pytest.raises(RuntimeError, match="must not receive"):
        ValidatorSettings.from_environment()


def test_validator_settings_require_internal_token(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _FORBIDDEN_VALIDATOR_ENV:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("MODEL_VALIDATOR_INTERNAL_TOKEN", "")
    with pytest.raises(RuntimeError, match="MODEL_VALIDATOR_INTERNAL_TOKEN"):
        ValidatorSettings.from_environment()


@pytest.mark.ml
def test_validator_app_probes_real_state_dict(tmp_path: Path) -> None:
    import torch

    from src.modules.model_package import PackageArchitecture, expected_state_dict_spec
    from tests.test_inference_bundle import V2_ARCHITECTURE

    architecture = PackageArchitecture.model_validate(V2_ARCHITECTURE)
    payload = {
        key: torch.zeros(spec.shape, dtype=torch.int64 if "int64" in spec.dtypes else torch.float32)
        for key, spec in expected_state_dict_spec(architecture).items()
    }
    artifact = tmp_path / "valid.pt"
    torch.save(payload, artifact)
    package_zip, bundle_zip = _v2_release_zips(tmp_path, artifact=artifact.read_bytes())
    client = _validator_client()
    response = _validate_zips(client, package_zip, bundle_zip)
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is True
    assert response.json()["issues"] == []
