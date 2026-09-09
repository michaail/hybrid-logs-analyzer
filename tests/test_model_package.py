"""Directory HDFS model-package contract tests. Non-ML tests never import Torch."""

from __future__ import annotations

import ast
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from src.modules.model_package import (
    MANIFEST_NAME,
    MAX_ZIP_COMPRESSED_BYTES,
    MAX_ZIP_UNCOMPRESSED_BYTES,
    PackageArchitecture,
    expected_state_dict_spec,
    validate_model_package,
    validate_model_package_source,
    validate_state_dict,
)

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


class FakeTensor:
    """Duck-typed tensor used by non-ML state-dict schema tests."""

    def __init__(self, shape: tuple[int, ...], dtype: str = "float32") -> None:
        self.shape = shape
        self.dtype = dtype


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_identifier": "attribute-gae",
        "version": "v1",
        "source_compatibility": "hdfs",
        "format": "attribute-aware-gae-v1",
        "metrics": {"best_threshold": 0.147, "test_roc_auc": 0.97},
        "architecture": dict(TINY_ARCHITECTURE),
        "scoring": {"alpha": 1.0, "beta": 1.0, "gamma": 0.0},
        "files": {
            "artifact": "model.pt",
            "evidence": "evidence.json",
            "checksums": {},
        },
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


def _complete_state_dict(
    architecture: PackageArchitecture | None = None,
    *,
    extra: dict[str, FakeTensor] | None = None,
    drop: set[str] | None = None,
    replace: dict[str, FakeTensor] | None = None,
) -> dict[str, FakeTensor]:
    spec_architecture = architecture or PackageArchitecture.model_validate(TINY_ARCHITECTURE)
    payload = {
        key: FakeTensor(spec.shape, next(iter(spec.dtypes)))
        for key, spec in expected_state_dict_spec(spec_architecture).items()
    }
    if extra:
        payload.update(extra)
    if replace:
        payload.update(replace)
    for key in drop or set():
        payload.pop(key, None)
    return payload


def _assert_has_issue(result: Any, fragment: str) -> None:
    haystacks = [issue.path + " " + issue.reason for issue in result.issues]
    assert any(fragment in item for item in haystacks), haystacks


def test_model_package_source_does_not_import_torch() -> None:
    source = Path("src/modules/model_package.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "torch" and not alias.name.startswith("torch.") for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("torch")


def test_extra_undeclared_files_are_accepted(tmp_path: Path) -> None:
    package = _write_package(tmp_path, extra_files={"leftover.bin": b"ignore-me"})
    result = validate_model_package(package)
    leftover_issues = [issue for issue in result.issues if "leftover" in issue.path]
    assert leftover_issues == []
    assert result.valid


def test_extra_manifest_keys_are_rejected(tmp_path: Path) -> None:
    payload = _manifest_payload(unexpected="nope")
    package = _write_package(tmp_path, manifest=payload)
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, MANIFEST_NAME)


def test_missing_manifest_is_reported(tmp_path: Path) -> None:
    package = tmp_path / "empty"
    package.mkdir()
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, MANIFEST_NAME)


def test_non_hdfs_compatibility_is_rejected(tmp_path: Path) -> None:
    payload = _manifest_payload(source_compatibility="bgl")
    package = _write_package(tmp_path, manifest=payload)
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "source_compatibility")


def test_missing_threshold_is_rejected(tmp_path: Path) -> None:
    payload = _manifest_payload(metrics={"test_roc_auc": 0.9})
    package = _write_package(tmp_path, manifest=payload)
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "best_threshold")


def test_non_finite_threshold_is_rejected(tmp_path: Path) -> None:
    payload = _manifest_payload(metrics={"best_threshold": float("nan")})
    package = _write_package(tmp_path, manifest=payload)
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "best_threshold")


def test_path_escape_in_declared_name_is_rejected(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["files"] = {
        "artifact": "../escape.pt",
        "evidence": "evidence.json",
        "checksums": {},
    }
    package = _write_package(tmp_path, manifest=payload)
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "..")


def test_sha256_mismatch_is_rejected(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    manifest_path = package / MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"]["checksums"]["model.pt"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "model.pt")


def test_declared_symlink_is_rejected(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    target = package / "model.pt"
    real = package / "real.pt"
    target.replace(real)
    target.symlink_to(real.name)
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "regular file")


def test_missing_declared_file_is_rejected(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    (package / "model.pt").unlink()
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "model.pt")


def test_empty_evidence_object_is_rejected(tmp_path: Path) -> None:
    package = _write_package(tmp_path, evidence={})
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "evidence.json")


def test_inconsistent_normalization_vectors_are_rejected(tmp_path: Path) -> None:
    architecture = dict(TINY_ARCHITECTURE)
    architecture["edge_mean"] = [0.0]
    architecture["edge_std"] = None
    package = _write_package(tmp_path, manifest=_manifest_payload(architecture=architecture))
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "architecture")


def test_invalid_scoring_weights_are_rejected(tmp_path: Path) -> None:
    package = _write_package(
        tmp_path,
        manifest=_manifest_payload(scoring={"alpha": 0.0, "beta": 0.0, "gamma": 0.0}),
    )
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "scoring")


def test_artifact_suffix_must_be_pt(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["files"] = {"artifact": "model.bin", "evidence": "evidence.json", "checksums": {}}
    package = _write_package(tmp_path, manifest=payload)
    (package / "model.bin").write_bytes(b"dummy-artifact")
    result = validate_model_package(package)
    assert not result.valid
    _assert_has_issue(result, "files.artifact")


def test_mlp_and_linear_state_dict_schemas_accept_complete_tensors() -> None:
    mlp = PackageArchitecture.model_validate(TINY_ARCHITECTURE)
    linear_payload = dict(TINY_ARCHITECTURE)
    linear_payload["node_transformation"] = "linear"
    linear = PackageArchitecture.model_validate(linear_payload)
    assert validate_state_dict(_complete_state_dict(mlp), mlp) == []
    assert validate_state_dict(_complete_state_dict(linear), linear) == []


def test_missing_unexpected_wrong_shape_and_dtype_tensors_are_rejected() -> None:
    architecture = PackageArchitecture.model_validate(TINY_ARCHITECTURE)
    missing = validate_state_dict(_complete_state_dict(drop={"node_proj.weight"}), architecture)
    unexpected = validate_state_dict(
        _complete_state_dict(extra={"bonus": FakeTensor((1,), "float32")}),
        architecture,
    )
    wrong_shape = validate_state_dict(
        _complete_state_dict(replace={"node_proj.bias": FakeTensor((8,), "float32")}),
        architecture,
    )
    wrong_dtype = validate_state_dict(
        _complete_state_dict(replace={"node_proj.bias": FakeTensor((2,), "int64")}),
        architecture,
    )
    assert any("node_proj.weight" in issue.path for issue in missing)
    assert any("bonus" in issue.path for issue in unexpected)
    assert any("node_proj.bias" in issue.path for issue in wrong_shape)
    assert any("node_proj.bias" in issue.path for issue in wrong_dtype)


def _torch_state_dict(architecture: PackageArchitecture) -> dict[str, Any]:
    import torch

    payload: dict[str, Any] = {}
    for key, spec in expected_state_dict_spec(architecture).items():
        dtype = torch.int64 if "int64" in spec.dtypes else torch.float32
        payload[key] = torch.zeros(spec.shape, dtype=dtype)
    return payload


@pytest.mark.ml
def test_weights_only_probe_accepts_tensor_state_dict(tmp_path: Path) -> None:
    import torch

    from src.model_validator.runtime import load_tensor_state_dict

    architecture = PackageArchitecture.model_validate(TINY_ARCHITECTURE)
    artifact = tmp_path / "model.pt"
    torch.save(_torch_state_dict(architecture), artifact)
    package = _write_package(tmp_path / "ok", artifact=artifact.read_bytes())
    result = validate_model_package(package, load_state_dict=load_tensor_state_dict)
    assert result.valid, [issue.model_dump() for issue in result.issues]


@pytest.mark.ml
def test_weights_only_probe_rejects_pickle_payload(tmp_path: Path) -> None:
    import pickle

    from src.model_validator.runtime import load_tensor_state_dict

    class Boom:
        def __reduce__(self) -> tuple[Any, tuple[str]]:
            return exec, ("raise RuntimeError('pickle-executed')",)

    artifact = tmp_path / "evil.pt"
    artifact.write_bytes(pickle.dumps(Boom()))
    package = _write_package(tmp_path / "bad", artifact=artifact.read_bytes())
    result = validate_model_package(package, load_state_dict=load_tensor_state_dict)
    assert not result.valid
    _assert_has_issue(result, "model.pt")


def _zip_directory(source: Path, dest: Path) -> Path:
    with zipfile.ZipFile(dest, "w") as archive:
        for file in source.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(source).as_posix())
    return dest


def test_valid_zip_package_is_accepted(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    archive = _zip_directory(package, tmp_path / "valid.zip")
    result = validate_model_package_source(archive)
    assert result.valid, [issue.model_dump() for issue in result.issues]


def test_zip_extra_members_are_accepted_under_caps(tmp_path: Path) -> None:
    package = _write_package(tmp_path, extra_files={"leftover.bin": b"ignore-me"})
    archive = _zip_directory(package, tmp_path / "extra.zip")
    result = validate_model_package_source(archive)
    leftover_issues = [issue for issue in result.issues if "leftover" in issue.path]
    assert leftover_issues == []
    assert result.valid


def test_zip_slip_member_is_rejected_without_writing_outside(tmp_path: Path) -> None:
    archive = tmp_path / "slip.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escaped.bin", b"pwned")
        handle.writestr("subdir/../../outside.bin", b"pwned")
    result = validate_model_package_source(archive)
    assert not result.valid
    _assert_has_issue(result, "..")
    written = {path.name for path in tmp_path.rglob("*") if path.is_file()}
    assert written == {"slip.zip"}


def test_nested_archive_member_is_rejected(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    archive = tmp_path / "nested.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for file in package.rglob("*"):
            if file.is_file():
                handle.write(file, file.relative_to(package).as_posix())
        handle.writestr("payload.tar", b"not-a-real-tar")
    result = validate_model_package_source(archive)
    assert not result.valid
    _assert_has_issue(result, "Nested archive")
    assert not (tmp_path / "payload.tar").exists()


def test_zip_extract_rejects_lying_uncompressed_size(tmp_path: Path) -> None:
    archive = tmp_path / "lie.zip"
    payload = b"A" * 8192
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as handle:
        handle.writestr("bomb.bin", payload)
    data = bytearray(archive.read_bytes())
    claimed = (1).to_bytes(4, "little")
    local = data.find(b"PK\x03\x04")
    central = data.find(b"PK\x01\x02")
    assert local != -1 and central != -1
    data[local + 22 : local + 26] = claimed
    data[central + 24 : central + 28] = claimed
    archive.write_bytes(data)
    with zipfile.ZipFile(archive) as handle:
        assert handle.infolist()[0].file_size == 1

    result = validate_model_package_source(archive)
    assert not result.valid
    _assert_has_issue(result, "declared uncompressed size")
    written = {path.name for path in tmp_path.rglob("*") if path.is_file()}
    assert written == {"lie.zip"}


def test_oversize_uncompressed_zip_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bomb.zip"
    info = zipfile.ZipInfo("bomb.bin")
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(archive, "w") as handle:
        with handle.open(info, "w") as dest:
            chunk = b"\x00" * (1024 * 1024)
            remaining = MAX_ZIP_UNCOMPRESSED_BYTES + 1
            while remaining:
                piece = chunk if remaining >= len(chunk) else chunk[:remaining]
                dest.write(piece)
                remaining -= len(piece)
    result = validate_model_package_source(archive)
    assert not result.valid
    _assert_has_issue(result, "96 MiB")


def test_oversize_compressed_zip_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "huge.zip"
    with archive.open("wb") as handle:
        handle.seek(MAX_ZIP_COMPRESSED_BYTES)
        handle.write(b"x")
    result = validate_model_package_source(archive)
    assert not result.valid
    _assert_has_issue(result, "32 MiB")
    assert archive.stat().st_size == MAX_ZIP_COMPRESSED_BYTES + 1


def test_zip_member_count_limit_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for index in range(65):
            handle.writestr(f"member-{index}.bin", b"x")
    result = validate_model_package_source(archive)
    assert not result.valid
    _assert_has_issue(result, "64-member")
