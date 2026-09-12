"""Isolated package-validation process tests."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from src.model_validator.runtime import report_json, scrub_environment
from src.modules.model_package import PackageValidationIssue, PackageValidationResult
from tests.test_model_package import _write_package


def _import_nodes(path: Path) -> list[ast.AST]:
    return list(ast.walk(ast.parse(path.read_text(encoding="utf-8"))))


def test_model_package_and_api_sources_do_not_import_torch() -> None:
    for path in (
        Path("src/modules/model_package.py"),
        Path("src/modules/inference_bundle.py"),
        Path("src/api/main.py"),
        Path("src/api/validation.py"),
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
