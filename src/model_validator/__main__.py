"""CLI entry for the isolated model-package validator."""

from __future__ import annotations

import sys
from pathlib import Path

from src.model_validator.runtime import (
    report_json,
    scrub_environment,
    validate_release_with_probe,
)


def main(argv: list[str] | None = None) -> int:
    """Validate a package directory and optional bundle directory."""

    scrub_environment()
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) not in {1, 2}:
        sys.stderr.write("usage: python -m src.model_validator <package-root> [bundle-root]\n")
        return 2
    bundle_root = Path(arguments[1]) if len(arguments) == 2 else None
    result = validate_release_with_probe(Path(arguments[0]), bundle_root)
    sys.stdout.write(report_json(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
