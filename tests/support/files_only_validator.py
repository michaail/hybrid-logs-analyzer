"""Directory-contract validator used by Torch-free API tests. Never imports Torch."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.modules.inference_bundle import validate_packaged_release


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) not in {1, 2}:
        sys.stderr.write("usage: files_only_validator.py <package-root> [bundle-root]\n")
        return 2
    bundle_root = Path(arguments[1]) if len(arguments) == 2 else None
    result = validate_packaged_release(Path(arguments[0]), bundle_root)
    sys.stdout.write(json.dumps(result.model_dump(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
