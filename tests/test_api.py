from __future__ import annotations

import io
import json
import sqlite3
import sys
import zipfile
from dataclasses import dataclass, replace
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
        object_store_root=(tmp_path / "objects").resolve(),
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


def _zip_package(package_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        for file in package_dir.rglob("*"):
            if file.is_file():
                handle.write(file, file.relative_to(package_dir).as_posix())
    return buffer.getvalue()


def _zip_staged(workspace: Path, **kwargs: Any) -> bytes:
    reference = _stage_package(workspace, **kwargs)
    return _zip_package(workspace / reference)


def _register(
    client: TestClient,
    headers: dict[str, str],
    project_id: object,
    archive: bytes,
    bundle: bytes | None = None,
):
    files = {"package": ("package.zip", archive, "application/zip")}
    if bundle is not None:
        files["preprocessing_bundle"] = ("bundle.zip", bundle, "application/zip")
    return client.post(
        f"/projects/{project_id}/models",
        headers=headers,
        files=files,
    )


def _v2_zips(workspace: Path) -> tuple[bytes, bytes]:
    from tests.test_inference_bundle import _v2_package, _write_bundle

    staging = workspace / "v2-release"
    bundle_dir = _write_bundle(staging)
    digest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))["digest"]
    package_dir = _v2_package(staging, digest)
    return _zip_package(package_dir), _zip_package(bundle_dir)


VALID_HDFS_LOG = (
    "081109 203615 148 INFO dfs.DataNode$DataXceiver: "
    "Receiving block blk_1 src: /10.0.0.1:50010 dest: /10.0.0.2:50010\n"
).encode("utf-8")


def _upload_log(
    client: TestClient,
    headers: dict[str, str],
    project_id: object,
    content: bytes = VALID_HDFS_LOG,
    filename: str = "hdfs.log",
):
    return client.post(
        f"/projects/{project_id}/datasets",
        headers=headers,
        files={"log": (filename, content, "text/plain")},
    )


def _object_files(api: ApiFixture) -> set[str]:
    return {
        path.relative_to(api.settings.object_store_root).as_posix()
        for path in api.settings.object_store_root.rglob("*")
        if path.is_file()
    }


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
    publisher_headers = _login(client, "publisher")
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
            files={"package": ("package.zip", _zip_staged(api.workspace), "application/zip")},
        ).status_code
        == 403
    )
    listed_as_operator = client.get(
        f"/projects/{first_project['id']}/models", headers=operator_headers
    )
    listed_as_publisher = client.get(
        f"/projects/{first_project['id']}/models", headers=publisher_headers
    )
    assert listed_as_operator.status_code == 200
    assert listed_as_operator.json() == []
    assert listed_as_publisher.status_code == 200
    assert listed_as_publisher.json() == []


def test_cross_project_member_routes_return_404(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    project_a = _create_project(client, administrator, "incident-a")
    project_b = _create_project(client, administrator, "incident-b")
    _provision_project_account(
        client, administrator, "publisher-a", str(project_a["id"]), "publisher"
    )
    _provision_project_account(
        client, administrator, "operator-a", str(project_a["id"]), "operator"
    )
    _provision_project_account(
        client, administrator, "publisher-b", str(project_b["id"]), "publisher"
    )
    _provision_project_account(
        client, administrator, "operator-b", str(project_b["id"]), "operator"
    )
    publisher_a = _login(client, "publisher-a")
    operator_a = _login(client, "operator-a")
    publisher_b = _login(client, "publisher-b")
    operator_b = _login(client, "operator-b")
    package_zip, bundle_zip = _v2_zips(api.workspace)

    assert (
        client.post(
            f"/projects/{project_a['id']}/models",
            files={"package": ("package.zip", package_zip, "application/zip")},
        ).status_code
        == 401
    )

    registration = _register(client, publisher_a, project_a["id"], package_zip, bundle_zip)
    assert registration.status_code == 201, registration.text
    model = registration.json()
    model_id = model["id"]
    assert model["status"] == "eligible"

    assert (
        client.get(
            f"/projects/{project_a['id']}/models/{model_id}",
            headers=operator_b,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/projects/{project_b['id']}/models/{model_id}",
            headers=operator_b,
        ).status_code
        == 404
    )

    foreign_register = _register(client, publisher_b, project_a["id"], package_zip, bundle_zip)
    assert foreign_register.status_code == 404
    listed_a = client.get(f"/projects/{project_a['id']}/models", headers=publisher_a)
    assert listed_a.status_code == 200
    assert [item["id"] for item in listed_a.json()] == [model_id]

    foreign_publish = client.post(
        f"/projects/{project_a['id']}/models/{model_id}/publish",
        headers=publisher_b,
    )
    assert foreign_publish.status_code == 404
    still_eligible = client.get(
        f"/projects/{project_a['id']}/models/{model_id}",
        headers=publisher_a,
    )
    assert still_eligible.status_code == 200
    assert still_eligible.json()["status"] == "eligible"

    publication = client.post(
        f"/projects/{project_a['id']}/models/{model_id}/publish",
        headers=publisher_a,
    )
    assert publication.status_code == 200, publication.text

    assert (
        client.post(
            f"/projects/{project_a['id']}/datasets",
            files={"log": ("hdfs.log", VALID_HDFS_LOG, "text/plain")},
        ).status_code
        == 401
    )
    uploaded = _upload_log(client, operator_a, project_a["id"])
    assert uploaded.status_code == 201, uploaded.text
    dataset_id = uploaded.json()["id"]
    analysis = client.post(
        f"/projects/{project_a['id']}/analysis-runs",
        headers=operator_a,
        json={"model_version_id": model_id, "dataset_id": dataset_id},
    )
    assert analysis.status_code == 202, analysis.text
    run_id = analysis.json()["id"]

    assert (
        client.get(
            f"/projects/{project_a['id']}/analysis-runs",
            headers=operator_b,
        ).status_code
        == 404
    )
    own_runs = client.get(
        f"/projects/{project_b['id']}/analysis-runs",
        headers=operator_b,
    )
    assert own_runs.status_code == 200
    assert own_runs.json() == []

    assert (
        client.post(
            f"/projects/{project_a['id']}/analysis-runs",
            headers=operator_b,
            json={"model_version_id": model_id, "dataset_id": dataset_id},
        ).status_code
        == 404
    )
    foreign_model = client.post(
        f"/projects/{project_b['id']}/analysis-runs",
        headers=operator_b,
        json={"model_version_id": model_id, "dataset_id": dataset_id},
    )
    assert foreign_model.status_code == 404
    uploaded_b = _upload_log(client, operator_b, project_b["id"])
    assert uploaded_b.status_code == 201, uploaded_b.text
    foreign_dataset = client.post(
        f"/projects/{project_a['id']}/analysis-runs",
        headers=operator_a,
        json={"model_version_id": model_id, "dataset_id": uploaded_b.json()["id"]},
    )
    assert foreign_dataset.status_code == 404
    missing_dataset = client.post(
        f"/projects/{project_a['id']}/analysis-runs",
        headers=operator_a,
        json={"model_version_id": model_id, "dataset_id": str(UUID("44444444-4444-4444-8444-444444444444"))},
    )
    assert missing_dataset.status_code == 404
    assert (
        client.get(
            f"/projects/{project_b['id']}/analysis-runs",
            headers=operator_b,
        ).json()
        == []
    )

    assert (
        client.get(
            f"/projects/{project_a['id']}/analysis-runs/{run_id}",
            headers=operator_b,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/projects/{project_a['id']}/analysis-runs/{run_id}/results",
            headers=operator_b,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/projects/{project_b['id']}/analysis-runs/{run_id}",
            headers=operator_b,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/projects/{project_b['id']}/analysis-runs/{run_id}/results",
            headers=operator_b,
        ).status_code
        == 404
    )


def test_model_publication_and_safe_analysis_run_lifecycle(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    project = _create_project(client, administrator, "incident-a")
    _provision_project_account(client, administrator, "publisher", str(project["id"]), "publisher")
    _provision_project_account(client, administrator, "operator", str(project["id"]), "operator")
    archive = _zip_staged(api.workspace)
    publisher_headers = _login(client, "publisher")
    registration = _register(client, publisher_headers, project["id"], archive)
    assert registration.status_code == 201, registration.text
    model = registration.json()
    assert model["status"] == "eligible"
    assert model["inference_ready"] is False
    assert model["preprocessing_bundle"] is None
    assert model["storage_kind"] == "object"
    assert model["checksum"] == model["artifact_sha256"]
    assert model["package_reference"] == (
        f"projects/{project['id']}/models/{model['id']}/{model['version']}"
    )
    assert model["artifact_reference"] == f"{model['package_reference']}/model.pt"
    assert len(model["artifact_sha256"]) == 64
    assert "#" not in model["artifact_reference"]

    duplicate = _register(client, publisher_headers, project["id"], archive)
    assert duplicate.status_code == 409
    stored_object_files = {
        path.relative_to(api.settings.object_store_root).as_posix()
        for path in api.settings.object_store_root.rglob("*")
        if path.is_file()
    }
    assert stored_object_files == {
        f"{model['package_reference']}/manifest.json",
        f"{model['package_reference']}/model.pt",
        f"{model['package_reference']}/evidence.json",
    }

    operator_headers = _login(client, "operator")
    assert (
        client.post(
            f"/projects/{project['id']}/models/{model['id']}/publish",
            headers=operator_headers,
        ).status_code
        == 403
    )
    unpublished = client.get(
        f"/projects/{project['id']}/models/{model['id']}",
        headers=publisher_headers,
    )
    assert unpublished.status_code == 200
    assert unpublished.json()["status"] == "eligible"
    assert unpublished.json()["published_at"] is None
    publication = client.post(
        f"/projects/{project['id']}/models/{model['id']}/publish",
        headers=publisher_headers,
    )
    assert publication.status_code == 200, publication.text
    assert publication.json()["status"] == "published"

    publisher_upload = _upload_log(client, publisher_headers, project["id"])
    assert publisher_upload.status_code == 201, publisher_upload.text
    uploaded = _upload_log(client, operator_headers, project["id"], filename="HDFS_2k.log")
    assert uploaded.status_code == 201, uploaded.text
    dataset = uploaded.json()
    assert dataset["storage_kind"] == "object"
    assert dataset["checksum"]
    assert dataset["object_reference"].endswith("/HDFS_2k.log")
    duplicate_bytes = _upload_log(client, operator_headers, project["id"], filename="HDFS_2k.log")
    assert duplicate_bytes.status_code == 201, duplicate_bytes.text
    assert duplicate_bytes.json()["id"] != dataset["id"]
    assert duplicate_bytes.json()["checksum"] == dataset["checksum"]

    analysis = client.post(
        f"/projects/{project['id']}/analysis-runs",
        headers=operator_headers,
        json={"model_version_id": model["id"], "dataset_id": dataset["id"]},
    )
    assert analysis.status_code == 409, analysis.text
    assert analysis.json()["detail"] == "Published model is not inference-ready."

    objects_before_invalid = _object_files(api)
    rejected = _upload_log(client, operator_headers, project["id"], b"not an HDFS record\n")
    assert rejected.status_code == 422, rejected.text
    detail = rejected.json()["detail"]
    assert detail["valid"] is False
    assert any(issue["reason"] for issue in detail["issues"])
    datasets = client.get(f"/projects/{project['id']}/datasets", headers=operator_headers)
    assert datasets.status_code == 200, datasets.text
    assert {item["id"] for item in datasets.json()} == {
        publisher_upload.json()["id"],
        dataset["id"],
        duplicate_bytes.json()["id"],
    }
    assert _object_files(api) == objects_before_invalid
    listed_runs = client.get(f"/projects/{project['id']}/analysis-runs", headers=operator_headers)
    assert listed_runs.status_code == 200
    assert listed_runs.json() == []

    fetched = client.get(
        f"/projects/{project['id']}/datasets/{dataset['id']}",
        headers=operator_headers,
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["storage_kind"] == "object"

    audit_events = client.get(f"/projects/{project['id']}/audit-events", headers=administrator)
    assert audit_events.status_code == 200
    assert {event["action"] for event in audit_events.json()} >= {
        "model.registered",
        "model.published",
        "dataset.registered",
    }


def test_dataset_reads_are_isolated_and_omit_rejected_inputs(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    first_project = _create_project(client, administrator, "incident-a")
    second_project = _create_project(client, administrator, "incident-b")
    _provision_project_account(client, administrator, "operator", str(first_project["id"]), "operator")
    _provision_project_account(
        client, administrator, "other-operator", str(second_project["id"]), "operator"
    )
    operator_headers = _login(client, "operator")
    uploaded = _upload_log(client, operator_headers, first_project["id"])
    assert uploaded.status_code == 201, uploaded.text
    dataset_id = uploaded.json()["id"]
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


def test_invalid_log_upload_persists_nothing(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    project = _create_project(client, administrator, "incident-a")
    _provision_project_account(client, administrator, "operator", str(project["id"]), "operator")
    operator_headers = _login(client, "operator")
    rejected = _upload_log(client, operator_headers, project["id"], b"not an HDFS record\n")
    assert rejected.status_code == 422, rejected.text
    detail = rejected.json()["detail"]
    assert detail["valid"] is False
    assert detail["issues"][0]["reason"]
    assert client.get(f"/projects/{project['id']}/datasets", headers=operator_headers).json() == []
    assert _object_files(api) == set()
    assert client.get(f"/projects/{project['id']}/analysis-runs", headers=operator_headers).json() == []


def test_registration_rejects_non_hdfs_or_outside_workspace_artifacts(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    project = _create_project(client, administrator, "incident-a")
    _provision_project_account(client, administrator, "publisher", str(project["id"]), "publisher")
    publisher_headers = _login(client, "publisher")
    package_dir = api.workspace / _stage_package(api.workspace)
    manifest_path = package_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["source_compatibility"] = "bgl"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    rejected = _register(client, publisher_headers, project["id"], _zip_package(package_dir))
    assert rejected.status_code == 422
    detail = rejected.json()["detail"]
    assert detail["valid"] is False
    assert any("source_compatibility" in issue["path"] for issue in detail["issues"])
    json_rejected = client.post(
        f"/projects/{project['id']}/models",
        headers=publisher_headers,
        json={"package_reference": "packages/hdfs"},
    )
    assert json_rejected.status_code == 422
    assert client.get(f"/projects/{project['id']}/models", headers=publisher_headers).json() == []


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


def _openapi_schema_properties(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    if "properties" in node:
        return node["properties"]
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        current: Any = schema
        for part in ref[2:].split("/"):
            current = current[part]
        return _openapi_schema_properties(schema, current)
    for item in node.get("allOf", []):
        try:
            return _openapi_schema_properties(schema, item)
        except (KeyError, TypeError):
            continue
    raise AssertionError(f"OpenAPI schema node has no properties: {sorted(node)}")


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
    assert "post" in paths[dataset_list]
    dataset_post = paths[dataset_list]["post"]
    assert "multipart/form-data" in dataset_post["requestBody"]["content"]
    create_schema = schema["components"]["schemas"]["AnalysisRunCreate"]
    assert "dataset_id" in create_schema["properties"]
    assert "log_reference" not in create_schema["properties"]
    assert "get" in paths[dataset_item]
    assert "patch" not in paths.get(dataset_item, {})
    results_path = "/projects/{project_id}/analysis-runs/{analysis_run_id}/results"
    assert "get" in paths[results_path]
    assert "post" not in paths[results_path]
    assert "patch" not in paths[results_path]
    results_get = paths[results_path]["get"]
    result_params = {item["name"] for item in results_get.get("parameters", []) if item.get("in") == "query"}
    assert {"limit", "sort", "block_id_prefix", "min_score", "cursor"} <= result_params
    result_schema = schema["components"]["schemas"]["AnalysisResultsResponse"]
    assert result_schema.get("additionalProperties") is False
    assert {
        "run",
        "summary",
        "trace",
        "anomalies",
        "query",
    } <= set(result_schema.get("required", []))
    assert "next_cursor" in result_schema["properties"]
    anomaly_schema = schema["components"]["schemas"]["HdfsAnomalyResult"]
    assert {"block_id", "record_reference", "context"} <= set(anomaly_schema["properties"])
    summary_schema = schema["components"]["schemas"]["AnalysisResultSummary"]
    assert {
        "anomaly_count",
        "normal_count",
        "rejected_records",
        "invalid_records",
    } <= set(summary_schema["properties"])
    trace_schema = schema["components"]["schemas"]["AnalysisResultTrace"]
    assert {
        "model_identifier",
        "version",
        "model_version_id",
        "pipeline_run_id",
        "dataset_checksum",
        "artifact_checksum",
        "preprocessing_bundle",
    } <= set(trace_schema["properties"])
    run_item = "/projects/{project_id}/analysis-runs/{analysis_run_id}"
    assert "patch" not in paths.get(run_item, {})
    assert "post" not in paths.get(run_item, {})
    assert not any("/internal/" in path for path in paths)
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

    model_schema = schema["components"]["schemas"]["ModelVersionResponse"]
    assert "package_reference" in model_schema["properties"]
    assert "artifact_sha256" in model_schema["properties"]
    assert "inference_ready" in model_schema["properties"]
    assert "preprocessing_bundle" in model_schema["properties"]
    register_op = paths["/projects/{project_id}/models"]["post"]
    assert "multipart/form-data" in register_op["requestBody"]["content"]
    assert "application/json" not in register_op["requestBody"]["content"]
    multipart_schema = register_op["requestBody"]["content"]["multipart/form-data"]["schema"]
    multipart = _openapi_schema_properties(schema, multipart_schema)
    assert "package" in multipart
    assert "preprocessing_bundle" in multipart
    assert "ModelRegistrationRequest" not in schema["components"]["schemas"]


def _publisher_client(api: ApiFixture) -> tuple[TestClient, dict[str, str], str]:
    administrator = _login(api.client, "admin")
    project = _create_project(api.client, administrator, "incident-a")
    _provision_project_account(
        api.client, administrator, "publisher", str(project["id"]), "publisher"
    )
    return api.client, _login(api.client, "publisher"), str(project["id"])


def test_registration_accepts_zip_and_persists_declared_files_only(api: ApiFixture) -> None:
    client, headers, project_id = _publisher_client(api)
    archive = _zip_staged(api.workspace, extra_files={"leftover.bin": b"ignore-me"})
    created = _register(client, headers, project_id, archive)
    assert created.status_code == 201, created.text
    model = created.json()
    assert model["status"] == "eligible"
    assert model["storage_kind"] == "object"
    stored = api.settings.object_store_root.joinpath(*model["package_reference"].split("/"))
    names = {path.name for path in stored.rglob("*") if path.is_file()}
    assert names == {"manifest.json", "model.pt", "evidence.json"}
    assert not (stored / "leftover.bin").exists()
    listed = client.get(f"/projects/{project_id}/models", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_registration_rejects_ineligible_zip_without_inserting(api: ApiFixture) -> None:
    client, headers, project_id = _publisher_client(api)
    archive = _zip_staged(api.workspace, name="broken", evidence={})
    rejected = _register(client, headers, project_id, archive)
    assert rejected.status_code == 422
    detail = rejected.json()["detail"]
    assert detail["valid"] is False
    assert any("evidence" in issue["path"] for issue in detail["issues"])
    assert client.get(f"/projects/{project_id}/models", headers=headers).json() == []
    object_files = [path for path in api.settings.object_store_root.rglob("*") if path.is_file()]
    assert object_files == []


def test_registration_collects_checksum_and_evidence_issues(api: ApiFixture) -> None:
    client, headers, project_id = _publisher_client(api)
    reference = _stage_package(api.workspace, name="broken", evidence={})
    manifest_path = api.workspace / reference / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"]["checksums"]["model.pt"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    rejected = _register(client, headers, project_id, _zip_package(api.workspace / reference))
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
    imported_before = set(sys.modules)
    with TestClient(create_app(settings)) as client:
        api = ApiFixture(client=client, workspace=workspace, settings=settings)
        _, headers, project_id = _publisher_client(api)
        rejected = _register(client, headers, project_id, _zip_staged(workspace))
        assert rejected.status_code == 422, rejected.text
        assert any(
            "model.pt" in issue["path"] or "artifact" in issue["path"]
            for issue in rejected.json()["detail"]["issues"]
        )
        assert "torch" not in (set(sys.modules) - imported_before)
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

        dummy = _register(client, headers, project_id, _zip_staged(workspace, name="dummy"))
        assert dummy.status_code == 422, dummy.text
        assert any("model.pt" in issue["path"] for issue in dummy.json()["detail"]["issues"])

        class Boom:
            def __reduce__(self) -> tuple[object, tuple[str]]:
                return exec, ("raise RuntimeError('pickle-executed')",)

        pickle_bytes = pickle.dumps(Boom())
        pickled = _register(
            client, headers, project_id, _zip_staged(workspace, name="pickle", artifact=pickle_bytes)
        )
        assert pickled.status_code == 422, pickled.text

        architecture = PackageArchitecture.model_validate(TINY_ARCHITECTURE)
        payload = {
            key: torch.zeros(spec.shape, dtype=torch.int64 if "int64" in spec.dtypes else torch.float32)
            for key, spec in expected_state_dict_spec(architecture).items()
        }
        artifact = tmp_path / "valid.pt"
        torch.save(payload, artifact)
        created = _register(
            client,
            headers,
            project_id,
            _zip_staged(workspace, name="valid", artifact=artifact.read_bytes()),
        )
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "eligible"
        assert created.json()["storage_kind"] == "object"
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
        rejected = _register(client, headers, project_id, _zip_staged(workspace))
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
        rejected = _register(client, headers, project_id, _zip_staged(workspace))
        assert rejected.status_code == 503
        assert client.get(f"/projects/{project_id}/models", headers=headers).json() == []


def test_unpublished_eligible_model_cannot_start_analysis(api: ApiFixture) -> None:
    client = api.client
    administrator = _login(client, "admin")
    project = _create_project(client, administrator, "incident-a")
    _provision_project_account(client, administrator, "publisher", str(project["id"]), "publisher")
    _provision_project_account(client, administrator, "operator", str(project["id"]), "operator")
    publisher_headers = _login(client, "publisher")
    registration = _register(client, publisher_headers, project["id"], _zip_staged(api.workspace))
    assert registration.status_code == 201, registration.text
    assert registration.json()["status"] == "eligible"
    operator_headers = _login(client, "operator")
    uploaded = _upload_log(client, operator_headers, project["id"])
    assert uploaded.status_code == 201, uploaded.text
    analysis = client.post(
        f"/projects/{project['id']}/analysis-runs",
        headers=operator_headers,
        json={
            "model_version_id": registration.json()["id"],
            "dataset_id": uploaded.json()["id"],
        },
    )
    assert analysis.status_code == 409
    assert analysis.json()["detail"] == "Only published model versions can start analysis."
    listed = client.get(f"/projects/{project['id']}/analysis-runs", headers=operator_headers)
    assert listed.status_code == 200
    assert listed.json() == []


def test_v2_registration_persists_separate_prefixes_and_is_inference_ready(api: ApiFixture) -> None:
    client, headers, project_id = _publisher_client(api)
    package_zip, bundle_zip = _v2_zips(api.workspace)
    created = _register(client, headers, project_id, package_zip, bundle_zip)
    assert created.status_code == 201, created.text
    model = created.json()
    assert model["inference_ready"] is True
    assert model["preprocessing_bundle"]["identifier"] == "attribute-gae-preprocessing"
    assert model["preprocessing_bundle"]["version"] == "v2"
    stored = {
        path.relative_to(api.settings.object_store_root).as_posix()
        for path in api.settings.object_store_root.rglob("*")
        if path.is_file()
    }
    assert f"{model['package_reference']}/manifest.json" in stored
    assert f"{model['package_reference']}/model.pt" in stored
    bundle_prefix = next(
        path.rsplit("/", 1)[0]
        for path in stored
        if "/preprocessing-bundles/" in path and path.endswith("/manifest.json")
    )
    assert bundle_prefix.startswith(f"projects/{project_id}/preprocessing-bundles/")
    assert f"{bundle_prefix}/drain.ini" in stored
    assert f"{bundle_prefix}/drain_parser.bin" in stored
    assert f"{bundle_prefix}/embeddings.npz" in stored

    duplicate = _register(client, headers, project_id, package_zip, bundle_zip)
    assert duplicate.status_code == 409
    assert stored == {
        path.relative_to(api.settings.object_store_root).as_posix()
        for path in api.settings.object_store_root.rglob("*")
        if path.is_file()
    }


def test_v2_registration_rejects_missing_or_v1_bundle(api: ApiFixture) -> None:
    client, headers, project_id = _publisher_client(api)
    package_zip, bundle_zip = _v2_zips(api.workspace)
    missing = _register(client, headers, project_id, package_zip)
    assert missing.status_code == 422
    assert any("preprocessing_bundle" in issue["path"] for issue in missing.json()["detail"]["issues"])
    v1_with_bundle = _register(client, headers, project_id, _zip_staged(api.workspace), bundle_zip)
    assert v1_with_bundle.status_code == 422
    assert any("preprocessing_bundle" in issue["path"] for issue in v1_with_bundle.json()["detail"]["issues"])
    assert client.get(f"/projects/{project_id}/models", headers=headers).json() == []
    assert [path for path in api.settings.object_store_root.rglob("*") if path.is_file()] == []


def test_published_v2_model_queues_and_schedules_dispatch(
    api: ApiFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatched: list[UUID] = []

    def fake_dispatch(run_id: UUID, settings: ApiSettings, **kwargs: object) -> None:
        del settings, kwargs
        dispatched.append(run_id)

    monkeypatch.setattr("src.api.main.dispatch_analysis_run", fake_dispatch)
    client = api.client
    administrator = _login(client, "admin")
    project = _create_project(client, administrator, "incident-a")
    _provision_project_account(client, administrator, "publisher", str(project["id"]), "publisher")
    _provision_project_account(client, administrator, "operator", str(project["id"]), "operator")
    publisher_headers = _login(client, "publisher")
    operator_headers = _login(client, "operator")
    package_zip, bundle_zip = _v2_zips(api.workspace)
    registration = _register(client, publisher_headers, project["id"], package_zip, bundle_zip)
    assert registration.status_code == 201, registration.text
    publication = client.post(
        f"/projects/{project['id']}/models/{registration.json()['id']}/publish",
        headers=publisher_headers,
    )
    assert publication.status_code == 200, publication.text
    uploaded = _upload_log(client, operator_headers, project["id"])
    analysis = client.post(
        f"/projects/{project['id']}/analysis-runs",
        headers=operator_headers,
        json={
            "model_version_id": registration.json()["id"],
            "dataset_id": uploaded.json()["id"],
        },
    )
    assert analysis.status_code == 202, analysis.text
    payload = analysis.json()
    assert payload["status"] == "queued"
    assert payload["error_code"] is None
    assert payload["completed_at"] is None
    assert payload["validation_report"] is None
    assert dispatched == [UUID(payload["id"])]
    results = client.get(
        f"/projects/{project['id']}/analysis-runs/{payload['id']}/results",
        headers=operator_headers,
    )
    assert results.status_code == 200
    assert results.json()["run"]["status"] == "queued"
    assert results.json()["summary"] == {
        "anomaly_count": 0,
        "normal_count": 0,
        "rejected_records": 0,
        "invalid_records": 0,
    }


def test_exhausted_dispatch_preserves_queued_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def fail_post(url: str, headers: object, connect: float, read: float) -> int:
        del url, headers, connect, read
        calls["n"] += 1
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr("src.api.inference_dispatch.post_inference_execute", fail_post)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = replace(
        _api_settings(tmp_path, workspace),
        inference_service_url="http://inference.test",
        inference_internal_token="dispatch-test-token",
        inference_retry_attempts=2,
        inference_retry_backoff_seconds=0.0,
    )
    ApiDatabase(settings.database_url).apply_migrations()
    bootstrap_administrator(settings, "admin", PASSWORD)
    with TestClient(create_app(settings)) as client:
        api = ApiFixture(client=client, workspace=workspace, settings=settings)
        _, publisher_headers, project_id = _publisher_client(api)
        _provision_project_account(client, _login(client, "admin"), "operator", project_id, "operator")
        operator_headers = _login(client, "operator")
        package_zip, bundle_zip = _v2_zips(workspace)
        registration = _register(client, publisher_headers, project_id, package_zip, bundle_zip)
        assert registration.status_code == 201, registration.text
        publication = client.post(
            f"/projects/{project_id}/models/{registration.json()['id']}/publish",
            headers=publisher_headers,
        )
        assert publication.status_code == 200, publication.text
        uploaded = _upload_log(client, operator_headers, project_id)
        analysis = client.post(
            f"/projects/{project_id}/analysis-runs",
            headers=operator_headers,
            json={
                "model_version_id": registration.json()["id"],
                "dataset_id": uploaded.json()["id"],
            },
        )
        assert analysis.status_code == 202, analysis.text
        assert analysis.json()["status"] == "queued"
        fetched = client.get(
            f"/projects/{project_id}/analysis-runs/{analysis.json()['id']}",
            headers=operator_headers,
        )
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "queued"
        assert fetched.json()["error_code"] is None
        assert fetched.json()["completed_at"] is None
        assert calls["n"] == 2


def _queued_v2_run(
    api: ApiFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, dict[str, str], dict[str, Any], dict[str, Any], str]:
    monkeypatch.setattr("src.api.main.dispatch_analysis_run", lambda *args, **kwargs: None)
    client = api.client
    administrator = _login(client, "admin")
    project = _create_project(client, administrator, "incident-results")
    operator = _provision_project_account(
        client, administrator, "operator-results", str(project["id"]), "operator"
    )
    _provision_project_account(
        client, administrator, "publisher-results", str(project["id"]), "publisher"
    )
    publisher_headers = _login(client, "publisher-results")
    operator_headers = _login(client, "operator-results")
    package_zip, bundle_zip = _v2_zips(api.workspace)
    registration = _register(client, publisher_headers, project["id"], package_zip, bundle_zip)
    assert registration.status_code == 201, registration.text
    publication = client.post(
        f"/projects/{project['id']}/models/{registration.json()['id']}/publish",
        headers=publisher_headers,
    )
    assert publication.status_code == 200, publication.text
    uploaded = _upload_log(client, operator_headers, project["id"])
    analysis = client.post(
        f"/projects/{project['id']}/analysis-runs",
        headers=operator_headers,
        json={
            "model_version_id": registration.json()["id"],
            "dataset_id": uploaded.json()["id"],
        },
    )
    assert analysis.status_code == 202, analysis.text
    return client, operator_headers, project, registration.json(), str(operator["id"])


def _complete_run_results(
    api: ApiFixture,
    run_id: str,
    operator_id: str,
    anomalies: list[dict[str, Any]],
    *,
    normal_count: int = 4,
) -> None:
    database = ApiDatabase(api.settings.database_url)
    identifier = UUID(run_id)
    actor = UUID(operator_id)
    database.transition_analysis_run(
        identifier,
        expected_status="queued",
        next_status="running",
        actor_user_id=actor,
    )
    database.transition_analysis_run(
        identifier,
        expected_status="running",
        next_status="completed",
        actor_user_id=actor,
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


def test_result_pages_are_typed_project_scoped_and_keep_run_wide_summaries(
    api: ApiFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers, project, model, operator_id = _queued_v2_run(api, monkeypatch)
    run_id = client.get(
        f"/projects/{project['id']}/analysis-runs",
        headers=headers,
    ).json()[0]["id"]
    assert (
        client.get(
            f"/projects/{project['id']}/analysis-runs/{run_id}/results"
        ).status_code
        == 401
    )
    source_context = {
        "matched_line_count": 37,
        "window": "ignored",
        "source_lines": [
            {"line_number": 12, "raw": "<script>blk_a</script>"},
            {"line_number": 18, "raw": "Receiving block blk_a"},
        ],
    }
    _complete_run_results(
        api,
        run_id,
        operator_id,
        [
            {
                "id": "00000000-0000-4000-8000-00000000000a",
                "record_reference": "blk_a",
                "anomaly_score": 0.91,
                "anomaly_level": "anomaly",
                "decision_threshold": 0.5,
                "context": source_context,
            },
            {
                "id": "00000000-0000-4000-8000-00000000000b",
                "record_reference": "blk_b",
                "anomaly_score": 0.91,
                "anomaly_level": "anomaly",
                "decision_threshold": 0.5,
                "context": {},
            },
            {
                "id": "00000000-0000-4000-8000-00000000000c",
                "record_reference": "blk_c",
                "anomaly_score": 0.4,
                "anomaly_level": "anomaly",
                "decision_threshold": 0.5,
                "context": {"matched_line_count": 1, "source_lines": []},
            },
        ],
        normal_count=5,
    )
    first = client.get(
        f"/projects/{project['id']}/analysis-runs/{run_id}/results",
        headers=headers,
        params={"limit": 2, "sort": "score_desc"},
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["summary"] == {
        "anomaly_count": 3,
        "normal_count": 5,
        "rejected_records": 0,
        "invalid_records": 0,
    }
    assert payload["query"]["limit"] == 2
    assert payload["query"]["sort"] == "score_desc"
    assert payload["next_cursor"]
    assert [item["block_id"] for item in payload["anomalies"]] == ["blk_a", "blk_b"]
    assert payload["anomalies"][0]["block_id"] == payload["anomalies"][0]["record_reference"]
    assert payload["anomalies"][0]["context"] == {
        "matched_line_count": 37,
        "source_lines": [
            {"line_number": 12, "raw": "<script>blk_a</script>"},
            {"line_number": 18, "raw": "Receiving block blk_a"},
        ],
    }
    assert payload["anomalies"][1]["context"] == {"matched_line_count": 0, "source_lines": []}
    assert payload["trace"]["model_identifier"] == model["model_identifier"]
    assert payload["trace"]["version"] == model["version"]
    assert payload["trace"]["model_version_id"] == model["id"]
    assert payload["trace"]["pipeline_run_id"] == model["pipeline_run_id"]
    assert payload["trace"]["artifact_checksum"] == model["artifact_sha256"]
    assert payload["trace"]["preprocessing_bundle"] == model["preprocessing_bundle"]

    second = client.get(
        f"/projects/{project['id']}/analysis-runs/{run_id}/results",
        headers=headers,
        params={"limit": 2, "sort": "score_desc", "cursor": payload["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    assert [item["block_id"] for item in second.json()["anomalies"]] == ["blk_c"]
    assert second.json()["next_cursor"] is None
    assert second.json()["summary"]["anomaly_count"] == 3

    filtered = client.get(
        f"/projects/{project['id']}/analysis-runs/{run_id}/results",
        headers=headers,
        params={"min_score": 0.9, "block_id_prefix": "blk_a"},
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["block_id"] for item in filtered.json()["anomalies"]] == ["blk_a"]
    assert filtered.json()["summary"]["anomaly_count"] == 3
    assert filtered.json()["summary"]["normal_count"] == 5

    mismatched = client.get(
        f"/projects/{project['id']}/analysis-runs/{run_id}/results",
        headers=headers,
        params={"sort": "block_id_asc", "cursor": payload["next_cursor"]},
    )
    assert mismatched.status_code == 422
    unknown = client.get(
        f"/projects/{project['id']}/analysis-runs/{run_id}/results",
        headers=headers,
        params={"limit": 2, "unknown": "1"},
    )
    assert unknown.status_code == 422
    too_large = client.get(
        f"/projects/{project['id']}/analysis-runs/{run_id}/results",
        headers=headers,
        params={"limit": 101},
    )
    assert too_large.status_code == 422
    infinite = client.get(
        f"/projects/{project['id']}/analysis-runs/{run_id}/results",
        headers=headers,
        params={"min_score": "inf"},
    )
    assert infinite.status_code == 422
