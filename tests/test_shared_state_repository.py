"""Repository tests for dataset identity, atomic audit, and analysis-run CAS."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest

from src.api.storage import (
    AnomalyResultPageQuery,
    ApiDatabase,
    DatabaseIntegrityError,
    DatasetPointerError,
    ResultCursorError,
    RunStatusConflict,
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


def _workspace_dataset(
    database: ApiDatabase,
    project_id: UUID,
    user_id: UUID,
    object_reference: str = "data/stored-hdfs.log",
) -> UUID:
    dataset = database.upsert_dataset(
        project_id=project_id,
        storage_kind="workspace",
        object_reference=object_reference,
        checksum=None,
        actor_user_id=user_id,
    )
    return UUID(str(dataset["id"]))


def _queued_run(database: ApiDatabase, project_id: UUID, user_id: UUID, model_id: UUID) -> UUID:
    dataset_id = _workspace_dataset(database, project_id, user_id)
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
        dataset_id=dataset_id,
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


def test_non_rejected_run_attaches_existing_dataset(tmp_path: Path) -> None:
    database = _database(tmp_path)
    project_id, user_id, model_id = _seed_model(database)
    first = database.upsert_dataset(
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
        log_reference="ignored-path",
        status="not_supported",
        validation_report_json="{}",
        error_code="INFERENCE_CONTRACT_UNAVAILABLE",
        completed_at=utc_now(),
        actor_user_id=user_id,
        dataset_id=UUID(str(first["id"])),
    )

    assert run["dataset_id"] == first["id"]
    assert run["log_reference"] == "data/stored-hdfs.log"
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
        dataset = database.upsert_dataset(
            project_id=project_id,
            storage_kind="workspace",
            object_reference="data/stored-hdfs.log",
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
                dataset_id=UUID(str(dataset["id"])),
            )

    assert [
        row["model_identifier"] for row in database.list_model_versions(project_id)
    ] == ["attribute-gae"]
    assert [row["id"] for row in database.list_datasets(project_id)] == [dataset["id"]]
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


def _bundle_fields() -> dict[str, str]:
    return {
        "identifier": "attribute-gae-preprocessing",
        "version": "v2",
        "object_prefix": "projects/x/preprocessing-bundles/y/v2",
        "manifest_checksum": "a" * 64,
        "metadata_json": "{}",
    }


def test_preprocessing_bundle_is_project_scoped_and_unique(tmp_path: Path) -> None:
    database = _database(tmp_path)
    project_id, user_id, _model_id = _seed_model(database)
    other_project = database.create_project("incident-b")
    other_user = database.create_user(
        username="other-publisher", password_hash="x", is_administrator=False
    )
    created = database.create_model_version(
        project_id=project_id,
        model_identifier="attribute-gae",
        version="v2",
        pipeline_run_id="baseline-v2",
        artifact_reference="outputs/hdfs/v2/model.pt",
        package_reference="packages/hdfs/attribute-gae-v2",
        artifact_sha256="1" * 64,
        metrics_json="{}",
        metadata_json="{}",
        external_evaluation_evidence="evidence",
        actor_user_id=user_id,
        preprocessing_bundle=_bundle_fields(),
    )
    assert created["preprocessing_bundle_identifier"] == "attribute-gae-preprocessing"
    bundle_id = UUID(str(created["preprocessing_bundle_id"]))
    assert database.get_preprocessing_bundle(project_id, bundle_id) is not None
    assert database.get_preprocessing_bundle(UUID(str(other_project["id"])), bundle_id) is None

    with pytest.raises(DatabaseIntegrityError):
        database.create_model_version(
            project_id=project_id,
            model_identifier="attribute-gae",
            version="v2-other",
            pipeline_run_id="baseline-v2-other",
            artifact_reference="outputs/hdfs/v2-other/model.pt",
            package_reference="packages/hdfs/attribute-gae-v2-other",
            artifact_sha256="2" * 64,
            metrics_json="{}",
            metadata_json="{}",
            external_evaluation_evidence="evidence",
            preprocessing_bundle=_bundle_fields(),
        )

    with pytest.raises(ValueError, match="not found"):
        database.create_model_version(
            project_id=UUID(str(other_project["id"])),
            model_identifier="attribute-gae",
            version="foreign",
            pipeline_run_id="foreign",
            artifact_reference="outputs/hdfs/foreign/model.pt",
            package_reference="packages/hdfs/foreign",
            artifact_sha256="3" * 64,
            metrics_json="{}",
            metadata_json="{}",
            external_evaluation_evidence="evidence",
            actor_user_id=UUID(str(other_user["id"])),
            preprocessing_bundle_id=bundle_id,
        )


def test_failed_model_insert_rolls_back_preprocessing_bundle(tmp_path: Path) -> None:
    database = _database(tmp_path)
    project_id, user_id, _model_id = _seed_model(database)
    with pytest.raises(DatabaseIntegrityError):
        database.create_model_version(
            project_id=project_id,
            model_identifier="attribute-gae",
            version="2026.09",
            pipeline_run_id="duplicate",
            artifact_reference="outputs/hdfs/dup/model.pt",
            package_reference="packages/hdfs/dup",
            artifact_sha256="4" * 64,
            metrics_json="{}",
            metadata_json="{}",
            external_evaluation_evidence="evidence",
            actor_user_id=user_id,
            preprocessing_bundle=_bundle_fields(),
        )
    with database.session() as connection:
        count = connection.execute("SELECT COUNT(*) AS n FROM preprocessing_bundles").fetchone()
        assert int(dict(count)["n"]) == 0


def test_inference_execution_lookup_and_system_audit(tmp_path: Path) -> None:
    database = _database(tmp_path)
    project_id, user_id, _model_id = _seed_model(database)
    other_project = database.create_project("incident-b")
    model = database.create_model_version(
        project_id=project_id,
        model_identifier="attribute-gae",
        version="lookup-v2",
        pipeline_run_id="lookup",
        artifact_reference="projects/p/models/m/v2/model.pt",
        package_reference="projects/p/models/m/v2",
        artifact_sha256="5" * 64,
        metrics_json="{}",
        metadata_json="{}",
        external_evaluation_evidence="evidence",
        actor_user_id=user_id,
        preprocessing_bundle=_bundle_fields(),
    )
    database.publish_model_version(UUID(str(model["id"])), user_id)
    dataset = database.upsert_dataset(
        project_id=project_id,
        storage_kind="object",
        object_reference="projects/p/datasets/d/hdfs.log",
        checksum="6" * 64,
        actor_user_id=user_id,
    )
    run = database.create_analysis_run(
        project_id=project_id,
        model_version_id=UUID(str(model["id"])),
        requested_by_user_id=user_id,
        log_reference="ignored",
        status="queued",
        validation_report_json="{}",
        error_code=None,
        completed_at=None,
        dataset_id=UUID(str(dataset["id"])),
    )
    job = database.get_inference_execution(UUID(str(run["id"])))
    assert job is not None
    assert job["bundle_object_prefix"] == "projects/x/preprocessing-bundles/y/v2"
    assert job["dataset_object_reference"] == "projects/p/datasets/d/hdfs.log"
    assert job["model_status"] == "published"

    other_dataset = database.upsert_dataset(
        project_id=UUID(str(other_project["id"])),
        storage_kind="object",
        object_reference="projects/other/datasets/d/hdfs.log",
        checksum="7" * 64,
        actor_user_id=user_id,
    )
    foreign = database.create_analysis_run(
        project_id=UUID(str(other_project["id"])),
        model_version_id=UUID(str(model["id"])),
        requested_by_user_id=user_id,
        log_reference="ignored",
        status="queued",
        validation_report_json="{}",
        error_code=None,
        completed_at=None,
        dataset_id=UUID(str(other_dataset["id"])),
    )
    assert database.get_inference_execution(UUID(str(foreign["id"]))) is None

    run_id = UUID(str(run["id"]))
    database.transition_analysis_run(
        run_id,
        expected_status="queued",
        next_status="running",
        actor_user_id=None,
    )
    with pytest.raises(RunStatusConflict):
        database.transition_analysis_run(
            run_id,
            expected_status="queued",
            next_status="running",
            actor_user_id=None,
        )
    failed = database.transition_analysis_run(
        run_id,
        expected_status="running",
        next_status="failed",
        actor_user_id=None,
        error_code="UNMATCHED_TEMPLATE",
        validation_report_json=json.dumps(
            {"execution": "An admitted log line did not match the frozen Drain templates."},
            sort_keys=True,
        ),
    )
    assert failed["error_code"] == "UNMATCHED_TEMPLATE"
    assert "frozen Drain templates" in str(failed["validation_report_json"])
    actions = [event["action"] for event in database.list_audit_events(project_id)]
    assert "analysis.running" in actions
    assert "analysis.failed" in actions
    system_events = [
        event
        for event in database.list_audit_events(project_id)
        if event["action"] in {"analysis.running", "analysis.failed"}
        and event["actor_user_id"] is None
    ]
    assert len(system_events) == 2


_ID_A = "00000000-0000-4000-8000-00000000000a"
_ID_B = "00000000-0000-4000-8000-00000000000b"
_ID_C = "00000000-0000-4000-8000-00000000000c"
_ID_D = "00000000-0000-4000-8000-00000000000d"
_ID_M = "00000000-0000-4000-8000-00000000000e"
_ID_Z = "00000000-0000-4000-8000-00000000000f"
_ID_A2 = "00000000-0000-4000-8000-000000000010"


def _anomaly_row(
    block_id: str,
    score: float | None,
    row_id: str,
    *,
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": row_id,
        "record_reference": block_id,
        "anomaly_score": score,
        "anomaly_level": None if score is None else "anomaly",
        "decision_threshold": 0.5,
        "context": context or {},
    }


def _complete_anomalies(
    database: ApiDatabase,
    run_id: UUID,
    user_id: UUID,
    anomalies: list[dict[str, object]],
    *,
    normal_count: int = 3,
) -> None:
    database.transition_analysis_run(
        run_id,
        expected_status="queued",
        next_status="running",
        actor_user_id=user_id,
    )
    database.transition_analysis_run(
        run_id,
        expected_status="running",
        next_status="completed",
        actor_user_id=user_id,
        results_summary_json=json.dumps(
            {
                "anomaly_count": len(anomalies),
                "normal_count": normal_count,
                "rejected_records": 0,
                "invalid_records": 0,
            },
            sort_keys=True,
        ),
        anomaly_results=anomalies,
    )


def _page_rows(
    database: ApiDatabase,
    run_id: UUID,
    *,
    limit: int,
    sort: str,
    block_id_prefix: str | None = None,
    min_score: float | None = None,
    cursor: str | None = None,
) -> tuple[list[str], str | None]:
    page = database.list_anomaly_result_page(
        run_id,
        AnomalyResultPageQuery(
            limit=limit,
            sort=sort,
            block_id_prefix=block_id_prefix,
            min_score=min_score,
            cursor=cursor,
        ),
    )
    return [str(row["id"]) for row in page.rows], page.next_cursor


def _walk_pages(
    database: ApiDatabase,
    run_id: UUID,
    *,
    limit: int,
    sort: str,
    block_id_prefix: str | None = None,
    min_score: float | None = None,
) -> list[str]:
    seen: list[str] = []
    cursor: str | None = None
    used_cursors: set[str] = set()
    while True:
        ids, next_cursor = _page_rows(
            database,
            run_id,
            limit=limit,
            sort=sort,
            block_id_prefix=block_id_prefix,
            min_score=min_score,
            cursor=cursor,
        )
        seen.extend(ids)
        if next_cursor is None:
            return seen
        assert next_cursor not in used_cursors
        used_cursors.add(next_cursor)
        cursor = next_cursor


def _seeded_anomaly_run(tmp_path: Path) -> tuple[ApiDatabase, UUID]:
    database = _database(tmp_path)
    project_id, user_id, model_id = _seed_model(database)
    run_id = _queued_run(database, project_id, user_id, model_id)
    _complete_anomalies(
        database,
        run_id,
        user_id,
        [
            _anomaly_row("blk_c", 0.9, _ID_C),
            _anomaly_row("blk_a", 0.9, _ID_A),
            _anomaly_row("blk_a", 0.9, _ID_A2),
            _anomaly_row("blk_b", 0.9, _ID_B),
            _anomaly_row("blk_d", 0.4, _ID_D),
            _anomaly_row("blkA1", 0.95, _ID_M),
            _anomaly_row("blk_z", None, _ID_Z),
        ],
    )
    return database, run_id


def test_result_pages_are_stable_across_equal_scores_and_nulls(tmp_path: Path) -> None:
    database, run_id = _seeded_anomaly_run(tmp_path)
    score_order = [_ID_M, _ID_A, _ID_A2, _ID_B, _ID_C, _ID_D, _ID_Z]
    assert _walk_pages(database, run_id, limit=2, sort="score_desc") == score_order
    assert _walk_pages(database, run_id, limit=3, sort="score_desc") == score_order
    block_order = [_ID_M, _ID_A, _ID_A2, _ID_B, _ID_C, _ID_D, _ID_Z]
    assert _walk_pages(database, run_id, limit=2, sort="block_id_asc") == block_order


def test_result_page_filters_and_cursor_validation(tmp_path: Path) -> None:
    database, run_id = _seeded_anomaly_run(tmp_path)
    prefix_ids, prefix_cursor = _page_rows(
        database, run_id, limit=2, sort="score_desc", block_id_prefix="blk_"
    )
    assert prefix_ids == [_ID_A, _ID_A2]
    assert prefix_cursor is not None
    remaining, last_cursor = _page_rows(
        database,
        run_id,
        limit=10,
        sort="score_desc",
        block_id_prefix="blk_",
        cursor=prefix_cursor,
    )
    assert remaining == [_ID_B, _ID_C, _ID_D, _ID_Z]
    assert last_cursor is None

    min_ids, _next_cursor = _page_rows(
        database, run_id, limit=10, sort="score_desc", min_score=0.9
    )
    assert min_ids == [_ID_M, _ID_A, _ID_A2, _ID_B, _ID_C]

    first, next_cursor = _page_rows(database, run_id, limit=2, sort="score_desc")
    assert first == [_ID_M, _ID_A]
    assert next_cursor is not None
    with pytest.raises(ResultCursorError):
        _page_rows(
            database,
            run_id,
            limit=2,
            sort="block_id_asc",
            cursor=next_cursor,
        )
    with pytest.raises(ResultCursorError):
        _page_rows(
            database,
            run_id,
            limit=2,
            sort="score_desc",
            min_score=0.9,
            cursor=next_cursor,
        )
    source_run = database.get_analysis_run(run_id)
    assert source_run is not None
    other_run_id = _queued_run(
        database,
        UUID(str(source_run["project_id"])),
        UUID(str(source_run["requested_by_user_id"])),
        UUID(str(source_run["model_version_id"])),
    )
    with pytest.raises(ResultCursorError):
        _page_rows(
            database,
            other_run_id,
            limit=2,
            sort="score_desc",
            cursor=next_cursor,
        )
    with pytest.raises(ResultCursorError):
        _page_rows(database, run_id, limit=2, sort="score_desc", cursor="not-a-cursor")
    empty = database.list_anomaly_result_page(
        run_id,
        AnomalyResultPageQuery(limit=10, sort="block_id_asc", block_id_prefix="missing"),
    )
    assert empty.rows == []
    assert empty.next_cursor is None
