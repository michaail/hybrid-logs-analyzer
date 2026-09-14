"""Harmless v2 HDFS package/bundle writers shared by contract tests and Playwright E2E.

This module must stay pytest-free. The E2E job installs ``requirements-e2e.txt``
(API deps + numpy) and generates ZIPs from ``scripts/e2e_package.py``.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

from src.modules.inference_bundle import (
    BUNDLE_FORMAT,
    DRAIN_CONFIG_NAME,
    DRAIN_PARSER_NAME,
    EMBEDDINGS_NAME,
    NODE_FEATURE_EXTRA_DIM,
    bundle_digest,
)
from src.modules.model_package import MANIFEST_NAME, PACKAGE_FORMAT_V2

TINY_ARCHITECTURE = {
    "node_dim": 2,
    "edge_dim": 1,
    "hidden_dim": 2,
    "latent_dim": 2,
    "gine_aggregation": "sum",
    "node_transformation": "mlp",
    "edge_mean": [0.0],
    "edge_std": [0.2],
}
DEFAULT_PREPROCESSING_BUNDLE = {
    "identifier": "attribute-gae-preprocessing",
    "version": "v2",
    "digest": "a" * 64,
}
V2_ARCHITECTURE = {
    **TINY_ARCHITECTURE,
    "node_dim": 2 + NODE_FEATURE_EXTRA_DIM,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_identifier": "attribute-gae",
        "version": "v1",
        "source_compatibility": "hdfs",
        "format": PACKAGE_FORMAT_V2,
        "metrics": {"best_threshold": 0.147, "test_roc_auc": 0.97},
        "architecture": dict(TINY_ARCHITECTURE),
        "scoring": {"alpha": 1.0, "beta": 1.0, "gamma": 0.0},
        "files": {
            "artifact": "model.pt",
            "evidence": "evidence.json",
            "checksums": {},
        },
        "preprocessing_bundle": dict(DEFAULT_PREPROCESSING_BUNDLE),
    }
    payload.update(overrides)
    return payload


def _write_package(
    root: Path,
    *,
    manifest: dict[str, Any] | None = None,
    artifact: bytes = b"dummy-artifact",
    evidence: dict[str, Any] | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    package = root / "package"
    package.mkdir(parents=True, exist_ok=True)
    evidence_payload = {"evaluation": "notebook baseline", "status": "passed"}
    if evidence is not None:
        evidence_payload = evidence
    artifact_bytes = artifact
    evidence_bytes = json.dumps(evidence_payload).encode("utf-8")
    (package / "model.pt").write_bytes(artifact_bytes)
    (package / "evidence.json").write_text(json.dumps(evidence_payload), encoding="utf-8")
    payload = _manifest_payload() if manifest is None else manifest
    files = dict(payload["files"])
    files["checksums"] = {
        files["artifact"]: _sha256(artifact_bytes),
        files["evidence"]: _sha256(evidence_bytes),
    }
    payload = {**payload, "files": files}
    (package / MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")
    for name, content in (extra_files or {}).items():
        extra_path = package / name
        extra_path.parent.mkdir(parents=True, exist_ok=True)
        extra_path.write_bytes(content)
    return package


def _embeddings_bytes(
    *,
    cluster_ids: list[int] | None = None,
    width: int = 2,
    values: Any = None,
) -> bytes:
    import numpy as np

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


def _v2_package(root: Path, digest: str, **package_kwargs: Any) -> Path:
    manifest = {
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
    }
    if "manifest" in package_kwargs:
        return _write_package(root, **package_kwargs)
    return _write_package(root, manifest=manifest, **package_kwargs)
