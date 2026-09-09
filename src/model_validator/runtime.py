"""Isolated package-validation process. This is the only admission Torch loader."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.modules.model_package import PackageValidationResult, validate_model_package

_SECRET_ENV_NAMES = frozenset(
    {
        "API_JWT_SECRET",
        "DATABASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "BUCKET_ACCESS_KEY_ID",
        "BUCKET_SECRET_ACCESS_KEY",
        "RAILWAY_TOKEN",
    }
)
_SECRET_ENV_PREFIXES = ("API_", "AWS_", "RAILWAY_", "BUCKET_")


def scrub_environment(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Remove application and object-storage secrets from a process environment."""

    target = os.environ if environ is None else environ
    removed: dict[str, str] = {}
    for key in list(target):
        if key in _SECRET_ENV_NAMES or key.startswith(_SECRET_ENV_PREFIXES):
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
