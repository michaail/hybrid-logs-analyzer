"""E2E package generation must run in the slim CI environment (no pytest)."""

from __future__ import annotations

import ast
from pathlib import Path

_FORBIDDEN_MODULES = {
    "pytest",
    "tests.test_model_package",
    "tests.test_inference_bundle",
}


def test_e2e_package_builder_does_not_import_pytest_test_modules() -> None:
    for path in (
        Path("scripts/e2e_package.py"),
        Path("tests/support/hdfs_v2_release.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name not in _FORBIDDEN_MODULES, f"{path} imports {name}"
                assert not name.startswith("pytest."), f"{path} imports {name}"
