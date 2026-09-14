"""Schema and upgrade tests for the shared durable runtime-state migration."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.api.migrations import (
    INITIAL_SCHEMA_VERSION,
    OBJECT_CHECKSUM_VERSION,
    PACKAGE_ADMISSION_VERSION,
    PREPROCESSING_BUNDLE_VERSION,
    PROVISIONAL_HDFS_RESULTS_VERSION,
    RESULT_INSPECTION_INDEXES_VERSION,
    RESULT_INSPECTION_SCORE_INDEX_VERSION,
    SHARED_STATE_VERSION,
    apply_migrations,
    _upgrade_shared_state_sqlite,
)
from src.api.storage import (
    ApiDatabase,
    DatabaseIntegrityError,
    ProvisionalResultPageQuery,
    ResultCursorError,
    utc_now,
)


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


def _index_names(database: ApiDatabase, table_name: str) -> set[str]:
    with database.session() as connection:
        if database.uses_postgresql:
            rows = connection.execute(
                """
                SELECT indexname AS name
                FROM pg_indexes
                WHERE schemaname = current_schema() AND tablename = ?
                """,
                (table_name,),
            ).fetchall()
        else:
            rows = connection.execute(f"PRAGMA index_list({table_name})").fetchall()
        return {str(dict(row)["name"]) for row in rows}


def _index_definition(database: ApiDatabase, index_name: str) -> str:
    with database.session() as connection:
        if database.uses_postgresql:
            row = connection.execute(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = current_schema() AND indexname = ?
                """,
                (index_name,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                (index_name,),
            ).fetchone()
    assert row is not None
    return str(dict(row)["indexdef" if database.uses_postgresql else "sql"])


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
        "provisional_count",
        "unassigned_context_line_count",
        "classification_policy",
        "classification_catalog_sha256",
    } <= _table_columns(database, "analysis_runs")
    assert {
        "id",
        "analysis_run_id",
        "record_reference",
        "reason_code",
        "context_json",
    } <= _table_columns(database, "provisional_results")
    assert "idx_provisional_results_run_block_id" in _index_names(
        database, "provisional_results"
    )
    assert {
        INITIAL_SCHEMA_VERSION,
        SHARED_STATE_VERSION,
        PACKAGE_ADMISSION_VERSION,
        OBJECT_CHECKSUM_VERSION,
        PREPROCESSING_BUNDLE_VERSION,
        RESULT_INSPECTION_INDEXES_VERSION,
        RESULT_INSPECTION_SCORE_INDEX_VERSION,
        PROVISIONAL_HDFS_RESULTS_VERSION,
    } <= _applied_versions(database)
    assert {
        "idx_anomaly_results_run_id",
        "idx_anomaly_results_run_score_desc",
        "idx_anomaly_results_run_block_id",
    } <= _index_names(database, "anomaly_results")
    score_index = _index_definition(database, "idx_anomaly_results_run_score_desc").upper()
    compact_score_index = " ".join(score_index.replace("(", " ").replace(")", " ").split())
    assert "CASE WHEN ANOMALY_SCORE IS NULL THEN 1 ELSE 0 END" in compact_score_index
    assert "ANOMALY_SCORE DESC" in compact_score_index
    assert {
        "id",
        "project_id",
        "identifier",
        "version",
        "object_prefix",
        "manifest_checksum",
        "metadata_json",
        "created_at",
    } <= _table_columns(database, "preprocessing_bundles")
    assert "preprocessing_bundle_id" in _table_columns(database, "model_versions")


def _seed_model(database: ApiDatabase, *, suffix: str = "") -> tuple[UUID, UUID, UUID]:
    project = database.create_project(f"incident-a{suffix}")
    user = database.create_user(
        username=f"publisher{suffix}",
        password_hash="x",
        is_administrator=False,
    )
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
    dataset = database.upsert_dataset(
        project_id=project_id,
        storage_kind="workspace",
        object_reference="data/stored-hdfs.log",
        checksum=None,
        actor_user_id=user_id,
    )

    accepted = database.create_analysis_run(
        project_id=project_id,
        model_version_id=model_id,
        requested_by_user_id=user_id,
        log_reference="data/stored-hdfs.log",
        status="not_supported",
        validation_report_json="{}",
        error_code="INFERENCE_CONTRACT_UNAVAILABLE",
        completed_at=utc_now(),
        dataset_id=UUID(str(dataset["id"])),
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


def test_result_inspection_indexes_are_idempotent_and_preserve_rows(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    apply_migrations(database, target=PREPROCESSING_BUNDLE_VERSION)
    project_id, user_id, model_id = _seed_model(database)
    dataset = database.upsert_dataset(
        project_id=project_id,
        storage_kind="workspace",
        object_reference="data/stored-hdfs.log",
        checksum=None,
        actor_user_id=user_id,
    )
    run = database.create_analysis_run(
        project_id=project_id,
        model_version_id=model_id,
        requested_by_user_id=user_id,
        log_reference="data/stored-hdfs.log",
        status="queued",
        validation_report_json="{}",
        error_code=None,
        completed_at=None,
        dataset_id=UUID(str(dataset["id"])),
    )
    run_id = UUID(str(run["id"]))
    database.transition_analysis_run(
        run_id,
        expected_status="queued",
        next_status="running",
        actor_user_id=user_id,
    )
    anomaly_id = str(uuid4())
    context_json = '{"matched_line_count": 2, "source_lines": []}'
    database.transition_analysis_run(
        run_id,
        expected_status="running",
        next_status="completed",
        actor_user_id=user_id,
        results_summary_json=(
            '{"anomaly_count": 1, "invalid_records": 0, "normal_count": 0, "rejected_records": 0}'
        ),
        anomaly_results=[
            {
                "id": anomaly_id,
                "record_reference": "blk_1",
                "anomaly_score": 0.91,
                "anomaly_level": "anomaly",
                "decision_threshold": 0.5,
                "context_json": context_json,
            }
        ],
    )

    apply_migrations(database)
    apply_migrations(database)
    _assert_shared_state_schema(database)
    results = database.list_anomaly_results(run_id)
    assert len(results) == 1
    assert results[0]["id"] == anomaly_id
    assert results[0]["record_reference"] == "blk_1"
    assert results[0]["context_json"] == context_json


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


def _queued_run(database: ApiDatabase, *, suffix: str = "") -> tuple[UUID, UUID]:
    project_id, user_id, model_id = _seed_model(database, suffix=suffix)
    dataset = database.upsert_dataset(
        project_id=project_id,
        storage_kind="workspace",
        object_reference="data/stored-hdfs.log",
        checksum=None,
        actor_user_id=user_id,
    )
    run = database.create_analysis_run(
        project_id=project_id,
        model_version_id=model_id,
        requested_by_user_id=user_id,
        log_reference="data/stored-hdfs.log",
        status="queued",
        validation_report_json="{}",
        error_code=None,
        completed_at=None,
        dataset_id=UUID(str(dataset["id"])),
    )
    return UUID(str(run["id"])), user_id


def test_sqlite_upgrade_to_provisional_results_preserves_pre008_rows(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    apply_migrations(database, target=RESULT_INSPECTION_SCORE_INDEX_VERSION)
    assert PROVISIONAL_HDFS_RESULTS_VERSION not in _applied_versions(database)
    run_id, user_id = _queued_run(database)
    database.transition_analysis_run(
        run_id,
        expected_status="queued",
        next_status="running",
        actor_user_id=user_id,
    )
    anomaly_id = str(uuid4())
    database.transition_analysis_run(
        run_id,
        expected_status="running",
        next_status="completed",
        actor_user_id=user_id,
        results_summary_json=(
            '{"anomaly_count": 1, "invalid_records": 0, "normal_count": 0, "rejected_records": 0}'
        ),
        anomaly_results=[
            {
                "id": anomaly_id,
                "record_reference": "blk_1",
                "anomaly_score": 0.91,
                "anomaly_level": "anomaly",
                "decision_threshold": 0.5,
                "context_json": "{}",
            }
        ],
    )

    apply_migrations(database)
    apply_migrations(database)
    _assert_shared_state_schema(database)
    run = database.get_analysis_run(run_id)
    assert run is not None
    assert int(run["provisional_count"] or 0) == 0
    assert int(run["unassigned_context_line_count"] or 0) == 0
    assert run["classification_policy"] is None
    assert run["classification_catalog_sha256"] is None
    results = database.list_anomaly_results(run_id)
    assert [row["id"] for row in results] == [anomaly_id]
    assert database.list_provisional_results(run_id) == []


def test_completed_result_transaction_rolls_back_both_result_kinds(tmp_path: Path) -> None:
    from unittest.mock import patch

    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    run_id, user_id = _queued_run(database)
    database.transition_analysis_run(
        run_id,
        expected_status="queued",
        next_status="running",
        actor_user_id=user_id,
    )
    summary = (
        '{"anomaly_count": 1, "invalid_records": 0, "normal_count": 0, "rejected_records": 0}'
    )
    with patch.object(database, "_insert_audit_event", side_effect=RuntimeError("audit boom")):
        with pytest.raises(RuntimeError, match="audit boom"):
            database.transition_analysis_run(
                run_id,
                expected_status="running",
                next_status="completed",
                actor_user_id=user_id,
                results_summary_json=summary,
                anomaly_results=[
                    {
                        "record_reference": "blk_1",
                        "anomaly_score": 0.9,
                        "anomaly_level": "high",
                        "decision_threshold": 0.5,
                        "context": {},
                    }
                ],
                provisional_results=[
                    {
                        "record_reference": "blk_2",
                        "reason_code": "not_in_reference_catalog",
                        "context": {"matched_line_count": 1, "source_lines": []},
                    }
                ],
                unassigned_context_line_count=3,
                classification_policy="hdfs_reference_membership_v1",
                classification_catalog_sha256="a" * 64,
            )
    rolled_back = database.get_analysis_run(run_id)
    assert rolled_back is not None
    assert rolled_back["status"] == "running"
    assert rolled_back["results_summary_json"] is None
    assert int(rolled_back["provisional_count"] or 0) == 0
    assert database.list_anomaly_results(run_id) == []
    assert database.list_provisional_results(run_id) == []

    with pytest.raises(DatabaseIntegrityError):
        database.transition_analysis_run(
            run_id,
            expected_status="running",
            next_status="completed",
            actor_user_id=user_id,
            results_summary_json=summary,
            provisional_results=[
                {"record_reference": "blk_2", "context": {}},
                {"record_reference": "blk_2", "context": {}},
            ],
        )
    still_running = database.get_analysis_run(run_id)
    assert still_running is not None
    assert still_running["status"] == "running"
    assert database.list_provisional_results(run_id) == []
    assert database.list_anomaly_results(run_id) == []


def test_provisional_paging_validates_literal_prefix_and_cursor_kind(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    run_id, user_id = _queued_run(database)
    other_run_id, other_user_id = _queued_run(database, suffix="-other")
    database.transition_analysis_run(
        run_id, expected_status="queued", next_status="running", actor_user_id=user_id
    )
    database.transition_analysis_run(
        other_run_id,
        expected_status="queued",
        next_status="running",
        actor_user_id=other_user_id,
    )
    database.transition_analysis_run(
        run_id,
        expected_status="running",
        next_status="completed",
        actor_user_id=user_id,
        results_summary_json=(
            '{"anomaly_count": 2, "invalid_records": 0, "normal_count": 0, "rejected_records": 0}'
        ),
        anomaly_results=[
            {
                "id": "00000000-0000-4000-8000-00000000000a",
                "record_reference": "blk_a",
                "anomaly_score": 0.91,
                "anomaly_level": "anomaly",
                "decision_threshold": 0.5,
                "context": {},
            },
            {
                "id": "00000000-0000-4000-8000-00000000000b",
                "record_reference": "blk_b",
                "anomaly_score": 0.8,
                "anomaly_level": "anomaly",
                "decision_threshold": 0.5,
                "context": {},
            },
        ],
        provisional_results=[
            {"id": "00000000-0000-4000-8000-000000000001", "record_reference": "blk_1", "context": {}},
            {"id": "00000000-0000-4000-8000-000000000002", "record_reference": "blk_2", "context": {}},
            {"id": "00000000-0000-4000-8000-000000000003", "record_reference": "blk_x", "context": {}},
            {
                "id": "00000000-0000-4000-8000-000000000004",
                "record_reference": "blk_underscore",
                "context": {},
            },
        ],
        unassigned_context_line_count=2,
        classification_policy="hdfs_reference_membership_v1",
        classification_catalog_sha256="b" * 64,
    )
    first = database.list_provisional_result_page(
        run_id, ProvisionalResultPageQuery(limit=2)
    )
    assert [row["record_reference"] for row in first.rows] == ["blk_1", "blk_2"]
    assert first.next_cursor is not None
    second = database.list_provisional_result_page(
        run_id,
        ProvisionalResultPageQuery(limit=2, cursor=first.next_cursor),
    )
    assert [row["record_reference"] for row in second.rows] == ["blk_underscore", "blk_x"]
    assert second.next_cursor is None

    prefixed = database.list_provisional_result_page(
        run_id, ProvisionalResultPageQuery(limit=10, block_id_prefix="blk_1")
    )
    assert [row["record_reference"] for row in prefixed.rows] == ["blk_1"]
    literal_underscore = database.list_provisional_result_page(
        run_id, ProvisionalResultPageQuery(limit=10, block_id_prefix="blk_")
    )
    assert {row["record_reference"] for row in literal_underscore.rows} == {
        "blk_1",
        "blk_2",
        "blk_underscore",
        "blk_x",
    }
    escaped = database.list_provisional_result_page(
        run_id, ProvisionalResultPageQuery(limit=10, block_id_prefix="blk_underscor_")
    )
    assert escaped.rows == []

    from src.api.storage import AnomalyResultPageQuery

    anomaly_page = database.list_anomaly_result_page(
        run_id, AnomalyResultPageQuery(limit=1, sort="score_desc")
    )
    assert anomaly_page.next_cursor is not None
    with pytest.raises(ResultCursorError):
        database.list_provisional_result_page(
            run_id,
            ProvisionalResultPageQuery(limit=2, cursor=anomaly_page.next_cursor),
        )
    with pytest.raises(ResultCursorError):
        database.list_provisional_result_page(
            other_run_id,
            ProvisionalResultPageQuery(limit=2, cursor=first.next_cursor),
        )
    with pytest.raises(ResultCursorError):
        database.list_provisional_result_page(
            run_id,
            ProvisionalResultPageQuery(limit=2, cursor="not-a-cursor"),
        )
    mismatched_filter = database.list_provisional_result_page(
        run_id, ProvisionalResultPageQuery(limit=2, block_id_prefix="blk_1")
    )
    with pytest.raises(ResultCursorError):
        database.list_provisional_result_page(
            run_id,
            ProvisionalResultPageQuery(
                limit=2,
                block_id_prefix="blk_2",
                cursor=mismatched_filter.next_cursor or first.next_cursor,
            ),
        )


@pytest.mark.postgres
def test_postgres_shared_state_migration_applies_and_is_healthy(
    postgres_database: ApiDatabase,
) -> None:
    postgres_database.apply_migrations()
    postgres_database.apply_migrations()
    _assert_shared_state_schema(postgres_database)
    assert postgres_database.healthcheck()
