"""Test double that adds a tensor-probe failure without importing Torch."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.modules.model_package import (
    PackageValidationIssue,
    PackageValidationResult,
    validate_model_package,
)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        sys.stderr.write("usage: rejecting_artifact_validator.py <package-root>\n")
        return 2
    result = validate_model_package(Path(arguments[0]))
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
