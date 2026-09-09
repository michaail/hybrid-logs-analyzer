"""Repository tests for dataset identity, atomic audit, and analysis-run CAS."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest

from src.api.storage import (
    ApiDatabase,
    DatabaseIntegrityError,
    DatasetPointerError,
    RunStatusConflict,
    _DatabaseConnection,
    utc_now,
)


def _database(tmp_path: Path) -> ApiDatabase:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    return database


def _seed_model(database: ApiDatabase) -> tuple[UUID, UUID, UUID]:
    project = database.create_project("incident-a")
    user = database.create_user(username="publisher", password_hash="x", is_administrator=False)
    model = database.create_model_version(
        project_id=UUID(str(project["id"])),
        model_identifier="attribute-gae",
        version="2026.09",
        pipeline_run_id="baseline",
        artifact_reference="outputs/hdfs/baseline/attribute_gae.pt",
        package_reference="packages/hdfs/attribute-gae-v1",
        artifact_sha256="0" * 64,
        metrics_json="{}",
        metadata_json="{}",
        external_evaluation_evidence="evidence",
        actor_user_id=UUID(str(user["id"])),
    )
    return UUID(str(project["id"])), UUID(str(user["id"])), UUID(str(model["id"]))


def _queued_run(database: ApiDatabase, project_id: UUID, user_id: UUID, model_id: UUID) -> UUID:
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
    )
    return UUID(str(run["id"]))


def test_dataset_upsert_reuses_identity_and_allows_workspace_null_checksum(tmp_path: Path) -> None:
    database = _database(tmp_path)
    project_id, user_id, _model_id = _seed_model(database)

    first = database.upsert_dataset(
        project_id=project_id,
        storage_kind="workspace",
        object_reference="data/stored-hdfs.log",
        checksum=None,
        actor_user_id=user_id,
    )
    second = database.upsert_dataset(
        project_id=project_id,
        storage_kind="workspace",
        object_reference="data/stored-hdfs.log",
        checksum=None,
        actor_user_id=user_id,
    )
    assert first["id"] == second["id"]
    assert first["checksum"] is None
    assert [row["id"] for row in database.list_datasets(project_id)] == [first["id"]]
    actions = [event["action"] for event in database.list_audit_events(project_id)]
    assert actions.count("dataset.registered") == 1


def test_dataset_insert_conflict_reuses_row_and_keeps_analysis_run(tmp_path: Path) -> None:
    database = _database(tmp_path)
    project_id, user_id, model_id = _seed_model(database)
    first = database.upsert_dataset(
        project_id=project_id,
        storage_kind="workspace",
        object_reference="data/stored-hdfs.log",
        checksum=None,
        actor_user_id=user_id,
    )
    skip_lookup = {"once": True}
    original = _DatabaseConnection.execute

    def execute(
        self: _DatabaseConnection,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> object:
        compact = " ".join(query.split())
        if skip_lookup["once"] and compact.startswith("SELECT id FROM datasets"):
            skip_lookup["once"] = False

            class _Empty:
                def fetchone(self) -> None:
                    return None

            return _Empty()
        return original(self, query, parameters)

    with patch.object(_DatabaseConnection, "execute", execute):
        run = database.create_analysis_run(
            project_id=project_id,
            model_version_id=model_id,
            requested_by_user_id=user_id,
            log_reference="data/stored-hdfs.log",
            status="not_supported",
            validation_report_json="{}",
            error_code="INFERENCE_CONTRACT_UNAVAILABLE",
            completed_at=utc_now(),
            actor_user_id=user_id,
        )

    assert run["dataset_id"] == first["id"]
    assert database.get_analysis_run(UUID(str(run["id"]))) is not None
    assert [row["id"] for row in database.list_datasets(project_id)] == [first["id"]]
    actions = [event["action"] for event in database.list_audit_events(project_id)]
    assert actions.count("dataset.registered") == 1


def test_object_kind_dataset_without_checksum_is_rejected_before_insert(tmp_path: Path) -> None:
    database = _database(tmp_path)
    project_id, user_id, _model_id = _seed_model(database)

    with pytest.raises(DatasetPointerError, match="checksum"):
        database.upsert_dataset(
            project_id=project_id,
            storage_kind="object",
            object_reference="bucket/hdfs.log",
            checksum=None,
            actor_user_id=user_id,
        )
    assert database.list_datasets(project_id) == []

    stored = database.upsert_dataset(
        project_id=project_id,
        storage_kind="object",
        object_reference="bucket/hdfs.log",
        checksum="sha256:abc",
        actor_user_id=user_id,
    )
    assert stored["checksum"] == "sha256:abc"


def test_audit_failure_rolls_back_model_dataset_run_and_results(tmp_path: Path) -> None:
    database = _database(tmp_path)
    project_id, user_id, model_id = _seed_model(database)

    with patch.object(database, "_insert_audit_event", side_effect=RuntimeError("audit boom")):
        with pytest.raises(RuntimeError, match="audit boom"):
            database.create_model_version(
                project_id=project_id,
                model_identifier="second-model",
                version="1",
                pipeline_run_id="baseline",
                artifact_reference="outputs/hdfs/baseline/other.pt",
                package_reference="packages/hdfs/second-model",
                artifact_sha256="1" * 64,
                metrics_json="{}",
                metadata_json="{}",
                external_evaluation_evidence="evidence",
                actor_user_id=user_id,
            )
        with pytest.raises(RuntimeError, match="audit boom"):
            database.upsert_dataset(
                project_id=project_id,
                storage_kind="workspace",
                object_reference="data/other.log",
                actor_user_id=user_id,
            )
        with pytest.raises(RuntimeError, match="audit boom"):
            database.create_analysis_run(
                project_id=project_id,
                model_version_id=model_id,
                requested_by_user_id=user_id,
                log_reference="data/stored-hdfs.log",
                status="not_supported",
                validation_report_json="{}",
                error_code="INFERENCE_CONTRACT_UNAVAILABLE",
                completed_at=utc_now(),
                actor_user_id=user_id,
            )

    assert [
        row["model_identifier"] for row in database.list_model_versions(project_id)
    ] == ["attribute-gae"]
    assert database.list_datasets(project_id) == []
    assert database.list_analysis_runs(project_id) == []

    run_id = _queued_run(database, project_id, user_id, model_id)
    database.transition_analysis_run(
        run_id,
        expected_status="queued",
        next_status="running",
        actor_user_id=user_id,
    )
    with patch.object(database, "_insert_audit_event", side_effect=RuntimeError("audit boom")):
        with pytest.raises(RuntimeError, match="audit boom"):
            database.transition_analysis_run(
                run_id,
                expected_status="running",
                next_status="completed",
                actor_user_id=user_id,
                results_summary_json=json.dumps({"anomaly_count": 1}, sort_keys=True),
                anomaly_results=[
                    {
                        "record_reference": "blk_1",
                        "anomaly_score": 0.9,
                        "anomaly_level": "high",
                        "decision_threshold": 0.5,
                        "context": {},
                    }
                ],
            )
    rolled_back = database.get_analysis_run(run_id)
    assert rolled_back is not None
    assert rolled_back["status"] == "running"
    assert rolled_back["results_summary_json"] is None
    assert database.list_anomaly_results(run_id) == []


def test_legal_cas_stores_summary_and_illegal_cas_conflicts(tmp_path: Path) -> None:
    database = _database(tmp_path)
    project_id, user_id, model_id = _seed_model(database)
    run_id = _queued_run(database, project_id, user_id, model_id)

    running = database.transition_analysis_run(
        run_id,
        expected_status="queued",
        next_status="running",
        actor_user_id=user_id,
    )
    assert running["status"] == "running"

    summary = json.dumps(
        {"anomaly_count": 1, "normal_count": 0, "rejected_records": 0, "invalid_records": 0},
        sort_keys=True,
    )
    completed = database.transition_analysis_run(
        run_id,
        expected_status="running",
        next_status="completed",
        actor_user_id=user_id,
        results_summary_json=summary,
        anomaly_results=[
            {
                "record_reference": "blk_1",
                "anomaly_score": 0.91,
                "anomaly_level": "high",
                "decision_threshold": 0.5,
                "context": {"window": 1},
            }
        ],
    )
    assert completed["status"] == "completed"
    assert completed["results_summary_json"] == summary
    results = database.list_anomaly_results(run_id)
    assert [row["record_reference"] for row in results] == ["blk_1"]

    with pytest.raises(RunStatusConflict):
        database.transition_analysis_run(
            run_id,
            expected_status="running",
            next_status="completed",
            actor_user_id=user_id,
            results_summary_json=summary,
        )
    with pytest.raises(RunStatusConflict):
        database.transition_analysis_run(
            run_id,
            expected_status="completed",
            next_status="failed",
            actor_user_id=user_id,
            error_code="boom",
        )
    with pytest.raises(RunStatusConflict):
        database.transition_analysis_run(
            run_id,
            expected_status="queued",
            next_status="completed",
            actor_user_id=user_id,
            results_summary_json=summary,
        )

    rejected = database.create_analysis_run(
        project_id=project_id,
        model_version_id=model_id,
        requested_by_user_id=user_id,
        log_reference="<invalid-reference>",
        status="rejected",
        validation_report_json="{}",
        error_code="INVALID_HDFS_DATASET",
        completed_at=utc_now(),
        actor_user_id=user_id,
    )
    assert rejected["dataset_id"] is None
    with pytest.raises(RunStatusConflict):
        database.transition_analysis_run(
            UUID(str(rejected["id"])),
            expected_status="rejected",
            next_status="running",
            actor_user_id=user_id,
        )


@pytest.mark.postgres
def test_postgres_dataset_identity_checksum_check_and_cas_conflict(
    postgres_database: ApiDatabase,
) -> None:
    database = postgres_database
    database.apply_migrations()
    project_id, user_id, model_id = _seed_model(database)

    first = database.upsert_dataset(
        project_id=project_id,
        storage_kind="workspace",
        object_reference="data/stored-hdfs.log",
        actor_user_id=user_id,
    )
    second = database.upsert_dataset(
        project_id=project_id,
        storage_kind="workspace",
        object_reference="data/stored-hdfs.log",
        actor_user_id=user_id,
    )
    assert first["id"] == second["id"]
    with pytest.raises(DatabaseIntegrityError):
        with database.session() as connection:
            connection.execute(
                """
                INSERT INTO datasets (
                    id, project_id, storage_kind, object_reference, checksum,
                    source_compatibility, created_at
                ) VALUES (?, ?, 'workspace', 'data/stored-hdfs.log', NULL, 'hdfs', ?)
                """,
                ("duplicate-dataset", str(project_id), utc_now()),
            )
    with pytest.raises(DatabaseIntegrityError):
        with database.session() as connection:
            connection.execute(
                """
                INSERT INTO datasets (
                    id, project_id, storage_kind, object_reference, checksum,
                    source_compatibility, created_at
                ) VALUES (?, ?, 'object', 'bucket/hdfs.log', NULL, 'hdfs', ?)
                """,
                ("object-without-checksum", str(project_id), utc_now()),
            )

    run_id = _queued_run(database, project_id, user_id, model_id)
    database.transition_analysis_run(
        run_id,
        expected_status="queued",
        next_status="running",
        actor_user_id=user_id,
    )
    database.transition_analysis_run(
        run_id,
        expected_status="running",
        next_status="failed",
        actor_user_id=user_id,
        error_code="INFERENCE_FAILED",
    )
    with pytest.raises(RunStatusConflict):
        database.transition_analysis_run(
            run_id,
            expected_status="running",
            next_status="failed",
            actor_user_id=user_id,
            error_code="INFERENCE_FAILED",
        )
