"""Build a harmless HDFS model-package ZIP for Playwright E2E.

Rewrites only identity fields on the committed ``valid_files`` fixture. Never
loads or executes ``model.pt``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID_FILES = ROOT / "tests" / "fixtures" / "model_packages" / "valid_files"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_package(*, kind: str, identifier: str, version: str, output: Path) -> Path:
    if kind not in {"eligible", "ineligible"}:
        raise SystemExit("kind must be eligible or ineligible")
    if not VALID_FILES.is_dir():
        raise SystemExit(f"Missing fixture directory: {VALID_FILES}")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="e2e-package-") as tmp:
        staging = Path(tmp) / "package"
        shutil.copytree(VALID_FILES, staging)
        manifest_path = staging / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["model_identifier"] = identifier
        payload["version"] = version
        if kind == "ineligible":
            evidence_path = staging / "evidence.json"
            evidence_path.write_text("{}", encoding="utf-8")
            payload["files"]["checksums"]["evidence.json"] = _sha256(evidence_path)
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        with zipfile.ZipFile(output, "w") as archive:
            for file in staging.rglob("*"):
                if file.is_file():
                    archive.write(file, file.relative_to(staging).as_posix())
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write an E2E HDFS model-package ZIP.")
    parser.add_argument("--kind", choices=("eligible", "ineligible"), required=True)
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    path = build_package(
        kind=arguments.kind,
        identifier=arguments.identifier,
        version=arguments.version,
        output=Path(arguments.output),
    )
    sys.stdout.write(str(path) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
