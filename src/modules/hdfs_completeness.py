"""Pinned F-03 reference catalog used as an HDFS membership heuristic.

Catalog membership makes a live-analysis block heuristically final. It does not
prove that an HDFS lifecycle ended.
"""

from __future__ import annotations

import hmac
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.modules.hdfs_evaluation_data import (
    SELECTED_IDS_NAME,
    EvaluationDataError,
    EvaluationDataManifest,
    load_selected_block_ids,
    selected_block_ids_order_sha256,
    sha256_file,
)

REFERENCE_MEMBERSHIP_POLICY: Literal["hdfs_reference_membership_v1"] = (
    "hdfs_reference_membership_v1"
)
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SHA256_RE = re.compile(_SHA256_PATTERN)

_MSG_UNAVAILABLE = "The HDFS reference catalog is missing or unreadable."
_MSG_INVALID_CONFIG = "The HDFS reference catalog configuration is invalid."
_MSG_DIGEST_MISMATCH = "The HDFS reference catalog digest does not match the configured value."
_MSG_MALFORMED_MANIFEST = "The HDFS reference catalog manifest is malformed."
_MSG_SELECTED_MISSING = "The HDFS reference catalog selected-block file is missing or unreadable."
_MSG_SELECTED_MISMATCH = "The HDFS reference catalog selected-block file does not match the manifest."
_MSG_SELECTED_MALFORMED = "The HDFS reference catalog selected-block file is malformed."


class CompletenessCatalogError(ValueError):
    """Raised when the pinned HDFS reference catalog cannot be loaded."""

    def __init__(self, message: str, *, reason: str) -> None:
        self.reason = reason
        super().__init__(message)


class HdfsReferenceCatalog(BaseModel):
    """Immutable selected-ID catalog pinned by manifest digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: Literal["hdfs_reference_membership_v1"] = REFERENCE_MEMBERSHIP_POLICY
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    corpus_sha256: str = Field(pattern=_SHA256_PATTERN)
    selected_block_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    selected_block_ids_order_sha256: str = Field(pattern=_SHA256_PATTERN)
    selected_block_ids: frozenset[str]


def normalize_manifest_sha256(value: str) -> str:
    """Return a lowercase 64-character SHA-256 hex digest or raise."""

    digest = value.strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise CompletenessCatalogError(_MSG_INVALID_CONFIG, reason="invalid_expected_digest")
    return digest


def load_hdfs_reference_catalog(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
) -> HdfsReferenceCatalog:
    """Load one exact F-03 manifest and its sibling selected-ID file."""

    expected = normalize_manifest_sha256(expected_manifest_sha256)
    path = Path(manifest_path)
    digest = _manifest_digest(path)
    if not hmac.compare_digest(digest, expected):
        raise CompletenessCatalogError(_MSG_DIGEST_MISMATCH, reason="manifest_digest_mismatch")
    manifest = _load_manifest(path)
    selected_path = path.parent / SELECTED_IDS_NAME
    if not selected_path.is_file():
        raise CompletenessCatalogError(_MSG_SELECTED_MISSING, reason="selected_ids_missing")
    try:
        selected_digest = sha256_file(selected_path)
    except OSError as error:
        raise CompletenessCatalogError(_MSG_SELECTED_MISSING, reason="selected_ids_unreadable") from error
    if not hmac.compare_digest(selected_digest, manifest.selected_block_ids_sha256):
        raise CompletenessCatalogError(
            _MSG_SELECTED_MISMATCH,
            reason="selected_ids_digest_mismatch",
        )
    try:
        block_ids = load_selected_block_ids(selected_path)
    except EvaluationDataError as error:
        raise CompletenessCatalogError(_MSG_SELECTED_MALFORMED, reason="selected_ids_malformed") from error
    order_digest = selected_block_ids_order_sha256(block_ids)
    if not hmac.compare_digest(order_digest, manifest.selected_block_ids_order_sha256):
        raise CompletenessCatalogError(
            _MSG_SELECTED_MISMATCH,
            reason="selected_ids_order_mismatch",
        )
    return HdfsReferenceCatalog(
        policy_id=REFERENCE_MEMBERSHIP_POLICY,
        manifest_sha256=digest,
        corpus_sha256=manifest.corpus_sha256,
        selected_block_ids_sha256=manifest.selected_block_ids_sha256,
        selected_block_ids_order_sha256=manifest.selected_block_ids_order_sha256,
        selected_block_ids=frozenset(block_ids),
    )


def _manifest_digest(path: Path) -> str:
    try:
        if not path.is_file():
            raise CompletenessCatalogError(_MSG_UNAVAILABLE, reason="manifest_missing")
        return sha256_file(path)
    except CompletenessCatalogError:
        raise
    except OSError as error:
        raise CompletenessCatalogError(_MSG_UNAVAILABLE, reason="manifest_unreadable") from error


def _load_manifest(path: Path) -> EvaluationDataManifest:
    try:
        return EvaluationDataManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as error:
        raise CompletenessCatalogError(_MSG_MALFORMED_MANIFEST, reason="manifest_malformed") from error
