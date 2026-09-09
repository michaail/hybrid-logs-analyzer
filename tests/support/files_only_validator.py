"""Directory-contract validator used by Torch-free API tests. Never imports Torch."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.modules.model_package import validate_model_package


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        sys.stderr.write("usage: files_only_validator.py <package-root>\n")
        return 2
    result = validate_model_package(Path(arguments[0]))
    sys.stdout.write(json.dumps(result.model_dump(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
