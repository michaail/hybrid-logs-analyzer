"""Test double that adds a tensor-probe failure without importing Torch."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.modules.inference_bundle import validate_packaged_release
from src.modules.model_package import (
    PackageValidationIssue,
    PackageValidationResult,
)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) not in {1, 2}:
        sys.stderr.write("usage: rejecting_artifact_validator.py <package-root> [bundle-root]\n")
        return 2
    bundle_root = Path(arguments[1]) if len(arguments) == 2 else None
    result = validate_packaged_release(Path(arguments[0]), bundle_root)
    issues = list(result.issues)
    issues.append(
        PackageValidationIssue(
            path="model.pt",
            reason="Artifact must load as a weights_only tensor state dict.",
        )
    )
    sys.stdout.write(
        json.dumps(PackageValidationResult.from_issues(issues).model_dump(), indent=2, sort_keys=True)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
