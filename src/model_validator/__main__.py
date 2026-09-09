"""CLI entry for the isolated model-package validator."""

from __future__ import annotations

import sys
from pathlib import Path

from src.model_validator.runtime import (
    report_json,
    scrub_environment,
    validate_package_with_probe,
)


def main(argv: list[str] | None = None) -> int:
    """Validate one package directory and print a typed JSON report."""

    scrub_environment()
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        sys.stderr.write("usage: python -m src.model_validator <package-root>\n")
        return 2
    result = validate_package_with_probe(Path(arguments[0]))
    sys.stdout.write(report_json(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
