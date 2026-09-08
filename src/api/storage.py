"""SQLite persistence for API identities, project resources, and audit events."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4


def utc_now() -> str:
    """Return a UTC timestamp suitable for API records."""
    return datetime.now(timezone.utc).isoformat()


class ApiDatabase:
    """Small SQLite repository; every request gets a short-lived transaction."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        """Create all API tables if they do not already exist."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    is_administrator INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memberships (
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    user_id TEXT NOT NULL REFERENCES users(id),
                    role TEXT NOT NULL CHECK (role IN ('operator', 'publisher')),
                    PRIMARY KEY (project_id, user_id)
                );

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
                );

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
                );

                CREATE TABLE IF NOT EXISTS anomaly_results (
                    id TEXT PRIMARY KEY,
                    analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id),
                    record_reference TEXT NOT NULL,
                    anomaly_score REAL,
                    anomaly_level TEXT,
                    decision_threshold REAL,
                    context_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    actor_user_id TEXT REFERENCES users(id),
                    project_id TEXT REFERENCES projects(id),
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @contextmanager
    def session(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a transaction with foreign keys enabled."""
        connection = sqlite3.connect(self.database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_user_by_id(self, user_id: UUID) -> sqlite3.Row | None:
        return self._one("SELECT * FROM users WHERE id = ?", (str(user_id),))

    def get_user_by_username(self, username: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM users WHERE username = ?", (username,))

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        is_administrator: bool,
    ) -> sqlite3.Row:
        user_id = str(uuid4())
        created_at = utc_now()
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO users (id, username, password_hash, is_administrator, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, username, password_hash, int(is_administrator), created_at),
            )
        return self.get_user_by_id(UUID(user_id)) or self._missing_record("user")

    def create_project(self, name: str) -> sqlite3.Row:
        project_id = str(uuid4())
        created_at = utc_now()
        with self.session() as connection:
            connection.execute(
                "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
                (project_id, name, created_at),
            )
        return self.get_project(UUID(project_id)) or self._missing_record("project")

    def get_project(self, project_id: UUID) -> sqlite3.Row | None:
        return self._one("SELECT * FROM projects WHERE id = ?", (str(project_id),))

    def list_projects_for_user(self, user_id: UUID, is_administrator: bool) -> list[sqlite3.Row]:
        if is_administrator:
            return self._all("SELECT * FROM projects ORDER BY name")
        return self._all(
            """
            SELECT projects.*
            FROM projects
            JOIN memberships ON memberships.project_id = projects.id
            WHERE memberships.user_id = ?
            ORDER BY projects.name
            """,
            (str(user_id),),
        )

    def grant_membership(self, project_id: UUID, user_id: UUID, role: str) -> sqlite3.Row:
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO memberships (project_id, user_id, role)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role
                """,
                (str(project_id), str(user_id), role),
            )
        return self.get_membership(project_id, user_id) or self._missing_record("membership")

    def get_membership(self, project_id: UUID, user_id: UUID) -> sqlite3.Row | None:
        return self._one(
            "SELECT * FROM memberships WHERE project_id = ? AND user_id = ?",
            (str(project_id), str(user_id)),
        )

    def list_memberships(self, project_id: UUID) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM memberships WHERE project_id = ? ORDER BY user_id", (str(project_id),)
        )

    def create_model_version(
        self,
        *,
        project_id: UUID,
        model_identifier: str,
        version: str,
        pipeline_run_id: str,
        artifact_reference: str,
        metrics_json: str,
        metadata_json: str,
        external_evaluation_evidence: str,
    ) -> sqlite3.Row:
        model_id = str(uuid4())
        created_at = utc_now()
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO model_versions (
                    id, project_id, model_identifier, version, source_compatibility, status,
                    pipeline_run_id, artifact_reference, metrics_json, metadata_json,
                    external_evaluation_evidence, created_at
                ) VALUES (?, ?, ?, ?, 'hdfs', 'eligible', ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    str(project_id),
                    model_identifier,
                    version,
                    pipeline_run_id,
                    artifact_reference,
                    metrics_json,
                    metadata_json,
                    external_evaluation_evidence,
                    created_at,
                ),
            )
        return self.get_model_version(UUID(model_id)) or self._missing_record("model version")

    def get_model_version(self, model_id: UUID) -> sqlite3.Row | None:
        return self._one("SELECT * FROM model_versions WHERE id = ?", (str(model_id),))

    def list_model_versions(self, project_id: UUID) -> list[sqlite3.Row]:
        return self._all(
            """
            SELECT * FROM model_versions
            WHERE project_id = ?
            ORDER BY model_identifier, version
            """,
            (str(project_id),),
        )

    def publish_model_version(self, model_id: UUID, publisher_id: UUID) -> sqlite3.Row:
        published_at = utc_now()
        with self.session() as connection:
            connection.execute(
                """
                UPDATE model_versions
                SET status = 'published', published_at = ?, published_by_user_id = ?
                WHERE id = ? AND status = 'eligible'
                """,
                (published_at, str(publisher_id), str(model_id)),
            )
            if connection.total_changes != 1:
                raise ValueError("Model version is not eligible for publication.")
        return self.get_model_version(model_id) or self._missing_record("model version")

    def create_analysis_run(
        self,
        *,
        project_id: UUID,
        model_version_id: UUID,
        requested_by_user_id: UUID,
        log_reference: str,
        status: str,
        validation_report_json: str | None,
        error_code: str | None,
        completed_at: str | None,
    ) -> sqlite3.Row:
        run_id = str(uuid4())
        created_at = utc_now()
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO analysis_runs (
                    id, project_id, model_version_id, requested_by_user_id, source_compatibility,
                    log_reference, status, validation_report_json, error_code, created_at, completed_at
                ) VALUES (?, ?, ?, ?, 'hdfs', ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(project_id),
                    str(model_version_id),
                    str(requested_by_user_id),
                    log_reference,
                    status,
                    validation_report_json,
                    error_code,
                    created_at,
                    completed_at,
                ),
            )
        return self.get_analysis_run(UUID(run_id)) or self._missing_record("analysis run")

    def get_analysis_run(self, run_id: UUID) -> sqlite3.Row | None:
        return self._one("SELECT * FROM analysis_runs WHERE id = ?", (str(run_id),))

    def list_analysis_runs(self, project_id: UUID) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM analysis_runs WHERE project_id = ? ORDER BY created_at DESC",
            (str(project_id),),
        )

    def list_anomaly_results(self, run_id: UUID) -> list[sqlite3.Row]:
        return self._all(
            """
            SELECT * FROM anomaly_results
            WHERE analysis_run_id = ?
            ORDER BY anomaly_score DESC
            """,
            (str(run_id),),
        )

    def add_audit_event(
        self,
        *,
        actor_user_id: UUID | None,
        project_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        details_json: str,
    ) -> None:
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    id, actor_user_id, project_id, action, resource_type, resource_id,
                    details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    str(actor_user_id) if actor_user_id else None,
                    str(project_id) if project_id else None,
                    action,
                    resource_type,
                    str(resource_id) if resource_id else None,
                    details_json,
                    utc_now(),
                ),
            )

    def list_audit_events(self, project_id: UUID) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM audit_events WHERE project_id = ? ORDER BY created_at DESC",
            (str(project_id),),
        )

    def _one(self, query: str, parameters: Iterable[object]) -> sqlite3.Row | None:
        with self.session() as connection:
            return connection.execute(query, tuple(parameters)).fetchone()

    def _all(self, query: str, parameters: Iterable[object] = ()) -> list[sqlite3.Row]:
        with self.session() as connection:
            return connection.execute(query, tuple(parameters)).fetchall()

    @staticmethod
    def _missing_record(resource_name: str) -> sqlite3.Row:
        raise RuntimeError(f"Created {resource_name} could not be read.")
