"""Preprocessing-bundle contract tests. Non-ML tests never import Torch."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from src.modules.inference_bundle import (
    BUNDLE_FORMAT,
    DRAIN_CONFIG_NAME,
    DRAIN_PARSER_NAME,
    EMBEDDINGS_NAME,
    NODE_FEATURE_EXTRA_DIM,
    bundle_digest,
    validate_packaged_release,
    validate_preprocessing_bundle,
    validate_preprocessing_bundle_source,
)
from src.modules.model_package import MANIFEST_NAME, PACKAGE_FORMAT_V2, PackageArchitecture
from tests.test_model_package import TINY_ARCHITECTURE, _assert_has_issue, _write_package

V2_ARCHITECTURE = {
    **TINY_ARCHITECTURE,
    "node_dim": 2 + NODE_FEATURE_EXTRA_DIM,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _embeddings_bytes(
    *,
    cluster_ids: list[int] | None = None,
    width: int = 2,
    values: np.ndarray | None = None,
) -> bytes:
    ids = np.asarray(cluster_ids if cluster_ids is not None else [1, 2], dtype=np.int64)
    vectors = values if values is not None else np.ones((ids.size, width), dtype=np.float32)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, cluster_ids=ids, embeddings=vectors)
    return buffer.getvalue()


def _bundle_manifest(checksums: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "identifier": "attribute-gae-preprocessing",
        "version": "v2",
        "source_compatibility": "hdfs",
        "format": BUNDLE_FORMAT,
        "digest": bundle_digest(checksums),
        "files": {
            "drain_config": DRAIN_CONFIG_NAME,
            "drain_parser": DRAIN_PARSER_NAME,
            "embeddings": EMBEDDINGS_NAME,
            "checksums": checksums,
        },
    }
    payload.update(overrides)
    return payload


def _write_bundle(
    root: Path,
    *,
    embeddings: bytes | None = None,
    extra_files: dict[str, bytes] | None = None,
    checksum_override: dict[str, str] | None = None,
    manifest_overrides: dict[str, Any] | None = None,
) -> Path:
    bundle = root / "bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    drain_config = b"[DRAIN]\nst=0.4\n"
    drain_parser = b"drain-state"
    embeddings_bytes = embeddings if embeddings is not None else _embeddings_bytes()
    (bundle / DRAIN_CONFIG_NAME).write_bytes(drain_config)
    (bundle / DRAIN_PARSER_NAME).write_bytes(drain_parser)
    (bundle / EMBEDDINGS_NAME).write_bytes(embeddings_bytes)
    checksums = {
        DRAIN_CONFIG_NAME: _sha256(drain_config),
        DRAIN_PARSER_NAME: _sha256(drain_parser),
        EMBEDDINGS_NAME: _sha256(embeddings_bytes),
    }
    if checksum_override:
        checksums.update(checksum_override)
    payload = _bundle_manifest(checksums, **(manifest_overrides or {}))
    if checksum_override and "digest" not in (manifest_overrides or {}):
        payload["digest"] = bundle_digest(checksums)
    (bundle / MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")
    for name, content in (extra_files or {}).items():
        extra_path = bundle / name
        extra_path.parent.mkdir(parents=True, exist_ok=True)
        extra_path.write_bytes(content)
    return bundle


def _v2_package(root: Path, digest: str) -> Path:
    return _write_package(
        root,
        manifest={
            "model_identifier": "attribute-gae",
            "version": "v2",
            "source_compatibility": "hdfs",
            "format": PACKAGE_FORMAT_V2,
            "metrics": {"best_threshold": 0.147},
            "architecture": dict(V2_ARCHITECTURE),
            "scoring": {"alpha": 1.0, "beta": 1.0, "gamma": 0.0},
            "files": {"artifact": "model.pt", "evidence": "evidence.json", "checksums": {}},
            "preprocessing_bundle": {
                "identifier": "attribute-gae-preprocessing",
                "version": "v2",
                "digest": digest,
            },
        },
    )


def test_inference_bundle_source_does_not_import_torch() -> None:
    source = Path("src/modules/inference_bundle.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "torch" and not alias.name.startswith("torch.") for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("torch")


def test_valid_bundle_is_accepted(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    architecture = PackageArchitecture.model_validate(V2_ARCHITECTURE)
    result = validate_preprocessing_bundle(bundle, architecture=architecture)
    assert result.valid, [issue.model_dump() for issue in result.issues]


def test_undeclared_bundle_file_is_rejected(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, extra_files={"leftover.bin": b"nope"})
    result = validate_preprocessing_bundle(bundle)
    assert not result.valid
    _assert_has_issue(result, "leftover.bin")


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, checksum_override={DRAIN_CONFIG_NAME: "0" * 64})
    result = validate_preprocessing_bundle(bundle)
    assert not result.valid
    _assert_has_issue(result, DRAIN_CONFIG_NAME)


def test_symlink_member_is_rejected(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    target = bundle / DRAIN_PARSER_NAME
    real = bundle / "real.bin"
    target.replace(real)
    target.symlink_to(real.name)
    result = validate_preprocessing_bundle(bundle)
    assert not result.valid
    _assert_has_issue(result, "regular file")


def test_path_escape_declared_name_is_rejected(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    payload = json.loads((bundle / MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["files"]["drain_config"] = "../escape.ini"
    payload["files"]["checksums"]["../escape.ini"] = payload["files"]["checksums"].pop(DRAIN_CONFIG_NAME)
    (bundle / MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")
    result = validate_preprocessing_bundle(bundle)
    assert not result.valid
    _assert_has_issue(result, "..")


def test_pickle_npz_is_rejected(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    np.savez(buffer, cluster_ids=np.array([1]), embeddings=np.array([[1.0, 1.0]]), obj=np.array([{"x": 1}], dtype=object))
    bundle = _write_bundle(tmp_path, embeddings=buffer.getvalue())
    result = validate_preprocessing_bundle(bundle)
    assert not result.valid
    _assert_has_issue(result, EMBEDDINGS_NAME)


def test_non_finite_embeddings_are_rejected(tmp_path: Path) -> None:
    values = np.array([[1.0, np.nan], [1.0, 1.0]], dtype=np.float32)
    bundle = _write_bundle(tmp_path, embeddings=_embeddings_bytes(values=values))
    result = validate_preprocessing_bundle(bundle)
    assert not result.valid
    _assert_has_issue(result, "finite")


def test_duplicate_cluster_ids_are_rejected(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, embeddings=_embeddings_bytes(cluster_ids=[1, 1]))
    result = validate_preprocessing_bundle(bundle)
    assert not result.valid
    _assert_has_issue(result, "unique")


def test_dimension_mismatch_is_rejected(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, embeddings=_embeddings_bytes(width=4))
    architecture = PackageArchitecture.model_validate(V2_ARCHITECTURE)
    result = validate_preprocessing_bundle(bundle, architecture=architecture)
    assert not result.valid
    _assert_has_issue(result, "node_dim")


def test_zip_slip_bundle_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "slip.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escaped.bin", b"pwned")
    result = validate_preprocessing_bundle_source(archive)
    assert not result.valid
    _assert_has_issue(result, "..")
    written = {path.name for path in tmp_path.rglob("*") if path.is_file()}
    assert written == {"slip.zip"}


def test_v1_package_rejects_companion_bundle(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    bundle = _write_bundle(tmp_path)
    result = validate_packaged_release(package, bundle)
    assert not result.valid
    _assert_has_issue(result, "preprocessing_bundle")


def test_v2_package_requires_matching_bundle(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    digest = json.loads((bundle / MANIFEST_NAME).read_text(encoding="utf-8"))["digest"]
    package = _v2_package(tmp_path, digest)
    result = validate_packaged_release(package, bundle)
    assert result.valid, [issue.model_dump() for issue in result.issues]


def test_v2_package_without_bundle_is_rejected(tmp_path: Path) -> None:
    package = _v2_package(tmp_path, "a" * 64)
    result = validate_packaged_release(package)
    assert not result.valid
    _assert_has_issue(result, "preprocessing_bundle")


def test_swapped_bundle_digest_is_rejected(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    package = _v2_package(tmp_path, "b" * 64)
    result = validate_packaged_release(package, bundle)
    assert not result.valid
    _assert_has_issue(result, "digest")
