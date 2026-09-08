"""Database persistence for API identities, project resources, and audit events."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4


def utc_now() -> str:
    """Return a UTC timestamp suitable for API records."""
    return datetime.now(timezone.utc).isoformat()


class DatabaseIntegrityError(RuntimeError):
    """Normalize database constraint failures across supported drivers."""


DatabaseRow = dict[str, Any]


class _DatabaseConnection:
    """Translate repository parameter placeholders for the active DB-API driver."""

    def __init__(self, connection: Any, *, uses_postgresql: bool) -> None:
        self._connection = connection
        self._uses_postgresql = uses_postgresql

    def execute(self, query: str, parameters: Iterable[object] = ()) -> Any:
        if self._uses_postgresql:
            query = query.replace("?", "%s")
        return self._connection.execute(query, tuple(parameters))


class ApiDatabase:
    """Small SQL repository; every request gets a short-lived transaction."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._uses_postgresql = database_url.startswith(("postgres://", "postgresql://"))
        self._integrity_errors: tuple[type[BaseException], ...] = (sqlite3.IntegrityError,)

    def apply_migrations(self) -> None:
        """Apply all versioned migrations before the API accepts traffic."""
        from src.api.migrations import apply_migrations

        apply_migrations(self)

    @property
    def uses_postgresql(self) -> bool:
        """Return whether this repository connects to PostgreSQL."""
        return self._uses_postgresql

    @contextmanager
    def session(self) -> Generator[_DatabaseConnection, None, None]:
        """Yield a transaction with foreign keys enabled when using SQLite."""
        connection = self._open_connection()
        try:
            yield _DatabaseConnection(connection, uses_postgresql=self._uses_postgresql)
            connection.commit()
        except BaseException as error:
            connection.rollback()
            if isinstance(error, self._integrity_errors):
                raise DatabaseIntegrityError("A database constraint was violated.") from error
            raise
        finally:
            connection.close()

    def healthcheck(self) -> bool:
        """Return whether the configured database accepts a trivial query."""
        try:
            with self.session() as connection:
                return connection.execute("SELECT 1").fetchone() is not None
        except Exception:
            return False

    def _open_connection(self) -> Any:
        if not self._uses_postgresql:
            database_path = _sqlite_path_from_url(self.database_url)
            database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(database_path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection

        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError(
                "PostgreSQL support requires psycopg. Install requirements-api.txt before starting."
            ) from error
        self._integrity_errors = (sqlite3.IntegrityError, psycopg.IntegrityError)
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def get_user_by_id(self, user_id: UUID) -> DatabaseRow | None:
        return self._one("SELECT * FROM users WHERE id = ?", (str(user_id),))

    def get_user_by_username(self, username: str) -> DatabaseRow | None:
        return self._one("SELECT * FROM users WHERE username = ?", (username,))

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        is_administrator: bool,
    ) -> DatabaseRow:
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

    def create_project(self, name: str) -> DatabaseRow:
        project_id = str(uuid4())
        created_at = utc_now()
        with self.session() as connection:
            connection.execute(
                "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
                (project_id, name, created_at),
            )
        return self.get_project(UUID(project_id)) or self._missing_record("project")

    def get_project(self, project_id: UUID) -> DatabaseRow | None:
        return self._one("SELECT * FROM projects WHERE id = ?", (str(project_id),))

    def list_projects_for_user(self, user_id: UUID, is_administrator: bool) -> list[DatabaseRow]:
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

    def grant_membership(self, project_id: UUID, user_id: UUID, role: str) -> DatabaseRow:
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

    def get_membership(self, project_id: UUID, user_id: UUID) -> DatabaseRow | None:
        return self._one(
            "SELECT * FROM memberships WHERE project_id = ? AND user_id = ?",
            (str(project_id), str(user_id)),
        )

    def list_memberships(self, project_id: UUID) -> list[DatabaseRow]:
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
    ) -> DatabaseRow:
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

    def get_model_version(self, model_id: UUID) -> DatabaseRow | None:
        return self._one("SELECT * FROM model_versions WHERE id = ?", (str(model_id),))

    def list_model_versions(self, project_id: UUID) -> list[DatabaseRow]:
        return self._all(
            """
            SELECT * FROM model_versions
            WHERE project_id = ?
            ORDER BY model_identifier, version
            """,
            (str(project_id),),
        )

    def publish_model_version(self, model_id: UUID, publisher_id: UUID) -> DatabaseRow:
        published_at = utc_now()
        with self.session() as connection:
            updated_rows = connection.execute(
                """
                UPDATE model_versions
                SET status = 'published', published_at = ?, published_by_user_id = ?
                WHERE id = ? AND status = 'eligible'
                """,
                (published_at, str(publisher_id), str(model_id)),
            ).rowcount
            if updated_rows != 1:
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
    ) -> DatabaseRow:
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

    def get_analysis_run(self, run_id: UUID) -> DatabaseRow | None:
        return self._one("SELECT * FROM analysis_runs WHERE id = ?", (str(run_id),))

    def list_analysis_runs(self, project_id: UUID) -> list[DatabaseRow]:
        return self._all(
            "SELECT * FROM analysis_runs WHERE project_id = ? ORDER BY created_at DESC",
            (str(project_id),),
        )

    def list_anomaly_results(self, run_id: UUID) -> list[DatabaseRow]:
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

    def list_audit_events(self, project_id: UUID) -> list[DatabaseRow]:
        return self._all(
            "SELECT * FROM audit_events WHERE project_id = ? ORDER BY created_at DESC",
            (str(project_id),),
        )

    def _one(self, query: str, parameters: Iterable[object]) -> DatabaseRow | None:
        with self.session() as connection:
            row = connection.execute(query, tuple(parameters)).fetchone()
            return dict(row) if row is not None else None

    def _all(self, query: str, parameters: Iterable[object] = ()) -> list[DatabaseRow]:
        with self.session() as connection:
            return [dict(row) for row in connection.execute(query, tuple(parameters)).fetchall()]

    @staticmethod
    def _missing_record(resource_name: str) -> DatabaseRow:
        raise RuntimeError(f"Created {resource_name} could not be read.")


def _sqlite_path_from_url(database_url: str) -> Path:
    """Resolve a sqlite URL while rejecting unsupported database URL schemes."""
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RuntimeError("DATABASE_URL must use a PostgreSQL or sqlite URL.")
    if database_url == "sqlite:///:memory:":
        raise RuntimeError("In-memory SQLite is not supported because each request opens a new connection.")
    if parsed.netloc:
        raise RuntimeError("SQLite database URLs must not specify a remote host.")
    database_path = unquote(database_url.removeprefix("sqlite:///"))
    if not database_path or database_path == "/":
        raise RuntimeError("SQLite database URL must include a database path.")
    return Path(database_path).resolve()
