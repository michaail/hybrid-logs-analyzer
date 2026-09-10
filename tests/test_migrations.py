"""Schema and upgrade tests for the shared durable runtime-state migration."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.api.migrations import (
    INITIAL_SCHEMA_VERSION,
    OBJECT_CHECKSUM_VERSION,
    PACKAGE_ADMISSION_VERSION,
    SHARED_STATE_VERSION,
    apply_migrations,
    _upgrade_shared_state_sqlite,
)
from src.api.storage import ApiDatabase, DatabaseIntegrityError, utc_now


def _table_columns(database: ApiDatabase, table_name: str) -> set[str]:
    with database.session() as connection:
        if database.uses_postgresql:
            rows = connection.execute(
                """
                SELECT column_name AS name
                FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = ?
                """,
                (table_name,),
            ).fetchall()
        else:
            rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(dict(row)["name"]) for row in rows}


def _applied_versions(database: ApiDatabase) -> set[str]:
    with database.session() as connection:
        rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
    return {str(dict(row)["version"]) for row in rows}


def _assert_shared_state_schema(database: ApiDatabase) -> None:
    assert {
        "id",
        "project_id",
        "storage_kind",
        "object_reference",
        "checksum",
        "source_compatibility",
        "created_at",
    } <= _table_columns(database, "datasets")
    assert {"storage_kind", "checksum", "package_reference", "artifact_sha256"} <= _table_columns(
        database, "model_versions"
    )
    assert {"dataset_id", "results_summary_json"} <= _table_columns(database, "analysis_runs")
    assert {
        INITIAL_SCHEMA_VERSION,
        SHARED_STATE_VERSION,
        PACKAGE_ADMISSION_VERSION,
        OBJECT_CHECKSUM_VERSION,
    } <= _applied_versions(database)


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
    )
    return UUID(str(project["id"])), UUID(str(user["id"])), UUID(str(model["id"]))


def test_shared_state_migration_is_idempotent_on_sqlite(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")

    database.apply_migrations()
    database.apply_migrations()

    _assert_shared_state_schema(database)
    assert database.healthcheck()


def test_sqlite_shared_state_upgrade_noops_when_already_recorded(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    _upgrade_shared_state_sqlite(database)
    _assert_shared_state_schema(database)
    assert database.healthcheck()


def test_fresh_schema_accepts_expanded_run_statuses(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    project_id, user_id, model_id = _seed_model(database)

    accepted = database.create_analysis_run(
        project_id=project_id,
        model_version_id=model_id,
        requested_by_user_id=user_id,
        log_reference="data/stored-hdfs.log",
        status="not_supported",
        validation_report_json="{}",
        error_code="INFERENCE_CONTRACT_UNAVAILABLE",
        completed_at=utc_now(),
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
    )
    assert accepted["dataset_id"]
    assert rejected["dataset_id"] is None

    with database.session() as connection:
        datasets = connection.execute("SELECT id FROM datasets").fetchall()
        assert len(list(datasets)) == 1

    with pytest.raises(DatabaseIntegrityError):
        with database.session() as connection:
            connection.execute(
                """
                INSERT INTO analysis_runs (
                    id, project_id, model_version_id, requested_by_user_id, source_compatibility,
                    log_reference, status, created_at, dataset_id
                ) VALUES (?, ?, ?, ?, 'hdfs', 'data/x.log', 'running', ?, NULL)
                """,
                ("bad-run", str(project_id), str(model_id), str(user_id), utc_now()),
            )


def test_seeded_initial_schema_preserves_ids_across_shared_state_upgrade(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    apply_migrations(database, target=INITIAL_SCHEMA_VERSION)
    assert _applied_versions(database) == {INITIAL_SCHEMA_VERSION}

    project = database.create_project("incident-a")
    user = database.create_user(username="publisher", password_hash="x", is_administrator=False)
    project_id = UUID(str(project["id"]))
    user_id = UUID(str(user["id"]))
    model_id = uuid4()
    with database.session() as connection:
        connection.execute(
            """
            INSERT INTO model_versions (
                id, project_id, model_identifier, version, source_compatibility, status,
                pipeline_run_id, artifact_reference, metrics_json, metadata_json,
                external_evaluation_evidence, created_at
            ) VALUES (?, ?, 'attribute-gae', '2026.09', 'hdfs', 'eligible', 'baseline',
                      'outputs/hdfs/baseline/attribute_gae.pt', '{}', '{}', 'evidence', ?)
            """,
            (str(model_id), str(project_id), utc_now()),
        )
    accepted_run_id = str(uuid4())
    rejected_run_id = str(uuid4())
    anomaly_id = str(uuid4())
    created_at = utc_now()
    with database.session() as connection:
        connection.execute(
            """
            INSERT INTO analysis_runs (
                id, project_id, model_version_id, requested_by_user_id, source_compatibility,
                log_reference, status, validation_report_json, error_code, created_at, completed_at
            ) VALUES (?, ?, ?, ?, 'hdfs', 'data/stored-hdfs.log', 'not_supported', '{}', 'x', ?, ?)
            """,
            (accepted_run_id, str(project_id), str(model_id), str(user_id), created_at, created_at),
        )
        connection.execute(
            """
            INSERT INTO analysis_runs (
                id, project_id, model_version_id, requested_by_user_id, source_compatibility,
                log_reference, status, validation_report_json, error_code, created_at, completed_at
            ) VALUES (?, ?, ?, ?, 'hdfs', '<invalid-reference>', 'rejected', '{}', 'x', ?, ?)
            """,
            (rejected_run_id, str(project_id), str(model_id), str(user_id), created_at, created_at),
        )
        connection.execute(
            """
            INSERT INTO anomaly_results (
                id, analysis_run_id, record_reference, anomaly_score, anomaly_level,
                decision_threshold, context_json
            ) VALUES (?, ?, 'blk_1', 0.9, 'high', 0.5, '{}')
            """,
            (anomaly_id, accepted_run_id),
        )

    apply_migrations(database)
    _assert_shared_state_schema(database)

    accepted = database.get_analysis_run(UUID(accepted_run_id))
    rejected = database.get_analysis_run(UUID(rejected_run_id))
    assert accepted is not None
    assert rejected is not None
    assert accepted["id"] == accepted_run_id
    assert accepted["log_reference"] == "data/stored-hdfs.log"
    assert accepted["dataset_id"]
    assert rejected["dataset_id"] is None
    results = database.list_anomaly_results(UUID(accepted_run_id))
    assert [row["id"] for row in results] == [anomaly_id]
    with database.session() as connection:
        dataset_count = connection.execute("SELECT COUNT(*) AS n FROM datasets").fetchone()
        assert int(dict(dataset_count)["n"]) == 1


def test_sqlite_rejects_object_kind_model_without_checksum(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    project = database.create_project("incident-a")
    created_at = utc_now()
    with pytest.raises(DatabaseIntegrityError):
        with database.session() as connection:
            connection.execute(
                """
                INSERT INTO model_versions (
                    id, project_id, model_identifier, version, source_compatibility, status,
                    pipeline_run_id, artifact_reference, metrics_json, metadata_json,
                    external_evaluation_evidence, created_at, storage_kind, checksum,
                    package_reference, artifact_sha256
                ) VALUES (
                    'model-id', ?, 'attribute-gae', 'v1', 'hdfs', 'eligible', 'run',
                    'artifact', '{}', '{}', 'evidence.json', ?, 'object', NULL, 'prefix', ?
                )
                """,
                (str(project["id"]), created_at, "0" * 64),
            )
    assert database.list_model_versions(UUID(str(project["id"]))) == []


@pytest.mark.postgres
def test_postgres_shared_state_migration_applies_and_is_healthy(
    postgres_database: ApiDatabase,
) -> None:
    postgres_database.apply_migrations()
    postgres_database.apply_migrations()
    _assert_shared_state_schema(postgres_database)
    assert postgres_database.healthcheck()
