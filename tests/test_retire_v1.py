"""Leftover v1 / null-bundle administrator cleanup."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.api.object_store import (
    FilesystemObjectStore,
    model_package_object_prefix,
    preprocessing_bundle_object_prefix,
)
from src.api.retire_v1 import (
    ACTION_DELETE,
    ACTION_SKIP_DEPENDENT,
    ACTION_SKIP_WORKSPACE,
    format_candidate_line,
    is_retire_candidate,
    retire_v1_models,
)
from src.api.storage import ApiDatabase, DatabaseIntegrityError
from src.modules.model_package import PACKAGE_FORMAT_V1, PACKAGE_FORMAT_V2

_REPO_ROOT = Path(__file__).resolve().parents[1]
_V1_METADATA = json.dumps(
    {"format": PACKAGE_FORMAT_V1, "feature_contract": "notebook_raw_v1"}
)
_V2_METADATA = json.dumps(
    {"format": PACKAGE_FORMAT_V2, "feature_contract": "notebook_raw_v1"}
)
_WORKSPACE_PACKAGE_REFERENCE = "packages/hdfs/attribute-gae-v1"


@dataclass(frozen=True)
class CleanupSeed:
    """IDs and object prefixes for the four leftover-cleanup fixtures."""

    project_id: UUID
    v1_id: UUID
    v1_prefix: str
    dependent_id: UUID
    dependent_prefix: str
    survivor_id: UUID
    survivor_prefix: str
    bundle_prefix: str
    workspace_id: UUID


class RecordingObjectStore:
    """Filesystem store that records delete_prefix calls."""

    def __init__(self, inner: FilesystemObjectStore) -> None:
        self._inner = inner
        self.deleted_prefixes: list[str] = []

    def put(self, key: str, payload: bytes) -> None:
        self._inner.put(key, payload)

    def get(self, key: str) -> bytes:
        return self._inner.get(key)

    def delete_prefix(self, prefix: str) -> None:
        self.deleted_prefixes.append(prefix)
        self._inner.delete_prefix(prefix)


def _database(tmp_path: Path) -> ApiDatabase:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    return database


def _object_store(tmp_path: Path) -> RecordingObjectStore:
    return RecordingObjectStore(FilesystemObjectStore(tmp_path / "objects"))


def _workspace_dataset(database: ApiDatabase, project_id: UUID, user_id: UUID) -> UUID:
    dataset = database.upsert_dataset(
        project_id=project_id,
        storage_kind="workspace",
        object_reference="data/stored-hdfs.log",
        checksum=None,
        actor_user_id=user_id,
    )
    return UUID(str(dataset["id"]))


def _queued_run(
    database: ApiDatabase, project_id: UUID, user_id: UUID, model_id: UUID
) -> UUID:
    run = database.create_analysis_run(
        project_id=project_id,
        model_version_id=model_id,
        requested_by_user_id=user_id,
        log_reference="data/stored-hdfs.log",
        status="queued",
        validation_report_json="{}",
        error_code=None,
        completed_at=None,
        actor_user_id=user_id,
        dataset_id=_workspace_dataset(database, project_id, user_id),
    )
    return UUID(str(run["id"]))


def _put_object(store: RecordingObjectStore, prefix: str, name: str, payload: bytes) -> str:
    key = f"{prefix}/{name}"
    store.put(key, payload)
    return key


def _seed_cleanup_fixture(
    database: ApiDatabase, store: RecordingObjectStore
) -> CleanupSeed:
    project = database.create_project("incident-a")
    user = database.create_user(
        username="publisher", password_hash="x", is_administrator=False
    )
    project_id = UUID(str(project["id"]))
    user_id = UUID(str(user["id"]))

    v1_id = uuid4()
    v1_prefix = model_package_object_prefix(project_id, v1_id, "v1-a")
    _put_object(store, v1_prefix, "manifest.json", b"v1-package")
    database.create_model_version(
        project_id=project_id,
        model_identifier="leftover-v1",
        version="v1-a",
        pipeline_run_id="baseline-v1",
        artifact_reference=f"{v1_prefix}/model.pt",
        package_reference=v1_prefix,
        artifact_sha256="0" * 64,
        metrics_json="{}",
        metadata_json=_V1_METADATA,
        external_evaluation_evidence="evidence",
        storage_kind="object",
        checksum="sha256:v1-a",
        actor_user_id=user_id,
        model_id=v1_id,
    )

    dependent_id = uuid4()
    dependent_prefix = model_package_object_prefix(project_id, dependent_id, "v1-b")
    _put_object(store, dependent_prefix, "manifest.json", b"v1-dependent")
    database.create_model_version(
        project_id=project_id,
        model_identifier="leftover-dependent",
        version="v1-b",
        pipeline_run_id="baseline-dependent",
        artifact_reference=f"{dependent_prefix}/model.pt",
        package_reference=dependent_prefix,
        artifact_sha256="1" * 64,
        metrics_json="{}",
        metadata_json=_V1_METADATA,
        external_evaluation_evidence="evidence",
        storage_kind="object",
        checksum="sha256:v1-b",
        actor_user_id=user_id,
        model_id=dependent_id,
    )
    _queued_run(database, project_id, user_id, dependent_id)

    survivor_id = uuid4()
    survivor_prefix = model_package_object_prefix(project_id, survivor_id, "v2")
    bundle_id = uuid4()
    bundle_prefix = preprocessing_bundle_object_prefix(project_id, bundle_id, "v2")
    _put_object(store, survivor_prefix, "manifest.json", b"v2-package")
    _put_object(store, bundle_prefix, "bundle.json", b"v2-bundle")
    database.create_model_version(
        project_id=project_id,
        model_identifier="survivor-v2",
        version="v2",
        pipeline_run_id="baseline-v2",
        artifact_reference=f"{survivor_prefix}/model.pt",
        package_reference=survivor_prefix,
        artifact_sha256="2" * 64,
        metrics_json="{}",
        metadata_json=_V2_METADATA,
        external_evaluation_evidence="evidence",
        storage_kind="object",
        checksum="sha256:v2",
        actor_user_id=user_id,
        model_id=survivor_id,
        preprocessing_bundle={
            "id": str(bundle_id),
            "identifier": "attribute-gae-preprocessing",
            "version": "v2",
            "object_prefix": bundle_prefix,
            "manifest_checksum": "a" * 64,
            "metadata_json": "{}",
        },
    )

    workspace_id = uuid4()
    database.create_model_version(
        project_id=project_id,
        model_identifier="leftover-workspace",
        version="workspace",
        pipeline_run_id="baseline-workspace",
        artifact_reference="outputs/hdfs/workspace/model.pt",
        package_reference=_WORKSPACE_PACKAGE_REFERENCE,
        artifact_sha256="3" * 64,
        metrics_json="{}",
        metadata_json="{}",
        external_evaluation_evidence="evidence",
        storage_kind="workspace",
        actor_user_id=user_id,
        model_id=workspace_id,
    )

    return CleanupSeed(
        project_id=project_id,
        v1_id=v1_id,
        v1_prefix=v1_prefix,
        dependent_id=dependent_id,
        dependent_prefix=dependent_prefix,
        survivor_id=survivor_id,
        survivor_prefix=survivor_prefix,
        bundle_prefix=bundle_prefix,
        workspace_id=workspace_id,
    )


def test_cli_help_lists_dry_run_and_apply() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.api.retire_v1", "--help"],
        check=False,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0
    assert "--dry-run" in result.stdout
    assert "--apply" in result.stdout


def test_feature_contract_is_not_a_package_format() -> None:
    row = {
        "metadata_json": json.dumps({"feature_contract": "notebook_raw_v1"}),
        "preprocessing_bundle_id": str(uuid4()),
    }
    assert is_retire_candidate(row) is False
    assert is_retire_candidate(
        {"metadata_json": _V1_METADATA, "preprocessing_bundle_id": str(uuid4())}
    )
    assert is_retire_candidate({"metadata_json": "{}", "preprocessing_bundle_id": None})


def test_dry_run_is_noop_and_exits_1_when_dependent_skip(tmp_path: Path) -> None:
    database = _database(tmp_path)
    store = _object_store(tmp_path)
    seeded = _seed_cleanup_fixture(database, store)

    report = retire_v1_models(database, store, apply=False)

    by_id = {candidate.model_id: candidate for candidate in report.candidates}
    assert set(by_id) == {
        seeded.v1_id,
        seeded.dependent_id,
        seeded.workspace_id,
    }
    assert seeded.survivor_id not in by_id
    assert by_id[seeded.v1_id].action == ACTION_DELETE
    assert by_id[seeded.dependent_id].action == ACTION_SKIP_DEPENDENT
    assert by_id[seeded.workspace_id].action == ACTION_SKIP_WORKSPACE
    assert report.exit_code == 1
    assert store.deleted_prefixes == []
    assert store.get(f"{seeded.v1_prefix}/manifest.json") == b"v1-package"
    assert database.get_model_version(seeded.v1_id) is not None

    listing = "\n".join(format_candidate_line(item) for item in report.candidates)
    assert f"id={seeded.v1_id}" in listing
    assert f"format={PACKAGE_FORMAT_V1}" in listing
    assert "bundle_null=yes" in listing
    assert "runs=1" in listing
    assert f"action={ACTION_SKIP_DEPENDENT}" in listing


def test_apply_deletes_object_kind_v1_skips_dependent_and_workspace(tmp_path: Path) -> None:
    database = _database(tmp_path)
    store = _object_store(tmp_path)
    seeded = _seed_cleanup_fixture(database, store)
    audit_before = database.list_audit_events(seeded.project_id)

    report = retire_v1_models(database, store, apply=True)

    by_id = {candidate.model_id: candidate for candidate in report.candidates}
    assert by_id[seeded.v1_id].action == ACTION_DELETE
    assert by_id[seeded.dependent_id].action == ACTION_SKIP_DEPENDENT
    assert by_id[seeded.workspace_id].action == ACTION_SKIP_WORKSPACE
    assert report.exit_code == 1
    assert seeded.v1_prefix in store.deleted_prefixes
    assert seeded.dependent_prefix not in store.deleted_prefixes
    assert _WORKSPACE_PACKAGE_REFERENCE not in store.deleted_prefixes
    assert seeded.survivor_prefix not in store.deleted_prefixes
    assert seeded.bundle_prefix not in store.deleted_prefixes

    assert database.get_model_version(seeded.v1_id) is None
    with pytest.raises(FileNotFoundError):
        store.get(f"{seeded.v1_prefix}/manifest.json")

    assert database.get_model_version(seeded.dependent_id) is not None
    assert store.get(f"{seeded.dependent_prefix}/manifest.json") == b"v1-dependent"
    assert database.get_model_version(seeded.survivor_id) is not None
    assert store.get(f"{seeded.survivor_prefix}/manifest.json") == b"v2-package"
    assert store.get(f"{seeded.bundle_prefix}/bundle.json") == b"v2-bundle"
    assert database.get_model_version(seeded.workspace_id) is not None

    audit_after = database.list_audit_events(seeded.project_id)
    assert [event["id"] for event in audit_after] == [event["id"] for event in audit_before]
    assert any(
        event["resource_id"] == str(seeded.v1_id) and event["action"] == "model.registered"
        for event in audit_after
    )


def test_apply_workspace_only_does_not_force_exit_1(tmp_path: Path) -> None:
    database = _database(tmp_path)
    store = _object_store(tmp_path)
    project = database.create_project("incident-workspace")
    user = database.create_user(
        username="publisher", password_hash="x", is_administrator=False
    )
    workspace_id = uuid4()
    database.create_model_version(
        project_id=UUID(str(project["id"])),
        model_identifier="leftover-workspace",
        version="workspace",
        pipeline_run_id="baseline-workspace",
        artifact_reference="outputs/hdfs/workspace/model.pt",
        package_reference=_WORKSPACE_PACKAGE_REFERENCE,
        artifact_sha256="3" * 64,
        metrics_json="{}",
        metadata_json="{}",
        external_evaluation_evidence="evidence",
        storage_kind="workspace",
        actor_user_id=UUID(str(user["id"])),
        model_id=workspace_id,
    )

    report = retire_v1_models(database, store, apply=True)

    assert report.exit_code == 0
    assert [candidate.action for candidate in report.candidates] == [ACTION_SKIP_WORKSPACE]
    assert store.deleted_prefixes == []
    assert database.get_model_version(workspace_id) is not None


def test_delete_model_version_fails_closed_when_runs_exist(tmp_path: Path) -> None:
    database = _database(tmp_path)
    project = database.create_project("incident-fk")
    user = database.create_user(
        username="publisher", password_hash="x", is_administrator=False
    )
    project_id = UUID(str(project["id"]))
    user_id = UUID(str(user["id"]))
    model = database.create_model_version(
        project_id=project_id,
        model_identifier="blocked",
        version="1",
        pipeline_run_id="baseline",
        artifact_reference="outputs/hdfs/blocked/model.pt",
        package_reference=_WORKSPACE_PACKAGE_REFERENCE,
        artifact_sha256="4" * 64,
        metrics_json="{}",
        metadata_json="{}",
        external_evaluation_evidence="evidence",
        actor_user_id=user_id,
    )
    model_id = UUID(str(model["id"]))
    _queued_run(database, project_id, user_id, model_id)

    with pytest.raises(DatabaseIntegrityError, match="referenced by analysis runs"):
        database.delete_model_version(model_id)
    assert database.get_model_version(model_id) is not None
    assert database.count_analysis_runs_for_model(model_id) == 1
