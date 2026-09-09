"""Versioned database migrations for the API metadata store."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase, utc_now

_MIGRATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "001_initial_schema",
        (
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
        ),
    ),
)
_POSTGRES_MIGRATION_LOCK = 6_815_717_470_146_882_780


def apply_migrations(database: ApiDatabase) -> None:
    """Apply every pending migration atomically and record its version."""
    with database.session() as connection:
        if database.uses_postgresql:
            connection.execute("SELECT pg_advisory_xact_lock(?)", (_POSTGRES_MIGRATION_LOCK,))
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied_versions = _applied_versions(connection.execute("SELECT version FROM schema_migrations"))
        for version, statements in _MIGRATIONS:
            if version in applied_versions:
                continue
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, utc_now()),
            )


def main() -> None:
    """Run pending migrations using the configured runtime database URL."""
    settings = ApiSettings.from_environment()
    database = ApiDatabase(settings.database_url)
    database.apply_migrations()
    print("Database migrations completed.")


def _applied_versions(rows: Iterable[Mapping[str, object]]) -> set[str]:
    """Return migration versions from SQLite rows or Psycopg dictionaries."""
    versions: set[str] = set()
    for row in rows:
        versions.add(str(row["version"]))
    return versions


if __name__ == "__main__":
    main()
