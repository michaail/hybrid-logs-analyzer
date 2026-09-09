from __future__ import annotations

import json
import sqlite3
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.api.bootstrap import bootstrap_administrator
from src.api.main import create_app
from src.api.migrations import PACKAGE_ADMISSION_VERSION
from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase, DatabaseIntegrityError
from src.api.validation import ValidationError, admit_validated_package
from tests.test_model_package import _write_package

PASSWORD = "correct-horse-battery-staple"
REPO_ROOT = Path(__file__).resolve().parents[1]
FILES_ONLY_VALIDATOR = REPO_ROOT / "tests" / "support" / "files_only_validator.py"


@dataclass
class ApiFixture:
    client: TestClient
    workspace: Path
    settings: ApiSettings


def _api_settings(
    tmp_path: Path,
    workspace: Path,
    command: tuple[str, ...] | None = None,
) -> ApiSettings:
    return ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        jwt_secret="test-secret-not-for-production",
        trusted_workspace_root=workspace,
        code_root=REPO_ROOT,
        model_validator_command=command
        if command is not None
        else (sys.executable, str(FILES_ONLY_VALIDATOR)),
    )


@pytest.fixture
def api(tmp_path: Path) -> Iterator[ApiFixture]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = _api_settings(tmp_path, workspace)
    ApiDatabase(settings.database_url).apply_migrations()
    bootstrap_administrator(settings, "admin", PASSWORD)
    with TestClient(create_app(settings)) as client:
        yield ApiFixture(client=client, workspace=workspace, settings=settings)


def _login(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/auth/token", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str], name: str) -> dict[str, object]:
    response = client.post("/projects", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _provision_project_account(
    client: TestClient,
    headers: dict[str, str],
    username: str,
    project_id: str,
    role: str,
) -> dict[str, object]:
    response = client.post(
        "/admin/project-accounts",
        headers=headers,
        json={
            "username": username,
            "password": PASSWORD,
            "project_id": project_id,
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["membership"]["role"] == role
    assert payload["membership"]["project_id"] == project_id
    return payload["account"]


def _grant_membership(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    user_id: str,
    role: str,
) -> dict[str, object]:
    response = client.post(
        f"/projects/{project_id}/members",
        headers=headers,
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _stage_package(workspace: Path, *, name: str = "hdfs", **kwargs: Any) -> str:
    package = _write_package(workspace / "packages" / name, **kwargs)
    return str(package.relative_to(workspace).as_posix())


def _register(client: TestClient, headers: dict[str, str], project_id: object, package_reference: str):
    return client.post(
        f"/projects/{project_id}/models",
        headers=headers,
        json={"package_reference": package_reference},
    )


def test_admit_validated_package_rejects_artifact_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    reference = _stage_package(workspace)
    package = workspace / reference
    target = package / "model.pt"
    real = package / "real.pt"
    target.replace(real)
    target.symlink_to(real.name)
    with pytest.raises(ValidationError, match="regular file"):
        admit_validated_package(package, workspace)


def test_migrations_are_idempotent_and_database_is_healthy(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")

    database.apply_migrations()
    database.apply_migrations()

    assert database.healthcheck()
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")

    database.apply_migrations()
    database.apply_migrations()

    assert database.healthcheck()


def test_model_package_admission_migration_adds_columns(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    with database.session() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(model_versions)").fetchall()
        }
        applied = {
            str(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
    assert "package_reference" in columns
    assert "artifact_sha256" in columns
    assert "002_model_package_admission" not in applied
    assert PACKAGE_ADMISSION_VERSION in applied


def test_model_package_admission_migration_retries_after_partial_apply(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    with database.session() as connection:
        connection.execute(
            "DELETE FROM schema_migrations WHERE version = ?",
            (PACKAGE_ADMISSION_VERSION,),
        )
    database.apply_migrations()
    with database.session() as connection:
        applied = {
            str(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(model_versions)").fetchall()
        }
    assert "002_model_package_admission" not in applied
    assert PACKAGE_ADMISSION_VERSION in applied
    assert {"package_reference", "artifact_sha256"} <= columns


def test_fresh_schema_enforces_canonical_lowercase_active_users(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()

    with database.session() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
    assert {"id", "username", "password_hash", "is_administrator", "is_active", "created_at"} <= columns

    user = database.create_user(
        username="Mixed.Case_User",
        password_hash="not-a-real-hash",
        is_administrator=False,
    )
    assert user["username"] == "mixed.case_user"
    assert bool(user["is_active"])
    assert database.get_user_by_username("MIXED.CASE_USER") is not None

    with pytest.raises(DatabaseIntegrityError):
        database.create_user(
            username="MIXED.CASE_USER",
            password_hash="not-a-real-hash",
            is_administrator=False,
        )

    with database.session() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO users (id, username, password_hash, is_administrator, created_at)
                VALUES ('raw-id', 'RAWUPPER', 'x', 0, 'now')
                """
            )


def test_bootstrap_normalizes_username_and_audits_atomically(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        jwt_secret="test-secret-not-for-production",
        trusted_workspace_root=workspace,
    )
    ApiDatabase(settings.database_url).apply_migrations()

    user_id = bootstrap_administrator(settings, "ADMIN", PASSWORD)

    database = ApiDatabase(settings.database_url)
    user = database.get_user_by_id(user_id)
    assert user is not None
    assert user["username"] == "admin"
    assert bool(user["is_administrator"])
    assert bool(user["is_active"])
    assert database.get_user_by_username("AdMiN") is not None

    with pytest.raises(ValueError):
        bootstrap_administrator(settings, "Admin", PASSWORD)
    with pytest.raises(ValueError):
        bootstrap_administrator(settings, "not valid!", PASSWORD)

    with database.session() as connection:
        audit_rows = connection.execute(
            "SELECT action, details_json FROM audit_events WHERE resource_type = 'user'"
        ).fetchall()
    assert [dict(row)["action"] for row in audit_rows] == ["user.bootstrapped"]
    assert json.loads(dict(audit_rows[0])["details_json"])["username"] == "admin"


def _fail_audit_event(*args: object, **kwargs: object) -> None:
    raise RuntimeError("forced audit failure")


def test_provisioning_rolls_back_when_audit_insert_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    project = database.create_project("incident-a")
    actor = database.create_user(
        username="actor", password_hash="x", is_administrator=True
    )
    monkeypatch.setattr(ApiDatabase, "_insert_audit_event", _fail_audit_event)

    with pytest.raises(RuntimeError, match="forced audit failure"):
        database.provision_project_account(
            username="New.User",
            password_hash="x",
            project_id=UUID(project["id"]),
            role="operator",
            actor_user_id=UUID(actor["id"]),
        )

    assert database.get_user_by_username("new.user") is None
    assert database.list_memberships(UUID(project["id"])) == []


def test_membership_lifecycle_rolls_back_when_audit_insert_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    project = database.create_project("incident-a")
    actor = database.create_user(username="actor", password_hash="x", is_administrator=True)
    member = database.create_user(username="member", password_hash="x", is_administrator=False)
    project_id = UUID(project["id"])
    actor_id = UUID(actor["id"])
    member_id = UUID(member["id"])

    monkeypatch.setattr(ApiDatabase, "_insert_audit_event", _fail_audit_event)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        database.create_membership(
            project_id=project_id, user_id=member_id, role="operator", actor_user_id=actor_id
        )
    assert database.get_membership(project_id, member_id) is None

    monkeypatch.undo()
    database.create_membership(
        project_id=project_id, user_id=member_id, role="operator", actor_user_id=actor_id
    )

    monkeypatch.setattr(ApiDatabase, "_insert_audit_event", _fail_audit_event)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        database.update_membership_role(
            project_id=project_id, user_id=member_id, role="publisher", actor_user_id=actor_id
        )
    membership = database.get_membership(project_id, member_id)
    assert membership is not None
    assert membership["role"] == "operator"

    with pytest.raises(RuntimeError, match="forced audit failure"):
        database.revoke_membership(project_id=project_id, user_id=member_id, actor_user_id=actor_id)
    assert database.get_membership(project_id, member_id) is not None


def test_account_activation_rolls_back_when_audit_insert_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    actor = database.create_user(username="actor", password_hash="x", is_administrator=True)
    member = database.create_user(username="member", password_hash="x", is_administrator=False)
    actor_id = UUID(actor["id"])
    member_id = UUID(member["id"])

    monkeypatch.setattr(ApiDatabase, "_insert_audit_event", _fail_audit_event)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        database.set_user_active(user_id=member_id, is_active=False, actor_user_id=actor_id)
    member_after = database.get_user_by_id(member_id)
    assert member_after is not None
    assert bool(member_after["is_active"])


def test_project_creation_rolls_back_when_audit_insert_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")
    database.apply_migrations()
    actor = database.create_user(username="actor", password_hash="x", is_administrator=True)

    monkeypatch.setattr(ApiDatabase, "_insert_audit_event", _fail_audit_event)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        database.create_project_with_audit(name="incident-a", actor_user_id=UUID(actor["id"]))
    assert database.list_projects_for_user(UUID(actor["id"]), True) == []


def test_health_requires_a_reachable_database(api: ApiFixture) -> None:
    response = api.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_authentication_roles_and_project_isolation(api: ApiFixture) -> None:
    client = api.client
    assert client.get("/projects").status_code == 401

    administrator = _login(client, "admin")
    first_project = _create_project(client, administrator, "incident-a")
    second_project = _create_project(client, administrator, "incident-b")
    publisher = _provision_project_account(
        client, administrator, "publisher", str(first_project["id"]), "publisher"
    )
    operator = _provision_project_account(
        client, administrator, "operator", str(first_project["id"]), "operator"
    )
    _provision_project_account(
        client, administrator, "other-operator", str(second_project["id"]), "operator"
    )
    del publisher, operator

    operator_headers = _login(client, "operator")
    other_operator_headers = _login(client, "other-operator")
    assert client.get(f"/projects/{first_project['id']}/models", headers=operator_headers).status_code == 200
    assert (
        client.get(f"/projects/{first_project['id']}/models", headers=other_operator_headers).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{first_project['id']}/models",
            headers=operator_headers,
            json={"package_reference": "packages/missing"},
        ).status_code
        == 403
    )


def test_model_publication_and_safe_analysis_run_lifecycle(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    project = _create_project(client, administrator, "incident-a")
    _provision_project_account(client, administrator, "publisher", str(project["id"]), "publisher")
    _provision_project_account(client, administrator, "operator", str(project["id"]), "operator")
    package_reference = _stage_package(api.workspace)

    publisher_headers = _login(client, "publisher")
    registration = _register(client, publisher_headers, project["id"], package_reference)
    assert registration.status_code == 201, registration.text
    model = registration.json()
    assert model["status"] == "eligible"
    assert model["package_reference"] == package_reference
    assert model["artifact_reference"] == f"{package_reference}/model.pt"
    assert len(model["artifact_sha256"]) == 64
    assert "#" not in model["artifact_reference"]

    duplicate = _register(client, publisher_headers, project["id"], package_reference)
    assert duplicate.status_code == 409

    operator_headers = _login(client, "operator")
    assert (
        client.post(
            f"/projects/{project['id']}/models/{model['id']}/publish",
            headers=operator_headers,
        ).status_code
        == 403
    )
    publication = client.post(
        f"/projects/{project['id']}/models/{model['id']}/publish",
        headers=publisher_headers,
    )
    assert publication.status_code == 200, publication.text
    assert publication.json()["status"] == "published"

    valid_log = api.workspace / "data" / "stored-hdfs.log"
    valid_log.parent.mkdir()
    valid_log.write_text(
        "081109 203615 148 INFO dfs.DataNode$DataXceiver: "
        "Receiving block blk_1 src: /10.0.0.1:50010 dest: /10.0.0.2:50010\n"
    )
    analysis = client.post(
        f"/projects/{project['id']}/analysis-runs",
        headers=operator_headers,
        json={"model_version_id": model["id"], "log_reference": "data/stored-hdfs.log"},
    )
    assert analysis.status_code == 202, analysis.text
    assert analysis.json()["status"] == "not_supported"
    assert analysis.json()["error_code"] == "INFERENCE_CONTRACT_UNAVAILABLE"
    assert analysis.json()["dataset_id"]
    assert analysis.json()["storage_kind"] == "workspace"

    repeat = client.post(
        f"/projects/{project['id']}/analysis-runs",
        headers=operator_headers,
        json={"model_version_id": model["id"], "log_reference": "data/stored-hdfs.log"},
    )
    assert repeat.status_code == 202, repeat.text
    assert repeat.json()["dataset_id"] == analysis.json()["dataset_id"]

    invalid_log = api.workspace / "data" / "invalid.log"
    invalid_log.write_text("not an HDFS record\n")
    rejected = client.post(
        f"/projects/{project['id']}/analysis-runs",
        headers=operator_headers,
        json={"model_version_id": model["id"], "log_reference": "data/invalid.log"},
    )
    assert rejected.status_code == 202, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["dataset_id"] is None

    datasets = client.get(f"/projects/{project['id']}/datasets", headers=operator_headers)
    assert datasets.status_code == 200, datasets.text
    assert [item["object_reference"] for item in datasets.json()] == ["data/stored-hdfs.log"]
    dataset = client.get(
        f"/projects/{project['id']}/datasets/{analysis.json()['dataset_id']}",
        headers=operator_headers,
    )
    assert dataset.status_code == 200, dataset.text
    assert dataset.json()["storage_kind"] == "workspace"

    supported_results = client.get(
        f"/projects/{project['id']}/analysis-runs/{analysis.json()['id']}/results",
        headers=operator_headers,
    )
    assert supported_results.status_code == 200, supported_results.text
    assert supported_results.json()["summary"] == {
        "anomaly_count": 0,
        "normal_count": 0,
        "rejected_records": 0,
        "invalid_records": 0,
    }

    results = client.get(
        f"/projects/{project['id']}/analysis-runs/{rejected.json()['id']}/results",
        headers=operator_headers,
    )
    assert results.status_code == 200, results.text
    assert results.json()["summary"]["rejected_records"] == 1

    audit_events = client.get(f"/projects/{project['id']}/audit-events", headers=administrator)
    assert audit_events.status_code == 200
    assert {event["action"] for event in audit_events.json()} >= {
        "model.registered",
        "model.published",
        "analysis.not_supported",
        "analysis.rejected",
    }


def test_dataset_reads_are_isolated_and_omit_rejected_inputs(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    first_project = _create_project(client, administrator, "incident-a")
    second_project = _create_project(client, administrator, "incident-b")
    _provision_project_account(client, administrator, "publisher", str(first_project["id"]), "publisher")
    _provision_project_account(client, administrator, "operator", str(first_project["id"]), "operator")
    _provision_project_account(
        client, administrator, "other-operator", str(second_project["id"]), "operator"
    )
    package_reference = _stage_package(api.workspace)
    publisher_headers = _login(client, "publisher")
    registration = _register(client, publisher_headers, first_project["id"], package_reference)
    assert registration.status_code == 201, registration.text
    assert (
        client.post(
            f"/projects/{first_project['id']}/models/{registration.json()['id']}/publish",
            headers=publisher_headers,
        ).status_code
        == 200
    )
    valid_log = api.workspace / "data" / "stored-hdfs.log"
    valid_log.parent.mkdir()
    valid_log.write_text(
        "081109 203615 148 INFO dfs.DataNode$DataXceiver: "
        "Receiving block blk_1 src: /10.0.0.1:50010 dest: /10.0.0.2:50010\n"
    )
    operator_headers = _login(client, "operator")
    analysis = client.post(
        f"/projects/{first_project['id']}/analysis-runs",
        headers=operator_headers,
        json={
            "model_version_id": registration.json()["id"],
            "log_reference": "data/stored-hdfs.log",
        },
    )
    assert analysis.status_code == 202, analysis.text
    dataset_id = analysis.json()["dataset_id"]
    other_headers = _login(client, "other-operator")
    assert (
        client.get(f"/projects/{second_project['id']}/datasets", headers=other_headers).json()
        == []
    )
    assert (
        client.get(
            f"/projects/{second_project['id']}/datasets/{dataset_id}",
            headers=other_headers,
        ).status_code
        == 404
    )
    assert client.get(f"/projects/{first_project['id']}/datasets", headers=other_headers).status_code == 404


def test_registration_rejects_non_hdfs_or_outside_workspace_artifacts(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    project = _create_project(client, administrator, "incident-a")
    _provision_project_account(client, administrator, "publisher", str(project["id"]), "publisher")
    publisher_headers = _login(client, "publisher")
    package_reference = _stage_package(api.workspace)
    manifest_path = api.workspace / package_reference / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["source_compatibility"] = "bgl"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    rejected = _register(client, publisher_headers, project["id"], package_reference)
    assert rejected.status_code == 422
    detail = rejected.json()["detail"]
    assert detail["valid"] is False
    assert any("source_compatibility" in issue["path"] for issue in detail["issues"])

    outside = _register(client, publisher_headers, project["id"], "../not-trusted")
    assert outside.status_code == 422
    outside_detail = outside.json()["detail"]
    assert outside_detail["valid"] is False
    assert any("trusted workspace" in issue["reason"] for issue in outside_detail["issues"])


def test_administration_lifecycle_requires_administrator(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    project = _create_project(client, administrator, "incident-a")
    account = _provision_project_account(
        client, administrator, "operator", str(project["id"]), "operator"
    )
    operator_headers = _login(client, "operator")

    assert client.post("/admin/project-accounts").status_code == 401
    assert client.get("/admin/users").status_code == 401
    assert client.get("/admin/audit-events").status_code == 401
    assert client.post("/admin/users", json={"username": "x", "password": PASSWORD}).status_code == 405

    forbidden_bodies = [
        client.post(
            "/admin/project-accounts",
            headers=operator_headers,
            json={
                "username": "another",
                "password": PASSWORD,
                "project_id": project["id"],
                "role": "operator",
            },
        ),
        client.get("/admin/users", headers=operator_headers),
        client.patch(
            f"/admin/users/{account['id']}/activation",
            headers=operator_headers,
            json={"is_active": False},
        ),
        client.get("/admin/audit-events", headers=operator_headers),
        client.post(
            f"/projects/{project['id']}/members",
            headers=operator_headers,
            json={"user_id": account["id"], "role": "publisher"},
        ),
        client.patch(
            f"/projects/{project['id']}/members/{account['id']}",
            headers=operator_headers,
            json={"role": "publisher"},
        ),
        client.delete(
            f"/projects/{project['id']}/members/{account['id']}",
            headers=operator_headers,
        ),
    ]
    assert all(response.status_code == 403 for response in forbidden_bodies)


def test_project_account_lifecycle_isolation_and_audit(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    first_project = _create_project(client, administrator, "incident-a")
    second_project = _create_project(client, administrator, "incident-b")

    provisioned = client.post(
        "/admin/project-accounts",
        headers=administrator,
        json={
            "username": "Mixed.User",
            "password": PASSWORD,
            "project_id": first_project["id"],
            "role": "operator",
        },
    )
    assert provisioned.status_code == 201, provisioned.text
    account = provisioned.json()["account"]
    membership = provisioned.json()["membership"]
    assert account["username"] == "mixed.user"
    assert account["is_active"] is True
    assert membership["username"] == "mixed.user"
    assert membership["role"] == "operator"

    duplicate = client.post(
        "/admin/project-accounts",
        headers=administrator,
        json={
            "username": "MIXED.USER",
            "password": PASSWORD,
            "project_id": first_project["id"],
            "role": "publisher",
        },
    )
    assert duplicate.status_code == 409

    users = client.get("/admin/users", headers=administrator)
    assert users.status_code == 200
    usernames = {item["username"] for item in users.json()}
    assert {"admin", "mixed.user"} <= usernames
    assert all("password" not in item and "is_administrator" not in item for item in users.json())

    second_membership = _grant_membership(
        client, administrator, str(second_project["id"]), str(account["id"]), "publisher"
    )
    assert second_membership["role"] == "publisher"

    duplicate_membership = client.post(
        f"/projects/{first_project['id']}/members",
        headers=administrator,
        json={"user_id": account["id"], "role": "publisher"},
    )
    assert duplicate_membership.status_code == 409

    role_change = client.patch(
        f"/projects/{first_project['id']}/members/{account['id']}",
        headers=administrator,
        json={"role": "publisher"},
    )
    assert role_change.status_code == 200, role_change.text
    assert role_change.json()["role"] == "publisher"

    missing_role_change = client.patch(
        f"/projects/{first_project['id']}/members/{UUID(int=0)}",
        headers=administrator,
        json={"role": "operator"},
    )
    assert missing_role_change.status_code == 404

    publisher_headers = _login(client, "mixed.user")
    assert (
        client.get(f"/projects/{first_project['id']}/analysis-runs", headers=publisher_headers).status_code
        == 200
    )
    assert (
        client.get(f"/projects/{second_project['id']}/models", headers=publisher_headers).status_code
        == 200
    )

    issued_token = publisher_headers
    revoke = client.delete(
        f"/projects/{first_project['id']}/members/{account['id']}",
        headers=administrator,
    )
    assert revoke.status_code == 204
    assert (
        client.get(f"/projects/{first_project['id']}/models", headers=issued_token).status_code == 404
    )
    assert (
        client.get(f"/projects/{second_project['id']}/models", headers=issued_token).status_code == 200
    )

    missing_revoke = client.delete(
        f"/projects/{first_project['id']}/members/{account['id']}",
        headers=administrator,
    )
    assert missing_revoke.status_code == 404

    deactivation = client.patch(
        f"/admin/users/{account['id']}/activation",
        headers=administrator,
        json={"is_active": False},
    )
    assert deactivation.status_code == 200
    assert deactivation.json()["is_active"] is False
    assert client.get("/users/me", headers=issued_token).status_code == 401
    assert client.post("/auth/token", json={"username": "mixed.user", "password": PASSWORD}).status_code == 401

    admin_user = next(item for item in users.json() if item["username"] == "admin")
    assert (
        client.patch(
            f"/admin/users/{admin_user['id']}/activation",
            headers=administrator,
            json={"is_active": False},
        ).status_code
        == 409
    )

    reactivation = client.patch(
        f"/admin/users/{account['id']}/activation",
        headers=administrator,
        json={"is_active": True},
    )
    assert reactivation.status_code == 200
    assert reactivation.json()["is_active"] is True
    restored = _login(client, "MIXED.USER")
    assert client.get("/projects", headers=restored).status_code == 200

    project_audit = client.get(f"/projects/{first_project['id']}/audit-events", headers=administrator)
    assert project_audit.status_code == 200
    project_actions = {event["action"] for event in project_audit.json()}
    assert {
        "project.created",
        "project.membership_granted",
        "project.membership_role_changed",
        "project.membership_revoked",
    } <= project_actions

    second_audit = client.get(f"/projects/{second_project['id']}/audit-events", headers=administrator)
    assert {event["action"] for event in second_audit.json()} >= {
        "project.created",
        "project.membership_granted",
    }

    system_audit = client.get("/admin/audit-events", headers=administrator)
    assert system_audit.status_code == 200
    system_actions = {event["action"] for event in system_audit.json()}
    assert {
        "user.bootstrapped",
        "user.provisioned",
        "user.signed_in",
        "user.deactivated",
        "user.reactivated",
    } <= system_actions
    assert all(event["resource_type"] == "user" for event in system_audit.json())
    assert "project.membership_granted" not in system_actions


def test_openapi_exposes_administration_lifecycle_without_legacy_user_create(
    api: ApiFixture,
) -> None:
    schema = api.client.get("/openapi.json").json()
    paths = schema["paths"]

    assert "/admin/users" in paths
    assert "post" not in paths["/admin/users"]
    assert "get" in paths["/admin/users"]
    assert "/admin/project-accounts" in paths
    assert "post" in paths["/admin/project-accounts"]
    assert "/admin/users/{user_id}/activation" in paths
    assert "patch" in paths["/admin/users/{user_id}/activation"]
    assert "/admin/audit-events" in paths
    assert "get" in paths["/admin/audit-events"]
    assert "post" in paths["/projects/{project_id}/members"]
    assert "patch" in paths["/projects/{project_id}/members/{user_id}"]
    assert "delete" in paths["/projects/{project_id}/members/{user_id}"]

    assert "/register" not in paths
    assert "/signup" not in paths
    assert "/auth/register" not in paths

    dataset_list = "/projects/{project_id}/datasets"
    dataset_item = "/projects/{project_id}/datasets/{dataset_id}"
    assert "get" in paths[dataset_list]
    assert "post" not in paths[dataset_list]
    assert "get" in paths[dataset_item]
    assert "patch" not in paths.get(dataset_item, {})
    results_path = "/projects/{project_id}/analysis-runs/{analysis_run_id}/results"
    assert "get" in paths[results_path]
    assert "post" not in paths[results_path]
    assert "patch" not in paths[results_path]
    run_item = "/projects/{project_id}/analysis-runs/{analysis_run_id}"
    assert "patch" not in paths.get(run_item, {})
    status_schema = schema["components"]["schemas"]["AnalysisRunStatus"]
    assert set(status_schema["enum"]) == {
        "queued",
        "running",
        "completed",
        "failed",
        "rejected",
        "not_supported",
    }

    secured_operations = [
        paths["/admin/project-accounts"]["post"],
        paths["/admin/users"]["get"],
        paths["/admin/users/{user_id}/activation"]["patch"],
        paths["/admin/audit-events"]["get"],
        paths["/projects/{project_id}/members"]["post"],
        paths["/projects/{project_id}/members/{user_id}"]["patch"],
        paths["/projects/{project_id}/members/{user_id}"]["delete"],
    ]
    for operation in secured_operations:
        assert "HTTPBearer" in str(operation.get("security", schema.get("components", {})))

    registration_schema = schema["components"]["schemas"]["ModelRegistrationRequest"]
    assert "package_reference" in registration_schema["properties"]
    assert "pipeline_run_manifest" not in registration_schema["properties"]
    model_schema = schema["components"]["schemas"]["ModelVersionResponse"]
    assert "package_reference" in model_schema["properties"]
    assert "artifact_sha256" in model_schema["properties"]


def _publisher_client(api: ApiFixture) -> tuple[TestClient, dict[str, str], str]:
    administrator = _login(api.client, "admin")
    project = _create_project(api.client, administrator, "incident-a")
    _provision_project_account(
        api.client, administrator, "publisher", str(project["id"]), "publisher"
    )
    return api.client, _login(api.client, "publisher"), str(project["id"])


def test_registration_rejects_direct_zip_with_structured_422(api: ApiFixture) -> None:
    client, headers, project_id = _publisher_client(api)
    package = api.workspace / _stage_package(api.workspace, name="zip-src")
    archive = api.workspace / "packages" / "model.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for file in package.rglob("*"):
            if file.is_file():
                handle.write(file, file.relative_to(package).as_posix())
    rejected = _register(client, headers, project_id, "packages/model.zip")
    assert rejected.status_code == 422
    detail = rejected.json()["detail"]
    assert detail["valid"] is False
    assert any("directory" in issue["reason"].lower() for issue in detail["issues"])
    assert client.get(f"/projects/{project_id}/models", headers=headers).json() == []


def test_registration_collects_checksum_and_evidence_issues(api: ApiFixture) -> None:
    client, headers, project_id = _publisher_client(api)
    reference = _stage_package(api.workspace, name="broken", evidence={})
    manifest_path = api.workspace / reference / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"]["checksums"]["model.pt"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    rejected = _register(client, headers, project_id, reference)
    assert rejected.status_code == 422
    issues = rejected.json()["detail"]["issues"]
    paths = {issue["path"] for issue in issues}
    assert any("model.pt" in path for path in paths)
    assert any("evidence" in path for path in paths)
    assert client.get(f"/projects/{project_id}/models", headers=headers).json() == []


def test_registration_rejects_dummy_artifact_with_probe_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = _api_settings(
        tmp_path,
        workspace,
        command=(sys.executable, str(REPO_ROOT / "tests" / "support" / "rejecting_artifact_validator.py")),
    )
    ApiDatabase(settings.database_url).apply_migrations()
    bootstrap_administrator(settings, "admin", PASSWORD)
    with TestClient(create_app(settings)) as client:
        api = ApiFixture(client=client, workspace=workspace, settings=settings)
        _, headers, project_id = _publisher_client(api)
        reference = _stage_package(workspace)
        rejected = _register(client, headers, project_id, reference)
        assert rejected.status_code == 422, rejected.text
        assert any(
            "model.pt" in issue["path"] or "artifact" in issue["path"]
            for issue in rejected.json()["detail"]["issues"]
        )
        assert "torch" not in sys.modules
        assert client.get(f"/projects/{project_id}/models", headers=headers).json() == []


@pytest.mark.ml
def test_http_admission_uses_real_validator_probe(tmp_path: Path) -> None:
    import pickle

    import torch

    from src.modules.model_package import PackageArchitecture, expected_state_dict_spec
    from tests.test_model_package import TINY_ARCHITECTURE

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = _api_settings(
        tmp_path,
        workspace,
        command=(sys.executable, "-m", "src.model_validator"),
    )
    ApiDatabase(settings.database_url).apply_migrations()
    bootstrap_administrator(settings, "admin", PASSWORD)
    with TestClient(create_app(settings)) as client:
        api = ApiFixture(client=client, workspace=workspace, settings=settings)
        _, headers, project_id = _publisher_client(api)

        dummy_reference = _stage_package(workspace, name="dummy")
        dummy = _register(client, headers, project_id, dummy_reference)
        assert dummy.status_code == 422, dummy.text
        assert any("model.pt" in issue["path"] for issue in dummy.json()["detail"]["issues"])

        class Boom:
            def __reduce__(self) -> tuple[object, tuple[str]]:
                return exec, ("raise RuntimeError('pickle-executed')",)

        pickle_bytes = pickle.dumps(Boom())
        pickle_reference = _stage_package(workspace, name="pickle", artifact=pickle_bytes)
        pickled = _register(client, headers, project_id, pickle_reference)
        assert pickled.status_code == 422, pickled.text

        architecture = PackageArchitecture.model_validate(TINY_ARCHITECTURE)
        payload = {
            key: torch.zeros(spec.shape, dtype=torch.int64 if "int64" in spec.dtypes else torch.float32)
            for key, spec in expected_state_dict_spec(architecture).items()
        }
        artifact = tmp_path / "valid.pt"
        torch.save(payload, artifact)
        valid_reference = _stage_package(workspace, name="valid", artifact=artifact.read_bytes())
        created = _register(client, headers, project_id, valid_reference)
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "eligible"
        assert client.get(f"/projects/{project_id}/models", headers=headers).json()[0]["status"] == "eligible"


def test_unavailable_validator_does_not_insert_a_model(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = _api_settings(
        tmp_path,
        workspace,
        command=(sys.executable, "-c", "raise SystemExit(1)"),
    )
    ApiDatabase(settings.database_url).apply_migrations()
    bootstrap_administrator(settings, "admin", PASSWORD)
    with TestClient(create_app(settings)) as client:
        api = ApiFixture(client=client, workspace=workspace, settings=settings)
        _, headers, project_id = _publisher_client(api)
        reference = _stage_package(workspace)
        rejected = _register(client, headers, project_id, reference)
        assert rejected.status_code == 503
        assert client.get(f"/projects/{project_id}/models", headers=headers).json() == []


def test_malformed_validator_report_does_not_insert_a_model(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = _api_settings(
        tmp_path,
        workspace,
        command=(sys.executable, "-c", "print('not-json')"),
    )
    ApiDatabase(settings.database_url).apply_migrations()
    bootstrap_administrator(settings, "admin", PASSWORD)
    with TestClient(create_app(settings)) as client:
        api = ApiFixture(client=client, workspace=workspace, settings=settings)
        _, headers, project_id = _publisher_client(api)
        reference = _stage_package(workspace)
        rejected = _register(client, headers, project_id, reference)
        assert rejected.status_code == 503
        assert client.get(f"/projects/{project_id}/models", headers=headers).json() == []
