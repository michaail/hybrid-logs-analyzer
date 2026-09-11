"""Database persistence for API identities, project resources, and audit events."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator, Iterable, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from src.api.security import canonical_username


def utc_now() -> str:
    """Return a UTC timestamp suitable for API records."""
    return datetime.now(timezone.utc).isoformat()


class DatabaseIntegrityError(RuntimeError):
    """Normalize database constraint failures across supported drivers."""


class DatasetPointerError(ValueError):
    """Raised when a kinded byte pointer cannot be stored."""


class RunStatusConflict(RuntimeError):
    """Raised when a compare-and-swap analysis-run transition does not apply."""


_STORAGE_KINDS = frozenset({"workspace", "object"})
_INITIAL_RUN_STATUSES = frozenset({"queued", "rejected", "not_supported"})
_LEGAL_RUN_TRANSITIONS = frozenset(
    {("queued", "running"), ("running", "completed"), ("running", "failed")}
)
_ANALYSIS_AUDIT_ACTIONS = {
    "queued": "analysis.queued",
    "running": "analysis.running",
    "completed": "analysis.completed",
    "failed": "analysis.failed",
    "rejected": "analysis.rejected",
    "not_supported": "analysis.not_supported",
}
_MODEL_VERSION_WITH_BUNDLE = """
SELECT
    model_versions.*,
    preprocessing_bundles.identifier AS preprocessing_bundle_identifier,
    preprocessing_bundles.version AS preprocessing_bundle_version,
    preprocessing_bundles.manifest_checksum AS preprocessing_bundle_digest,
    preprocessing_bundles.object_prefix AS preprocessing_bundle_prefix
FROM model_versions
LEFT JOIN preprocessing_bundles
    ON preprocessing_bundles.id = model_versions.preprocessing_bundle_id
""".strip()
_ANALYSIS_RUN_WITH_DATASET = """
SELECT r.*, d.storage_kind AS dataset_storage_kind, d.checksum AS dataset_checksum
FROM analysis_runs AS r
LEFT JOIN datasets AS d ON d.id = r.dataset_id
""".strip()


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
            if not self._uses_postgresql:
                connection.execute("BEGIN")
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
            connection = sqlite3.connect(
                database_path,
                check_same_thread=False,
                isolation_level=None,
            )
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
        return self._one("SELECT * FROM users WHERE username = ?", (username.lower(),))

    def list_users(self) -> list[DatabaseRow]:
        """List all provisioned accounts with their non-secret lifecycle state."""
        return self._all("SELECT * FROM users ORDER BY username")

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
                INSERT INTO users (id, username, password_hash, is_administrator, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (user_id, canonical_username(username), password_hash, int(is_administrator), created_at),
            )
        return self.get_user_by_id(UUID(user_id)) or self._missing_record("user")

    def create_administrator(self, *, username: str, password_hash: str) -> DatabaseRow:
        """Create the CLI-bootstrapped Administrator and its audit event atomically."""
        canonical = canonical_username(username)
        user_id = str(uuid4())
        created_at = utc_now()
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO users (id, username, password_hash, is_administrator, is_active, created_at)
                VALUES (?, ?, ?, 1, 1, ?)
                """,
                (user_id, canonical, password_hash, created_at),
            )
            self._insert_audit_event(
                connection,
                actor_user_id=None,
                project_id=None,
                action="user.bootstrapped",
                resource_type="user",
                resource_id=UUID(user_id),
                details_json=json.dumps({"username": canonical}, sort_keys=True),
            )
        return self.get_user_by_id(UUID(user_id)) or self._missing_record("user")

    def provision_project_account(
        self,
        *,
        username: str,
        password_hash: str,
        project_id: UUID,
        role: str,
        actor_user_id: UUID,
    ) -> tuple[DatabaseRow, DatabaseRow]:
        """Create a non-administrator account and its initial membership atomically."""
        canonical = canonical_username(username)
        user_id = str(uuid4())
        created_at = utc_now()
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO users (id, username, password_hash, is_administrator, is_active, created_at)
                VALUES (?, ?, ?, 0, 1, ?)
                """,
                (user_id, canonical, password_hash, created_at),
            )
            connection.execute(
                """
                INSERT INTO memberships (project_id, user_id, role)
                VALUES (?, ?, ?)
                """,
                (str(project_id), user_id, role),
            )
            self._insert_audit_event(
                connection,
                actor_user_id=actor_user_id,
                project_id=None,
                action="user.provisioned",
                resource_type="user",
                resource_id=UUID(user_id),
                details_json=json.dumps(
                    {"is_administrator": False, "username": canonical},
                    sort_keys=True,
                ),
            )
            self._insert_audit_event(
                connection,
                actor_user_id=actor_user_id,
                project_id=project_id,
                action="project.membership_granted",
                resource_type="membership",
                resource_id=UUID(user_id),
                details_json=json.dumps(
                    {"role": role, "user_id": user_id, "username": canonical},
                    sort_keys=True,
                ),
            )
        user = self.get_user_by_id(UUID(user_id)) or self._missing_record("user")
        membership = self.get_membership(project_id, UUID(user_id)) or self._missing_record("membership")
        return user, membership

    def set_user_active(
        self,
        *,
        user_id: UUID,
        is_active: bool,
        actor_user_id: UUID,
    ) -> DatabaseRow | None:
        """Activate or deactivate a non-administrator account with an audit event."""
        with self.session() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (str(user_id),)).fetchone()
            if row is None:
                return None
            user = dict(row)
            if user["is_administrator"]:
                raise ValueError(
                    "Administrator accounts cannot be changed through account activation."
                )
            previous_is_active = bool(user["is_active"])
            if previous_is_active == is_active:
                raise ValueError(
                    "Account is already active." if is_active else "Account is already deactivated."
                )
            connection.execute(
                "UPDATE users SET is_active = ? WHERE id = ?",
                (int(is_active), str(user_id)),
            )
            self._insert_audit_event(
                connection,
                actor_user_id=actor_user_id,
                project_id=None,
                action="user.reactivated" if is_active else "user.deactivated",
                resource_type="user",
                resource_id=user_id,
                details_json=json.dumps(
                    {
                        "is_active": is_active,
                        "previous_is_active": previous_is_active,
                        "username": str(user["username"]),
                    },
                    sort_keys=True,
                ),
            )
        return self.get_user_by_id(user_id) or self._missing_record("user")

    def create_project(self, name: str) -> DatabaseRow:
        project_id = str(uuid4())
        created_at = utc_now()
        with self.session() as connection:
            connection.execute(
                "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
                (project_id, name, created_at),
            )
        return self.get_project(UUID(project_id)) or self._missing_record("project")

    def create_project_with_audit(self, *, name: str, actor_user_id: UUID) -> DatabaseRow:
        """Create a project and its audit event in one transaction."""
        project_id = str(uuid4())
        created_at = utc_now()
        with self.session() as connection:
            connection.execute(
                "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
                (project_id, name, created_at),
            )
            self._insert_audit_event(
                connection,
                actor_user_id=actor_user_id,
                project_id=UUID(project_id),
                action="project.created",
                resource_type="project",
                resource_id=UUID(project_id),
                details_json=json.dumps({"name": name}, sort_keys=True),
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

    def create_membership(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        role: str,
        actor_user_id: UUID,
    ) -> DatabaseRow:
        """Grant a missing membership; a duplicate raises DatabaseIntegrityError."""
        with self.session() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (str(user_id),)).fetchone()
            username = str(dict(row)["username"]) if row is not None else str(user_id)
            connection.execute(
                """
                INSERT INTO memberships (project_id, user_id, role)
                VALUES (?, ?, ?)
                """,
                (str(project_id), str(user_id), role),
            )
            self._insert_audit_event(
                connection,
                actor_user_id=actor_user_id,
                project_id=project_id,
                action="project.membership_granted",
                resource_type="membership",
                resource_id=user_id,
                details_json=json.dumps(
                    {"role": role, "user_id": str(user_id), "username": username},
                    sort_keys=True,
                ),
            )
        return self.get_membership(project_id, user_id) or self._missing_record("membership")

    def update_membership_role(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        role: str,
        actor_user_id: UUID,
    ) -> DatabaseRow | None:
        """Change an existing membership role and record the before/after transition."""
        with self.session() as connection:
            row = connection.execute(
                "SELECT * FROM memberships WHERE project_id = ? AND user_id = ?",
                (str(project_id), str(user_id)),
            ).fetchone()
            if row is None:
                return None
            previous_role = str(dict(row)["role"])
            if previous_role == role:
                raise ValueError(f"Account already has the {role!r} role in this project.")
            connection.execute(
                """
                UPDATE memberships SET role = ?
                WHERE project_id = ? AND user_id = ?
                """,
                (role, str(project_id), str(user_id)),
            )
            self._insert_audit_event(
                connection,
                actor_user_id=actor_user_id,
                project_id=project_id,
                action="project.membership_role_changed",
                resource_type="membership",
                resource_id=user_id,
                details_json=json.dumps(
                    {
                        "new_role": role,
                        "previous_role": previous_role,
                        "user_id": str(user_id),
                    },
                    sort_keys=True,
                ),
            )
        return self.get_membership(project_id, user_id) or self._missing_record("membership")

    def revoke_membership(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        actor_user_id: UUID,
    ) -> bool:
        """Delete a membership; return whether one existed. Audit is transactional."""
        with self.session() as connection:
            row = connection.execute(
                "SELECT * FROM memberships WHERE project_id = ? AND user_id = ?",
                (str(project_id), str(user_id)),
            ).fetchone()
            if row is None:
                return False
            previous_role = str(dict(row)["role"])
            connection.execute(
                "DELETE FROM memberships WHERE project_id = ? AND user_id = ?",
                (str(project_id), str(user_id)),
            )
            self._insert_audit_event(
                connection,
                actor_user_id=actor_user_id,
                project_id=project_id,
                action="project.membership_revoked",
                resource_type="membership",
                resource_id=user_id,
                details_json=json.dumps(
                    {"previous_role": previous_role, "user_id": str(user_id)},
                    sort_keys=True,
                ),
            )
        return True

    def get_membership(self, project_id: UUID, user_id: UUID) -> DatabaseRow | None:
        return self._one(
            """
            SELECT memberships.project_id, memberships.user_id, memberships.role,
                   users.username, users.is_active
            FROM memberships
            JOIN users ON users.id = memberships.user_id
            WHERE memberships.project_id = ? AND memberships.user_id = ?
            """,
            (str(project_id), str(user_id)),
        )

    def list_memberships(self, project_id: UUID) -> list[DatabaseRow]:
        return self._all(
            """
            SELECT memberships.project_id, memberships.user_id, memberships.role,
                   users.username, users.is_active
            FROM memberships
            JOIN users ON users.id = memberships.user_id
            WHERE memberships.project_id = ?
            ORDER BY users.username
            """,
            (str(project_id),),
        )

    def create_model_version(
        self,
        *,
        project_id: UUID,
        model_identifier: str,
        version: str,
        pipeline_run_id: str,
        artifact_reference: str,
        package_reference: str,
        artifact_sha256: str,
        metrics_json: str,
        metadata_json: str,
        external_evaluation_evidence: str,
        storage_kind: str = "workspace",
        checksum: str | None = None,
        actor_user_id: UUID | None = None,
        model_id: UUID | None = None,
        preprocessing_bundle: Mapping[str, Any] | None = None,
        preprocessing_bundle_id: UUID | None = None,
    ) -> DatabaseRow:
        resolved_model_id = str(model_id) if model_id is not None else str(uuid4())
        created_at = utc_now()
        pointer_checksum = _normalized_checksum(storage_kind, checksum)
        with self.session() as connection:
            linked_bundle_id = _resolve_preprocessing_bundle_id(
                connection,
                project_id=project_id,
                created_at=created_at,
                preprocessing_bundle=preprocessing_bundle,
                preprocessing_bundle_id=preprocessing_bundle_id,
            )
            connection.execute(
                """
                INSERT INTO model_versions (
                    id, project_id, model_identifier, version, source_compatibility, status,
                    pipeline_run_id, artifact_reference, package_reference, artifact_sha256,
                    metrics_json, metadata_json, external_evaluation_evidence, created_at,
                    storage_kind, checksum, preprocessing_bundle_id
                ) VALUES (?, ?, ?, ?, 'hdfs', 'eligible', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_model_id,
                    str(project_id),
                    model_identifier,
                    version,
                    pipeline_run_id,
                    artifact_reference,
                    package_reference,
                    artifact_sha256,
                    metrics_json,
                    metadata_json,
                    external_evaluation_evidence,
                    created_at,
                    storage_kind,
                    pointer_checksum,
                    linked_bundle_id,
                ),
            )
            if actor_user_id is not None:
                self._insert_audit_event(
                    connection,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                    action="model.registered",
                    resource_type="model_version",
                    resource_id=UUID(resolved_model_id),
                    details_json=json.dumps(
                        {
                            "artifact_reference": artifact_reference,
                            "artifact_sha256": artifact_sha256,
                            "model_identifier": model_identifier,
                            "package_reference": package_reference,
                            "pipeline_run_id": pipeline_run_id,
                            "version": version,
                        },
                        sort_keys=True,
                    ),
                )
        return self.get_model_version(UUID(resolved_model_id)) or self._missing_record("model version")

    def get_model_version(self, model_id: UUID) -> DatabaseRow | None:
        return self._one(
            f"{_MODEL_VERSION_WITH_BUNDLE} WHERE model_versions.id = ?",
            (str(model_id),),
        )

    def list_model_versions(self, project_id: UUID) -> list[DatabaseRow]:
        return self._all(
            f"""
            {_MODEL_VERSION_WITH_BUNDLE}
            WHERE model_versions.project_id = ?
            ORDER BY model_versions.model_identifier, model_versions.version
            """,
            (str(project_id),),
        )

    def get_preprocessing_bundle(self, project_id: UUID, bundle_id: UUID) -> DatabaseRow | None:
        return self._one(
            """
            SELECT * FROM preprocessing_bundles
            WHERE id = ? AND project_id = ?
            """,
            (str(bundle_id), str(project_id)),
        )

    def publish_model_version(
        self,
        model_id: UUID,
        publisher_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> DatabaseRow:
        published_at = utc_now()
        with self.session() as connection:
            existing = connection.execute(
                "SELECT * FROM model_versions WHERE id = ?",
                (str(model_id),),
            ).fetchone()
            if existing is None:
                raise ValueError("Model version is not eligible for publication.")
            model = dict(existing)
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
            if actor_user_id is not None:
                self._insert_audit_event(
                    connection,
                    actor_user_id=actor_user_id,
                    project_id=UUID(str(model["project_id"])),
                    action="model.published",
                    resource_type="model_version",
                    resource_id=model_id,
                    details_json=json.dumps(
                        {
                            "model_identifier": str(model["model_identifier"]),
                            "version": str(model["version"]),
                        },
                        sort_keys=True,
                    ),
                )
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
        actor_user_id: UUID | None = None,
        results_summary_json: str | None = None,
        dataset_id: UUID | None = None,
    ) -> DatabaseRow:
        if status not in _INITIAL_RUN_STATUSES:
            raise ValueError(f"Analysis runs cannot be created with status {status!r}.")
        if status == "rejected" and dataset_id is not None:
            raise ValueError("Rejected analysis runs cannot attach a dataset.")
        if status != "rejected" and dataset_id is None:
            raise ValueError("Non-rejected analysis runs require a dataset_id.")
        run_id = str(uuid4())
        created_at = utc_now()
        with self.session() as connection:
            stored_dataset_id = None
            stored_log_reference = log_reference
            if status != "rejected":
                dataset_row = connection.execute(
                    "SELECT project_id, object_reference FROM datasets WHERE id = ?",
                    (str(dataset_id),),
                ).fetchone()
                if dataset_row is None:
                    raise ValueError("Dataset was not found.")
                dataset = dict(dataset_row)
                if str(dataset["project_id"]) != str(project_id):
                    raise ValueError("Dataset was not found.")
                stored_dataset_id = str(dataset_id)
                stored_log_reference = str(dataset["object_reference"])
            connection.execute(
                """
                INSERT INTO analysis_runs (
                    id, project_id, model_version_id, requested_by_user_id, source_compatibility,
                    log_reference, status, validation_report_json, error_code, created_at,
                    completed_at, dataset_id, results_summary_json
                ) VALUES (?, ?, ?, ?, 'hdfs', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(project_id),
                    str(model_version_id),
                    str(requested_by_user_id),
                    stored_log_reference,
                    status,
                    validation_report_json,
                    error_code,
                    created_at,
                    completed_at,
                    stored_dataset_id,
                    results_summary_json,
                ),
            )
            if actor_user_id is not None:
                self._insert_audit_event(
                    connection,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                    action=_ANALYSIS_AUDIT_ACTIONS[status],
                    resource_type="analysis_run",
                    resource_id=UUID(run_id),
                    details_json=json.dumps(
                        {"error_code": error_code, "status": status},
                        sort_keys=True,
                    ),
                )
        return self.get_analysis_run(UUID(run_id)) or self._missing_record("analysis run")

    def upsert_dataset(
        self,
        *,
        project_id: UUID,
        storage_kind: str,
        object_reference: str,
        checksum: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> DatabaseRow:
        """Return the project-owned dataset for a kinded pointer, inserting on first use."""
        with self.session() as connection:
            dataset_id = self._upsert_dataset(
                connection,
                project_id=project_id,
                storage_kind=storage_kind,
                object_reference=object_reference,
                checksum=checksum,
                actor_user_id=actor_user_id,
            )
        return self.get_dataset(UUID(dataset_id)) or self._missing_record("dataset")

    def create_dataset(
        self,
        *,
        project_id: UUID,
        storage_kind: str,
        object_reference: str,
        checksum: str | None,
        actor_user_id: UUID | None = None,
        dataset_id: UUID | None = None,
    ) -> DatabaseRow:
        """Insert one project-owned dataset pointer. Unique conflicts propagate."""

        resolved_id = str(dataset_id) if dataset_id is not None else str(uuid4())
        pointer_checksum = _normalized_checksum(storage_kind, checksum)
        created_at = utc_now()
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO datasets (
                    id, project_id, storage_kind, object_reference, checksum,
                    source_compatibility, created_at
                ) VALUES (?, ?, ?, ?, ?, 'hdfs', ?)
                """,
                (
                    resolved_id,
                    str(project_id),
                    storage_kind,
                    object_reference,
                    pointer_checksum,
                    created_at,
                ),
            )
            if actor_user_id is not None:
                self._insert_audit_event(
                    connection,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                    action="dataset.registered",
                    resource_type="dataset",
                    resource_id=UUID(resolved_id),
                    details_json=json.dumps(
                        {
                            "object_reference": object_reference,
                            "storage_kind": storage_kind,
                        },
                        sort_keys=True,
                    ),
                )
        return self.get_dataset(UUID(resolved_id)) or self._missing_record("dataset")

    def get_dataset(self, dataset_id: UUID) -> DatabaseRow | None:
        return self._one("SELECT * FROM datasets WHERE id = ?", (str(dataset_id),))

    def list_datasets(self, project_id: UUID) -> list[DatabaseRow]:
        return self._all(
            """
            SELECT * FROM datasets
            WHERE project_id = ?
            ORDER BY created_at, object_reference
            """,
            (str(project_id),),
        )

    def _upsert_dataset(
        self,
        connection: _DatabaseConnection,
        *,
        project_id: UUID,
        storage_kind: str,
        object_reference: str,
        checksum: str | None,
        actor_user_id: UUID | None,
    ) -> str:
        pointer_checksum = _normalized_checksum(storage_kind, checksum)
        row = connection.execute(
            """
            SELECT id FROM datasets
            WHERE project_id = ? AND storage_kind = ? AND object_reference = ?
            """,
            (str(project_id), storage_kind, object_reference),
        ).fetchone()
        if row is not None:
            return str(dict(row)["id"])
        dataset_id = str(uuid4())
        connection.execute("SAVEPOINT dataset_upsert")
        try:
            connection.execute(
                """
                INSERT INTO datasets (
                    id, project_id, storage_kind, object_reference, checksum,
                    source_compatibility, created_at
                ) VALUES (?, ?, ?, ?, ?, 'hdfs', ?)
                """,
                (
                    dataset_id,
                    str(project_id),
                    storage_kind,
                    object_reference,
                    pointer_checksum,
                    utc_now(),
                ),
            )
        except self._integrity_errors:
            connection.execute("ROLLBACK TO SAVEPOINT dataset_upsert")
            reused = connection.execute(
                """
                SELECT id FROM datasets
                WHERE project_id = ? AND storage_kind = ? AND object_reference = ?
                """,
                (str(project_id), storage_kind, object_reference),
            ).fetchone()
            if reused is None:
                raise
            return str(dict(reused)["id"])
        if actor_user_id is not None:
            self._insert_audit_event(
                connection,
                actor_user_id=actor_user_id,
                project_id=project_id,
                action="dataset.registered",
                resource_type="dataset",
                resource_id=UUID(dataset_id),
                details_json=json.dumps(
                    {
                        "object_reference": object_reference,
                        "storage_kind": storage_kind,
                    },
                    sort_keys=True,
                ),
            )
        return dataset_id

    def transition_analysis_run(
        self,
        run_id: UUID,
        *,
        expected_status: str,
        next_status: str,
        actor_user_id: UUID | None = None,
        error_code: str | None = None,
        results_summary_json: str | None = None,
        anomaly_results: Iterable[dict[str, Any]] | None = None,
    ) -> DatabaseRow:
        """Apply a legal compare-and-swap status transition inside one transaction."""
        if (expected_status, next_status) not in _LEGAL_RUN_TRANSITIONS:
            raise RunStatusConflict("Analysis run status transition was not applied.")
        if next_status == "completed" and results_summary_json is None:
            raise ValueError("Completed analysis runs require a stored results summary.")
        completed_at = utc_now() if next_status in {"completed", "failed"} else None
        with self.session() as connection:
            existing = connection.execute(
                "SELECT * FROM analysis_runs WHERE id = ?",
                (str(run_id),),
            ).fetchone()
            if existing is None:
                raise RunStatusConflict("Analysis run status transition was not applied.")
            run = dict(existing)
            if next_status == "running":
                updated_rows = connection.execute(
                    "UPDATE analysis_runs SET status = ? WHERE id = ? AND status = ?",
                    (next_status, str(run_id), expected_status),
                ).rowcount
            elif next_status == "failed":
                updated_rows = connection.execute(
                    """
                    UPDATE analysis_runs
                    SET status = ?, error_code = ?, completed_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (next_status, error_code, completed_at, str(run_id), expected_status),
                ).rowcount
            else:
                updated_rows = connection.execute(
                    """
                    UPDATE analysis_runs
                    SET status = ?, results_summary_json = ?, completed_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        next_status,
                        results_summary_json,
                        completed_at,
                        str(run_id),
                        expected_status,
                    ),
                ).rowcount
            if updated_rows != 1:
                raise RunStatusConflict("Analysis run status transition was not applied.")
            if next_status == "completed":
                self.replace_anomaly_results(
                    connection,
                    run_id,
                    anomaly_results or (),
                )
            if actor_user_id is not None:
                self._insert_audit_event(
                    connection,
                    actor_user_id=actor_user_id,
                    project_id=UUID(str(run["project_id"])),
                    action=_ANALYSIS_AUDIT_ACTIONS[next_status],
                    resource_type="analysis_run",
                    resource_id=run_id,
                    details_json=json.dumps(
                        {
                            "error_code": error_code,
                            "from_status": expected_status,
                            "status": next_status,
                        },
                        sort_keys=True,
                    ),
                )
        return self.get_analysis_run(run_id) or self._missing_record("analysis run")

    def replace_anomaly_results(
        self,
        connection: _DatabaseConnection,
        run_id: UUID,
        results: Iterable[dict[str, Any]],
    ) -> None:
        """Replace every anomaly row for a run inside the caller's transaction."""
        connection.execute(
            "DELETE FROM anomaly_results WHERE analysis_run_id = ?",
            (str(run_id),),
        )
        for item in results:
            context_json = item.get("context_json")
            if context_json is None:
                context_json = json.dumps(item.get("context") or {}, sort_keys=True)
            connection.execute(
                """
                INSERT INTO anomaly_results (
                    id, analysis_run_id, record_reference, anomaly_score, anomaly_level,
                    decision_threshold, context_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.get("id") or uuid4()),
                    str(run_id),
                    str(item["record_reference"]),
                    item.get("anomaly_score"),
                    item.get("anomaly_level"),
                    item.get("decision_threshold"),
                    str(context_json),
                ),
            )

    def get_analysis_run(self, run_id: UUID) -> DatabaseRow | None:
        return self._one(
            f"{_ANALYSIS_RUN_WITH_DATASET} WHERE r.id = ?",
            (str(run_id),),
        )

    def list_analysis_runs(self, project_id: UUID) -> list[DatabaseRow]:
        return self._all(
            f"{_ANALYSIS_RUN_WITH_DATASET} WHERE r.project_id = ? ORDER BY r.created_at DESC",
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
            self._insert_audit_event(
                connection,
                actor_user_id=actor_user_id,
                project_id=project_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details_json=details_json,
            )

    def _insert_audit_event(
        self,
        connection: _DatabaseConnection,
        *,
        actor_user_id: UUID | None,
        project_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        details_json: str,
    ) -> None:
        """Insert one audit event inside the caller's transaction."""
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

    def list_user_audit_events(self) -> list[DatabaseRow]:
        """List Administrator-visible user-resource events across all projects."""
        return self._all(
            """
            SELECT * FROM audit_events
            WHERE resource_type = 'user'
            ORDER BY created_at DESC
            """
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


def _resolve_preprocessing_bundle_id(
    connection: _DatabaseConnection,
    *,
    project_id: UUID,
    created_at: str,
    preprocessing_bundle: Mapping[str, Any] | None,
    preprocessing_bundle_id: UUID | None,
) -> str | None:
    if preprocessing_bundle is not None and preprocessing_bundle_id is not None:
        raise ValueError("Provide either a new preprocessing bundle or an existing bundle id.")
    if preprocessing_bundle_id is not None:
        row = connection.execute(
            "SELECT project_id FROM preprocessing_bundles WHERE id = ?",
            (str(preprocessing_bundle_id),),
        ).fetchone()
        if row is None or str(dict(row)["project_id"]) != str(project_id):
            raise ValueError("Preprocessing bundle was not found.")
        return str(preprocessing_bundle_id)
    if preprocessing_bundle is None:
        return None
    bundle_id = str(preprocessing_bundle.get("id") or uuid4())
    connection.execute(
        """
        INSERT INTO preprocessing_bundles (
            id, project_id, identifier, version, object_prefix, manifest_checksum,
            metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            bundle_id,
            str(project_id),
            str(preprocessing_bundle["identifier"]),
            str(preprocessing_bundle["version"]),
            str(preprocessing_bundle["object_prefix"]),
            str(preprocessing_bundle["manifest_checksum"]),
            str(preprocessing_bundle["metadata_json"]),
            created_at,
        ),
    )
    return bundle_id


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


def _normalized_checksum(storage_kind: str, checksum: str | None) -> str | None:
    """Reject object-kind pointers that are missing a checksum before insert."""
    if storage_kind not in _STORAGE_KINDS:
        raise DatasetPointerError(f"Unsupported storage kind {storage_kind!r}.")
    if checksum is None:
        normalized = None
    else:
        normalized = checksum.strip() or None
    if storage_kind == "object" and normalized is None:
        raise DatasetPointerError("Object-kind pointers require a non-empty checksum.")
    return normalized
