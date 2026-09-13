"""Build harmless HDFS model-package and preprocessing-bundle ZIPs for Playwright E2E.

Rewrites only identity fields. Never loads or executes ``model.pt``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_inference_bundle import _v2_package, _write_bundle  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _zip_directory(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        for file in source.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(source).as_posix())


def build_release(
    *,
    kind: str,
    identifier: str,
    version: str,
    package_output: Path,
    bundle_output: Path,
) -> tuple[Path, Path]:
    if kind not in {"eligible", "ineligible"}:
        raise SystemExit("kind must be eligible or ineligible")

    with tempfile.TemporaryDirectory(prefix="e2e-release-") as tmp:
        staging = Path(tmp)
        bundle_identifier = f"{identifier}-preprocessing"
        bundle_dir = _write_bundle(
            staging,
            manifest_overrides={"identifier": bundle_identifier, "version": version},
        )
        digest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))["digest"]
        package_dir = _v2_package(staging, digest)
        manifest_path = package_dir / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["model_identifier"] = identifier
        payload["version"] = version
        payload["preprocessing_bundle"] = {
            "identifier": bundle_identifier,
            "version": version,
            "digest": digest,
        }
        if kind == "ineligible":
            evidence_path = package_dir / "evidence.json"
            evidence_path.write_text("{}", encoding="utf-8")
            payload["files"]["checksums"]["evidence.json"] = _sha256(evidence_path)
        manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _zip_directory(package_dir, package_output.resolve())
        _zip_directory(bundle_dir, bundle_output.resolve())
    return package_output.resolve(), bundle_output.resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write E2E HDFS model-package and preprocessing-bundle ZIPs."
    )
    parser.add_argument("--kind", choices=("eligible", "ineligible"), required=True)
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, help="Package ZIP path.")
    parser.add_argument("--bundle-output", required=True, help="Bundle ZIP path.")
    arguments = parser.parse_args(argv)
    package_path, bundle_path = build_release(
        kind=arguments.kind,
        identifier=arguments.identifier,
        version=arguments.version,
        package_output=Path(arguments.output),
        bundle_output=Path(arguments.bundle_output),
    )
    sys.stdout.write(f"{package_path}\n{bundle_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
