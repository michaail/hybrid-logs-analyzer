from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.api.bootstrap import bootstrap_administrator
from src.api.main import create_app
from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase, DatabaseIntegrityError

PASSWORD = "correct-horse-battery-staple"


@dataclass
class ApiFixture:
    client: TestClient
    workspace: Path


@pytest.fixture
def api(tmp_path: Path) -> Iterator[ApiFixture]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        jwt_secret="test-secret-not-for-production",
        trusted_workspace_root=workspace,
    )
    ApiDatabase(settings.database_url).apply_migrations()
    bootstrap_administrator(settings, "admin", PASSWORD)
    with TestClient(create_app(settings)) as client:
        yield ApiFixture(client=client, workspace=workspace)


def _login(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/auth/token", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _provision(client: TestClient, headers: dict[str, str], username: str) -> dict[str, str]:
    response = client.post(
        "/admin/users",
        headers=headers,
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_project(client: TestClient, headers: dict[str, str], name: str) -> dict[str, str]:
    response = client.post("/projects", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _grant_membership(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    user_id: str,
    role: str,
) -> None:
    response = client.post(
        f"/projects/{project_id}/members",
        headers=headers,
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 201, response.text


def _write_trusted_manifest(workspace: Path, *, dataset: str = "hdfs") -> str:
    checkpoint = workspace / "outputs" / dataset / "baseline" / "attribute_gae.pt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"trusted pipeline checkpoint reference only")
    metrics = checkpoint.with_name("metrics.json")
    metrics.write_text(json.dumps({"best_threshold": 0.147, "test_roc_auc": 0.9763}))
    manifest = workspace / "artifacts" / "runs" / "baseline.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "run_id": "baseline",
                "dataset": dataset,
                "artifacts": {
                    "checkpoint": str(checkpoint.relative_to(workspace)),
                    "metrics": str(metrics.relative_to(workspace)),
                },
                "metrics": {"best_threshold": 0.147, "test_roc_auc": 0.9763},
            }
        )
    )
    return str(manifest.relative_to(workspace))


def test_migrations_are_idempotent_and_database_is_healthy(tmp_path: Path) -> None:
    database = ApiDatabase(f"sqlite:///{tmp_path / 'api.db'}")

    database.apply_migrations()
    database.apply_migrations()

    assert database.healthcheck()


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
    publisher = _provision(client, administrator, "publisher")
    operator = _provision(client, administrator, "operator")
    other_operator = _provision(client, administrator, "other-operator")
    first_project = _create_project(client, administrator, "incident-a")
    second_project = _create_project(client, administrator, "incident-b")

    _grant_membership(client, administrator, first_project["id"], publisher["id"], "publisher")
    _grant_membership(client, administrator, first_project["id"], operator["id"], "operator")
    _grant_membership(client, administrator, second_project["id"], other_operator["id"], "operator")

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
            json={
                "model_identifier": "gae",
                "version": "v1",
                "pipeline_run_manifest": "artifacts/runs/missing.json",
                "external_evaluation_evidence": "run report",
            },
        ).status_code
        == 403
    )


def test_model_publication_and_safe_analysis_run_lifecycle(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    publisher = _provision(client, administrator, "publisher")
    operator = _provision(client, administrator, "operator")
    project = _create_project(client, administrator, "incident-a")
    _grant_membership(client, administrator, project["id"], publisher["id"], "publisher")
    _grant_membership(client, administrator, project["id"], operator["id"], "operator")
    manifest_reference = _write_trusted_manifest(api.workspace)

    publisher_headers = _login(client, "publisher")
    registration = client.post(
        f"/projects/{project['id']}/models",
        headers=publisher_headers,
        json={
            "model_identifier": "attribute-gae",
            "version": "2026.09",
            "pipeline_run_manifest": manifest_reference,
            "external_evaluation_evidence": "https://evidence.example/evaluation/baseline",
            "metadata": {"architecture": "AttributeAwareGAE"},
        },
    )
    assert registration.status_code == 201, registration.text
    model = registration.json()
    assert model["status"] == "eligible"
    assert model["artifact_reference"] == "outputs/hdfs/baseline/attribute_gae.pt"

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

    invalid_log = api.workspace / "data" / "invalid.log"
    invalid_log.write_text("not an HDFS record\n")
    rejected = client.post(
        f"/projects/{project['id']}/analysis-runs",
        headers=operator_headers,
        json={"model_version_id": model["id"], "log_reference": "data/invalid.log"},
    )
    assert rejected.status_code == 202, rejected.text
    assert rejected.json()["status"] == "rejected"

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


def test_registration_rejects_non_hdfs_or_outside_workspace_artifacts(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    publisher = _provision(client, administrator, "publisher")
    project = _create_project(client, administrator, "incident-a")
    _grant_membership(client, administrator, project["id"], publisher["id"], "publisher")
    publisher_headers = _login(client, "publisher")
    bgl_manifest = _write_trusted_manifest(api.workspace, dataset="bgl")

    rejected = client.post(
        f"/projects/{project['id']}/models",
        headers=publisher_headers,
        json={
            "model_identifier": "attribute-gae",
            "version": "bgl",
            "pipeline_run_manifest": bgl_manifest,
            "external_evaluation_evidence": "evidence",
        },
    )
    assert rejected.status_code == 422
    assert "HDFS" in rejected.json()["detail"]

    outside = client.post(
        f"/projects/{project['id']}/models",
        headers=publisher_headers,
        json={
            "model_identifier": "attribute-gae",
            "version": "outside",
            "pipeline_run_manifest": "../not-trusted.json",
            "external_evaluation_evidence": "evidence",
        },
    )
    assert outside.status_code == 422
    assert "trusted workspace" in outside.json()["detail"]
