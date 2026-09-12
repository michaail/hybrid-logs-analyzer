"""Versioned database migrations for the API metadata store."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any, Protocol
from uuid import uuid4

from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase, utc_now, _sqlite_path_from_url

INITIAL_SCHEMA_VERSION = "001_initial_schema"
SHARED_STATE_VERSION = "002_shared_durable_runtime_state"
# F-02 originally numbered this 002; F-01 already occupied that slot.
PACKAGE_ADMISSION_VERSION = "003_model_package_admission"
OBJECT_CHECKSUM_VERSION = "004_model_object_checksum"
PREPROCESSING_BUNDLE_VERSION = "005_preprocessing_bundles"
RESULT_INSPECTION_INDEXES_VERSION = "006_result_inspection_indexes"
_MIGRATION_ORDER = (
    INITIAL_SCHEMA_VERSION,
    SHARED_STATE_VERSION,
    PACKAGE_ADMISSION_VERSION,
    OBJECT_CHECKSUM_VERSION,
    PREPROCESSING_BUNDLE_VERSION,
    RESULT_INSPECTION_INDEXES_VERSION,
)

_INITIAL_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE CHECK (username = lower(username)),
        password_hash TEXT NOT NULL,
        is_administrator INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memberships (
        project_id TEXT NOT NULL REFERENCES projects(id),
        user_id TEXT NOT NULL REFERENCES users(id),
        role TEXT NOT NULL CHECK (role IN ('operator', 'publisher')),
        PRIMARY KEY (project_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS model_versions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        model_identifier TEXT NOT NULL,
        version TEXT NOT NULL,
        source_compatibility TEXT NOT NULL CHECK (source_compatibility = 'hdfs'),
        status TEXT NOT NULL CHECK (status IN ('eligible', 'published')),
        pipeline_run_id TEXT NOT NULL,
        artifact_reference TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        external_evaluation_evidence TEXT NOT NULL,
        created_at TEXT NOT NULL,
        published_at TEXT,
        published_by_user_id TEXT REFERENCES users(id),
        UNIQUE (project_id, model_identifier, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_runs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        model_version_id TEXT NOT NULL REFERENCES model_versions(id),
        requested_by_user_id TEXT NOT NULL REFERENCES users(id),
        source_compatibility TEXT NOT NULL CHECK (source_compatibility = 'hdfs'),
        log_reference TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('queued', 'rejected', 'not_supported')),
        validation_report_json TEXT,
        error_code TEXT,
        created_at TEXT NOT NULL,
        completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS anomaly_results (
        id TEXT PRIMARY KEY,
        analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id),
        record_reference TEXT NOT NULL,
        anomaly_score REAL,
        anomaly_level TEXT,
        decision_threshold REAL,
        context_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        actor_user_id TEXT REFERENCES users(id),
        project_id TEXT REFERENCES projects(id),
        action TEXT NOT NULL,
        resource_type TEXT NOT NULL,
        resource_id TEXT,
        details_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memberships_user_id ON memberships(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_model_versions_project_id ON model_versions(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_runs_project_id ON analysis_runs(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_anomaly_results_run_id ON anomaly_results(analysis_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_project_id ON audit_events(project_id)",
)

_DATASETS_TABLE = """
CREATE TABLE datasets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    storage_kind TEXT NOT NULL CHECK (storage_kind IN ('workspace', 'object')),
    object_reference TEXT NOT NULL,
    checksum TEXT,
    source_compatibility TEXT NOT NULL CHECK (source_compatibility = 'hdfs'),
    created_at TEXT NOT NULL,
    UNIQUE (project_id, storage_kind, object_reference),
    CHECK (
        storage_kind <> 'object'
        OR (checksum IS NOT NULL AND checksum <> '')
    )
)
"""

_ANALYSIS_RUNS_REPLACEMENT = """
CREATE TABLE analysis_runs_002 (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    model_version_id TEXT NOT NULL REFERENCES model_versions(id),
    requested_by_user_id TEXT NOT NULL REFERENCES users(id),
    source_compatibility TEXT NOT NULL CHECK (source_compatibility = 'hdfs'),
    log_reference TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'completed', 'failed', 'rejected', 'not_supported')
    ),
    validation_report_json TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    dataset_id TEXT REFERENCES datasets(id),
    results_summary_json TEXT,
    CHECK (
        (status = 'rejected' AND dataset_id IS NULL)
        OR (status <> 'rejected' AND dataset_id IS NOT NULL)
    )
)
"""

_ANOMALY_RESULTS_REPLACEMENT = """
CREATE TABLE anomaly_results_002 (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL REFERENCES analysis_runs_002(id),
    record_reference TEXT NOT NULL,
    anomaly_score REAL,
    anomaly_level TEXT,
    decision_threshold REAL,
    context_json TEXT NOT NULL
)
"""

_MODEL_VERSIONS_OBJECT_CHECKSUM = """
CREATE TABLE model_versions_004 (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    model_identifier TEXT NOT NULL,
    version TEXT NOT NULL,
    source_compatibility TEXT NOT NULL CHECK (source_compatibility = 'hdfs'),
    status TEXT NOT NULL CHECK (status IN ('eligible', 'published')),
    pipeline_run_id TEXT NOT NULL,
    artifact_reference TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    external_evaluation_evidence TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    published_by_user_id TEXT REFERENCES users(id),
    storage_kind TEXT NOT NULL CHECK (storage_kind IN ('workspace', 'object')),
    checksum TEXT,
    package_reference TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    UNIQUE (project_id, model_identifier, version),
    CHECK (
        storage_kind <> 'object'
        OR (checksum IS NOT NULL AND checksum <> '')
    )
)
"""
_MODEL_VERSIONS_COPY_COLUMNS = (
    "id, project_id, model_identifier, version, source_compatibility, status, "
    "pipeline_run_id, artifact_reference, metrics_json, metadata_json, "
    "external_evaluation_evidence, created_at, published_at, published_by_user_id, "
    "storage_kind, checksum, package_reference, artifact_sha256"
)
_POSTGRES_OBJECT_CHECKSUM_CONSTRAINT = "model_versions_object_kind_checksum_check"

_PREPROCESSING_BUNDLES_TABLE = """
CREATE TABLE IF NOT EXISTS preprocessing_bundles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    identifier TEXT NOT NULL,
    version TEXT NOT NULL,
    object_prefix TEXT NOT NULL,
    manifest_checksum TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (project_id, identifier, version)
)
"""
_PREPROCESSING_BUNDLE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_preprocessing_bundles_project_id "
    "ON preprocessing_bundles(project_id)"
)
_PREPROCESSING_BUNDLE_MODEL_COLUMN = (
    "ALTER TABLE model_versions ADD COLUMN preprocessing_bundle_id TEXT "
    "REFERENCES preprocessing_bundles(id)"
)
_RESULT_INSPECTION_INDEX_STATEMENTS: tuple[str, ...] = (
    """
    CREATE INDEX IF NOT EXISTS idx_anomaly_results_run_score_desc
    ON anomaly_results (analysis_run_id, anomaly_score, record_reference, id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_anomaly_results_run_block_id
    ON anomaly_results (analysis_run_id, record_reference, id)
    """,
)

_PACKAGE_ADMISSION_STATEMENTS: tuple[str, ...] = (
    """
    ALTER TABLE model_versions
    ADD COLUMN package_reference TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE model_versions
    ADD COLUMN artifact_sha256 TEXT NOT NULL DEFAULT ''
    """,
)

_POSTGRES_MIGRATION_LOCK = 6_815_717_470_146_882_780
_IDEMPOTENT_ADD_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    PACKAGE_ADMISSION_VERSION: (
        ("model_versions", "package_reference"),
        ("model_versions", "artifact_sha256"),
    ),
    PREPROCESSING_BUNDLE_VERSION: (("model_versions", "preprocessing_bundle_id"),),
}


class _Executor(Protocol):
    def execute(self, query: str, parameters: Iterable[object] = ()) -> Any: ...


class _SqliteRebuildConnection:
    """Run parameterized SQL against a SQLite rebuild transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def execute(self, query: str, parameters: Iterable[object] = ()) -> Any:
        return self._connection.execute(query, tuple(parameters))


def apply_migrations(database: ApiDatabase, *, target: str | None = None) -> None:
    """Apply every pending migration atomically and record its version."""
    if target is not None and target not in _MIGRATION_ORDER:
        raise ValueError(f"Unknown migration target {target!r}.")

    with database.session() as connection:
        if database.uses_postgresql:
            connection.execute("SELECT pg_advisory_xact_lock(?)", (_POSTGRES_MIGRATION_LOCK,))
        _ensure_schema_migrations(connection)
        applied_versions = _read_applied_versions(connection)
        if _should_apply(INITIAL_SCHEMA_VERSION, target) and INITIAL_SCHEMA_VERSION not in applied_versions:
            for statement in _INITIAL_SCHEMA_STATEMENTS:
                connection.execute(statement)
            _record_migration(connection, INITIAL_SCHEMA_VERSION)
            applied_versions.add(INITIAL_SCHEMA_VERSION)
        if database.uses_postgresql:
            if (
                _should_apply(SHARED_STATE_VERSION, target)
                and SHARED_STATE_VERSION not in applied_versions
            ):
                _upgrade_shared_state(connection)
                _record_migration(connection, SHARED_STATE_VERSION)
                applied_versions.add(SHARED_STATE_VERSION)
            if (
                _should_apply(PACKAGE_ADMISSION_VERSION, target)
                and PACKAGE_ADMISSION_VERSION not in applied_versions
            ):
                _apply_package_admission(database, connection)
                applied_versions.add(PACKAGE_ADMISSION_VERSION)
            if (
                _should_apply(OBJECT_CHECKSUM_VERSION, target)
                and OBJECT_CHECKSUM_VERSION not in applied_versions
            ):
                _apply_object_checksum_postgres(connection)
                _record_migration(connection, OBJECT_CHECKSUM_VERSION)
                applied_versions.add(OBJECT_CHECKSUM_VERSION)
            if (
                _should_apply(PREPROCESSING_BUNDLE_VERSION, target)
                and PREPROCESSING_BUNDLE_VERSION not in applied_versions
            ):
                _apply_preprocessing_bundles(database, connection)
            if (
                _should_apply(RESULT_INSPECTION_INDEXES_VERSION, target)
                and RESULT_INSPECTION_INDEXES_VERSION not in _read_applied_versions(connection)
            ):
                _apply_result_inspection_indexes(connection)
            return

    if (
        not database.uses_postgresql
        and _should_apply(SHARED_STATE_VERSION, target)
        and SHARED_STATE_VERSION not in _current_applied_versions(database)
    ):
        _upgrade_shared_state_sqlite(database)

    if (
        not database.uses_postgresql
        and _should_apply(PACKAGE_ADMISSION_VERSION, target)
        and PACKAGE_ADMISSION_VERSION not in _current_applied_versions(database)
    ):
        with database.session() as connection:
            _apply_package_admission(database, connection)

    if (
        not database.uses_postgresql
        and _should_apply(OBJECT_CHECKSUM_VERSION, target)
        and OBJECT_CHECKSUM_VERSION not in _current_applied_versions(database)
    ):
        _upgrade_model_object_checksum_sqlite(database)

    if (
        not database.uses_postgresql
        and _should_apply(PREPROCESSING_BUNDLE_VERSION, target)
        and PREPROCESSING_BUNDLE_VERSION not in _current_applied_versions(database)
    ):
        with database.session() as connection:
            _apply_preprocessing_bundles(database, connection)

    if (
        not database.uses_postgresql
        and _should_apply(RESULT_INSPECTION_INDEXES_VERSION, target)
        and RESULT_INSPECTION_INDEXES_VERSION not in _current_applied_versions(database)
    ):
        with database.session() as connection:
            _apply_result_inspection_indexes(connection)


def main() -> None:
    """Run pending migrations using the configured runtime database URL."""
    settings = ApiSettings.from_environment()
    database = ApiDatabase(settings.database_url)
    database.apply_migrations()
    print("Database migrations completed.")


def _apply_package_admission(database: ApiDatabase, connection: Any) -> None:
    _apply_migration_statements(
        database, connection, PACKAGE_ADMISSION_VERSION, _PACKAGE_ADMISSION_STATEMENTS
    )
    _record_migration(connection, PACKAGE_ADMISSION_VERSION)


def _apply_preprocessing_bundles(database: ApiDatabase, connection: Any) -> None:
    connection.execute(_PREPROCESSING_BUNDLES_TABLE)
    connection.execute(_PREPROCESSING_BUNDLE_INDEX)
    if "preprocessing_bundle_id" not in _table_columns(database, connection, "model_versions"):
        connection.execute(_PREPROCESSING_BUNDLE_MODEL_COLUMN)
    _record_migration(connection, PREPROCESSING_BUNDLE_VERSION)


def _apply_result_inspection_indexes(connection: _Executor) -> None:
    for statement in _RESULT_INSPECTION_INDEX_STATEMENTS:
        connection.execute(statement)
    _record_migration(connection, RESULT_INSPECTION_INDEXES_VERSION)


def _apply_object_checksum_postgres(connection: _Executor) -> None:
    existing = connection.execute(
        """
        SELECT 1
        FROM pg_constraint
        WHERE conname = ?
        """,
        (_POSTGRES_OBJECT_CHECKSUM_CONSTRAINT,),
    ).fetchone()
    if existing is not None:
        return
    connection.execute(
        f"""
        ALTER TABLE model_versions
        ADD CONSTRAINT {_POSTGRES_OBJECT_CHECKSUM_CONSTRAINT}
        CHECK (
            storage_kind <> 'object'
            OR (checksum IS NOT NULL AND checksum <> '')
        )
        """
    )


def _upgrade_model_object_checksum_sqlite(database: ApiDatabase) -> None:
    """Rebuild SQLite model_versions so object kind requires a checksum."""
    database_path = _sqlite_path_from_url(database.database_url)
    connection = sqlite3.connect(str(database_path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        executor = _SqliteRebuildConnection(connection)
        if OBJECT_CHECKSUM_VERSION in _read_applied_versions(executor):
            connection.execute("ROLLBACK")
            return
        connection.execute(_MODEL_VERSIONS_OBJECT_CHECKSUM)
        connection.execute(
            f"""
            INSERT INTO model_versions_004 ({_MODEL_VERSIONS_COPY_COLUMNS})
            SELECT {_MODEL_VERSIONS_COPY_COLUMNS}
            FROM model_versions
            """
        )
        connection.execute("DROP TABLE model_versions")
        connection.execute("ALTER TABLE model_versions_004 RENAME TO model_versions")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_model_versions_project_id ON model_versions(project_id)"
        )
        _record_migration(executor, OBJECT_CHECKSUM_VERSION)
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"Object-checksum migration left foreign-key violations: {violations}"
            )
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _apply_migration_statements(
    database: ApiDatabase,
    connection: Any,
    version: str,
    statements: tuple[str, ...],
) -> None:
    additions = _IDEMPOTENT_ADD_COLUMNS.get(version)
    if additions is None:
        for statement in statements:
            connection.execute(statement)
        return
    for statement, (table, column) in zip(statements, additions, strict=True):
        if column in _table_columns(database, connection, table):
            continue
        connection.execute(statement)


def _table_columns(database: ApiDatabase, connection: Any, table: str) -> set[str]:
    if database.uses_postgresql:
        rows = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = ?
            """,
            (table,),
        ).fetchall()
        return {str(row["column_name"]) for row in rows}
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _should_apply(version: str, target: str | None) -> bool:
    if target is None:
        return True
    return _MIGRATION_ORDER.index(version) <= _MIGRATION_ORDER.index(target)


def _ensure_schema_migrations(connection: _Executor) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _record_migration(connection: _Executor, version: str) -> None:
    connection.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, utc_now()),
    )


def _read_applied_versions(connection: _Executor) -> set[str]:
    return _applied_versions(connection.execute("SELECT version FROM schema_migrations"))


def _current_applied_versions(database: ApiDatabase) -> set[str]:
    with database.session() as connection:
        _ensure_schema_migrations(connection)
        return _read_applied_versions(connection)


def _upgrade_shared_state_sqlite(database: ApiDatabase) -> None:
    """Rebuild SQLite run/result tables with foreign keys disabled before BEGIN."""
    database_path = _sqlite_path_from_url(database.database_url)
    connection = sqlite3.connect(str(database_path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        executor = _SqliteRebuildConnection(connection)
        if SHARED_STATE_VERSION in _read_applied_versions(executor):
            connection.execute("ROLLBACK")
            return
        _upgrade_shared_state(executor)
        _record_migration(executor, SHARED_STATE_VERSION)
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Shared-state migration left foreign-key violations: {violations}")
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _upgrade_shared_state(connection: _Executor) -> None:
    """Create datasets, widen model pointers, and rebuild analysis run/result tables."""
    connection.execute(_DATASETS_TABLE)
    connection.execute(
        "ALTER TABLE model_versions ADD COLUMN storage_kind TEXT NOT NULL DEFAULT 'workspace'"
    )
    connection.execute("ALTER TABLE model_versions ADD COLUMN checksum TEXT")
    connection.execute(_ANALYSIS_RUNS_REPLACEMENT)
    _copy_analysis_runs(connection)
    connection.execute(_ANOMALY_RESULTS_REPLACEMENT)
    connection.execute("INSERT INTO anomaly_results_002 SELECT * FROM anomaly_results")
    connection.execute("DROP TABLE anomaly_results")
    connection.execute("DROP TABLE analysis_runs")
    connection.execute("ALTER TABLE analysis_runs_002 RENAME TO analysis_runs")
    connection.execute("ALTER TABLE anomaly_results_002 RENAME TO anomaly_results")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_runs_project_id ON analysis_runs(project_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_anomaly_results_run_id ON anomaly_results(analysis_run_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_datasets_project_id ON datasets(project_id)"
    )


def _copy_analysis_runs(connection: _Executor) -> None:
    runs = [dict(row) for row in connection.execute("SELECT * FROM analysis_runs").fetchall()]
    dataset_ids: dict[tuple[str, str], str] = {}
    created_at = utc_now()
    for run in runs:
        dataset_id: str | None = None
        if str(run["status"]) != "rejected":
            key = (str(run["project_id"]), str(run["log_reference"]))
            dataset_id = dataset_ids.get(key)
            if dataset_id is None:
                dataset_id = str(uuid4())
                dataset_ids[key] = dataset_id
                connection.execute(
                    """
                    INSERT INTO datasets (
                        id, project_id, storage_kind, object_reference, checksum,
                        source_compatibility, created_at
                    ) VALUES (?, ?, 'workspace', ?, NULL, 'hdfs', ?)
                    """,
                    (dataset_id, key[0], key[1], created_at),
                )
        connection.execute(
            """
            INSERT INTO analysis_runs_002 (
                id, project_id, model_version_id, requested_by_user_id, source_compatibility,
                log_reference, status, validation_report_json, error_code, created_at,
                completed_at, dataset_id, results_summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                str(run["id"]),
                str(run["project_id"]),
                str(run["model_version_id"]),
                str(run["requested_by_user_id"]),
                str(run["source_compatibility"]),
                str(run["log_reference"]),
                str(run["status"]),
                run["validation_report_json"],
                run["error_code"],
                str(run["created_at"]),
                run["completed_at"],
                dataset_id,
            ),
        )


def _applied_versions(rows: Iterable[Mapping[str, object]]) -> set[str]:
    """Return migration versions from SQLite rows or Psycopg dictionaries."""
    versions: set[str] = set()
    for row in rows:
        versions.add(str(row["version"]))
    return versions


if __name__ == "__main__":
    main()
