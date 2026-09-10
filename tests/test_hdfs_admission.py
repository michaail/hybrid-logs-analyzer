"""In-process HDFS log admission tests. Non-ML tests never import Torch."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from src.api.object_store import FilesystemObjectStore
from src.api.validation import MAX_HDFS_UPLOAD_BYTES, admit_uploaded_hdfs_log

_PROJECT_ID = UUID("11111111-1111-4111-8111-111111111111")
_VALID_HDFS_LINE = (
    "081109 203615 148 INFO dfs.DataNode$DataXceiver: "
    "Receiving block blk_1 src: /10.0.0.1:50010 dest: /10.0.0.2:50010"
)
_VALID_PAYLOAD = f"{_VALID_HDFS_LINE}\n".encode("utf-8")


def _object_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_admit_uploaded_hdfs_log_persists_valid_bytes(tmp_path: Path) -> None:
    object_root = tmp_path / "objects"
    store = FilesystemObjectStore(object_root)
    report, admitted = admit_uploaded_hdfs_log(
        _VALID_PAYLOAD,
        object_store=store,
        project_id=_PROJECT_ID,
        original_filename="nested/HDFS_2k.log",
    )
    assert report["valid"] is True
    assert report["total_records"] == 1
    assert report["invalid_records"] == 0
    assert report["issues"] == []
    assert admitted is not None
    assert admitted.storage_kind == "object"
    assert admitted.checksum == hashlib.sha256(_VALID_PAYLOAD).hexdigest()
    assert admitted.object_reference == (
        f"projects/{_PROJECT_ID}/datasets/{admitted.dataset_id}/HDFS_2k.log"
    )
    stored = _object_files(object_root)
    assert stored == {admitted.object_reference}
    stored_path = object_root.joinpath(*admitted.object_reference.split("/"))
    assert stored_path.read_bytes() == _VALID_PAYLOAD


def test_admit_uploaded_hdfs_log_falls_back_to_hdfs_log_name(tmp_path: Path) -> None:
    object_root = tmp_path / "objects"
    store = FilesystemObjectStore(object_root)
    _report, admitted = admit_uploaded_hdfs_log(
        _VALID_PAYLOAD,
        object_store=store,
        project_id=_PROJECT_ID,
        original_filename="..",
    )
    assert admitted is not None
    assert admitted.object_reference.endswith("/hdfs.log")
    assert _object_files(object_root) == {admitted.object_reference}


def test_admit_uploaded_hdfs_log_sanitizes_original_filename(tmp_path: Path) -> None:
    object_root = tmp_path / "objects"
    store = FilesystemObjectStore(object_root)
    _report, admitted = admit_uploaded_hdfs_log(
        _VALID_PAYLOAD,
        object_store=store,
        project_id=_PROJECT_ID,
        original_filename=r"C:\logs\HDFS 2k.log",
    )
    assert admitted is not None
    assert admitted.object_reference.endswith("/HDFS_2k.log")
    assert _object_files(object_root) == {admitted.object_reference}


def test_admit_uploaded_hdfs_log_rejects_oversize_without_put(tmp_path: Path) -> None:
    object_root = tmp_path / "objects"
    store = FilesystemObjectStore(object_root)
    payload = b"x" * (MAX_HDFS_UPLOAD_BYTES + 1)
    report, admitted = admit_uploaded_hdfs_log(
        payload,
        object_store=store,
        project_id=_PROJECT_ID,
        original_filename="hdfs.log",
    )
    assert admitted is None
    assert report["valid"] is False
    assert report["issues"] == [{"reason": "HDFS log exceeds the 32 MiB size limit."}]
    assert _object_files(object_root) == set()


def test_admit_uploaded_hdfs_log_rejects_empty_without_put(tmp_path: Path) -> None:
    object_root = tmp_path / "objects"
    store = FilesystemObjectStore(object_root)
    report, admitted = admit_uploaded_hdfs_log(
        b"",
        object_store=store,
        project_id=_PROJECT_ID,
        original_filename="hdfs.log",
    )
    assert admitted is None
    assert report["valid"] is False
    assert report["total_records"] == 0
    assert report["issues"] == [{"reason": "Dataset contains no records."}]
    assert _object_files(object_root) == set()


def test_admit_uploaded_hdfs_log_rejects_one_bad_line_without_put(tmp_path: Path) -> None:
    object_root = tmp_path / "objects"
    store = FilesystemObjectStore(object_root)
    payload = f"{_VALID_HDFS_LINE}\nnot an HDFS record\n{_VALID_HDFS_LINE}\n".encode("utf-8")
    report, admitted = admit_uploaded_hdfs_log(
        payload,
        object_store=store,
        project_id=_PROJECT_ID,
        original_filename="hdfs.log",
    )
    assert admitted is None
    assert report["valid"] is False
    assert report["total_records"] == 3
    assert report["invalid_records"] == 1
    assert report["examples"] == [
        {"line_number": 2, "reason": "Does not match the supported HDFS log format."}
    ]
    assert report["issues"] == [
        {"reason": "Does not match the supported HDFS log format."}
    ]
    assert _object_files(object_root) == set()


def test_admit_uploaded_hdfs_log_rejects_non_utf8_without_put(tmp_path: Path) -> None:
    object_root = tmp_path / "objects"
    store = FilesystemObjectStore(object_root)
    report, admitted = admit_uploaded_hdfs_log(
        b"\xff\xfe not utf-8",
        object_store=store,
        project_id=_PROJECT_ID,
        original_filename="hdfs.log",
    )
    assert admitted is None
    assert report["valid"] is False
    assert report["issues"] == [
        {"reason": "HDFS log dataset must be a readable UTF-8 text file."}
    ]
    assert _object_files(object_root) == set()
