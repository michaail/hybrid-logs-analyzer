"""Isolated package-validation process. This is the only admission Torch loader."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.modules.model_package import PackageValidationResult, validate_model_package

_ALLOWED_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "TMPDIR",
        "TEMP",
        "TMP",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "PYTHONHOME",
        "PYTHONNOUSERSITE",
        "PYTHONSAFEPATH",
        "USER",
        "LOGNAME",
        "TZ",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
)


def allowed_validator_environment(
    environ: Mapping[str, str] | None = None,
    *,
    code_root: Path | None = None,
) -> dict[str, str]:
    """Return a copy of environ containing only variables the validator may see."""

    source = os.environ if environ is None else environ
    env = {key: value for key, value in source.items() if key in _ALLOWED_ENV_KEYS}
    if code_root is not None:
        pythonpath = str(code_root.resolve())
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = pythonpath if not existing else pythonpath + os.pathsep + existing
    return env


def scrub_environment(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Drop every variable the validator process is not allowed to keep."""

    target = os.environ if environ is None else environ
    allowed = allowed_validator_environment(target)
    removed: dict[str, str] = {}
    for key in list(target):
        if key not in allowed:
            removed[key] = target.pop(key)
    return removed


def load_tensor_state_dict(path: Path) -> Mapping[str, Any]:
    """Load a tensor-only state dict. Never use weights_only=False."""

    import torch

    payload = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(payload, dict):
        raise TypeError("Artifact payload must be a mapping.")
    return payload


def validate_package_with_probe(root: Path) -> PackageValidationResult:
    """Validate a directory package including the restricted tensor probe."""

    return validate_model_package(root, load_state_dict=load_tensor_state_dict)


def report_json(result: PackageValidationResult) -> str:
    """Serialize a typed validation report for the control plane."""

    return json.dumps(result.model_dump(), indent=2, sort_keys=True)
