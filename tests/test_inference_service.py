"""Private inference service tests. Token and AST checks stay Torch-free at import."""

from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.object_store import (
    FilesystemObjectStore,
    model_package_object_prefix,
    preprocessing_bundle_object_prefix,
)
from src.api.storage import ApiDatabase
from src.inference_service.main import create_app
from src.inference_service.settings import InferenceSettings
from src.modules.inference_bundle import (
    DRAIN_CONFIG_NAME,
    DRAIN_PARSER_NAME,
    EMBEDDINGS_NAME,
    NODE_FEATURE_EXTRA_DIM,
    bundle_digest,
)
from src.modules.model_package import MANIFEST_NAME, PACKAGE_FORMAT_V2
from src.modules.parser.drain_parser import DrainParser, UnmatchedLogLine

REPO_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "inference-test-token-not-a-jwt"
TINY_LOG = (
    "081109 203615 148 INFO dfs.DataNode$DataXceiver: "
    "Receiving block blk_1 src: /10.0.0.1:50010 dest: /10.0.0.2:50010\n"
    "081109 203616 149 INFO dfs.DataNode$DataXceiver: "
    "Receiving block blk_1 src: /10.0.0.1:50011 dest: /10.0.0.2:50010\n"
    "081109 203617 150 INFO dfs.DataNode$DataXceiver: "
    "Receiving block blk_2 src: /10.0.0.1:50010 dest: /10.0.0.2:50010\n"
).encode("utf-8")
UNMATCHED_LOG = (
    "081109 203615 148 INFO dfs.UnknownComponent: xyzzy-unmatched-line blk_9\n"
).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _settings(tmp_path: Path) -> InferenceSettings:
    return InferenceSettings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        internal_token=TOKEN,
        code_root=REPO_ROOT,
        object_store_root=(tmp_path / "objects").resolve(),
    )


def _client(tmp_path: Path) -> tuple[TestClient, InferenceSettings, ApiDatabase]:
    settings = _settings(tmp_path)
    database = ApiDatabase(settings.database_url)
    database.apply_migrations()
    return TestClient(create_app(settings)), settings, database


def test_api_sources_do_not_import_inference_service() -> None:
    for path in Path("src/api").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith("src.inference_service") for alias in node.names
                )
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("src.inference_service")


def test_inference_service_rejects_missing_or_invalid_token(tmp_path: Path) -> None:
    client, _settings, _database = _client(tmp_path)
    run_id = uuid4()
    missing = client.post(f"/internal/analysis-runs/{run_id}/execute")
    assert missing.status_code == 401
    wrong = client.post(
        f"/internal/analysis-runs/{run_id}/execute",
        headers={"Authorization": "Bearer wrong-token-value-xxxxx"},
    )
    assert wrong.status_code == 401
    unknown = client.post(
        f"/internal/analysis-runs/{run_id}/execute",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert unknown.status_code == 404


def test_strict_annotation_fails_unmatched_lines(tmp_path: Path) -> None:
    config = REPO_ROOT / "configs" / "drain.ini"
    snapshot = tmp_path / "drain_parser.bin"
    fitted = tmp_path / "fit.log"
    fitted.write_bytes(TINY_LOG)
    parser = DrainParser(config_path=str(config), persistence_path=str(snapshot))
    parser.fit_file(str(fitted))
    parser.save()
    unmatched = tmp_path / "unmatched.log"
    unmatched.write_bytes(UNMATCHED_LOG)
    with pytest.raises(UnmatchedLogLine):
        parser.annotate_file(str(unmatched), unmatched="fail")


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _architecture(embed_dim: int = 2) -> dict[str, Any]:
    return {
        "node_dim": embed_dim + NODE_FEATURE_EXTRA_DIM,
        "edge_dim": 1,
        "hidden_dim": 2,
        "latent_dim": 2,
        "gine_aggregation": "sum",
        "node_transformation": "mlp",
        "edge_mean": [0.0],
        "edge_std": [0.2],
    }


def _fit_parser(tmp_path: Path, log_bytes: bytes) -> tuple[bytes, bytes, list[int]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = REPO_ROOT / "configs" / "drain.ini"
    snapshot = tmp_path / "drain_parser.bin"
    fitted = tmp_path / "fit.log"
    fitted.write_bytes(log_bytes)
    parser = DrainParser(config_path=str(config), persistence_path=str(snapshot))
    parser.fit_file(str(fitted))
    parser.save()
    annotated = parser.annotate_file(str(fitted), unmatched="fail")
    cluster_ids = sorted({int(value) for value in annotated["cluster_id"].tolist()})
    return config.read_bytes(), snapshot.read_bytes(), cluster_ids


def _embeddings_bytes(cluster_ids: list[int], width: int = 2) -> bytes:
    ids = np.asarray(cluster_ids, dtype=np.int64)
    vectors = np.ones((ids.size, width), dtype=np.float32)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, cluster_ids=ids, embeddings=vectors)
    return buffer.getvalue()


def _state_dict_bytes(architecture: dict[str, Any]) -> bytes:
    import torch

    from src.modules.models.gae import AttributeAwareGAE

    model = AttributeAwareGAE(
        node_dim=int(architecture["node_dim"]),
        edge_dim=int(architecture["edge_dim"]),
        hidden_dim=int(architecture["hidden_dim"]),
        latent_dim=int(architecture["latent_dim"]),
        gine_aggregation=str(architecture["gine_aggregation"]),
        node_transformation=str(architecture["node_transformation"]),
    )
    buffer = io.BytesIO()
    torch.save(model.state_dict(), buffer)
    return buffer.getvalue()


def _seed_queued_job(
    tmp_path: Path,
    *,
    log_bytes: bytes = TINY_LOG,
    fit_bytes: bytes | None = None,
    cluster_ids_override: list[int] | None = None,
    artifact_bytes: bytes | None = None,
) -> tuple[TestClient, UUID, ApiDatabase]:
    client, settings, database = _client(tmp_path)
    store = FilesystemObjectStore(settings.object_store_root)
    project = database.create_project("incident-a")
    user = database.create_user(username="operator", password_hash="x", is_administrator=False)
    project_id = UUID(str(project["id"]))
    user_id = UUID(str(user["id"]))
    model_id = uuid4()
    bundle_id = uuid4()
    version = "v2"
    package_prefix = model_package_object_prefix(project_id, model_id, version)
    bundle_prefix = preprocessing_bundle_object_prefix(project_id, bundle_id, version)

    drain_ini, drain_bin, cluster_ids = _fit_parser(tmp_path / "parser", fit_bytes or log_bytes)
    if cluster_ids_override is not None:
        cluster_ids = cluster_ids_override
    embeddings = _embeddings_bytes(cluster_ids or [1])
    architecture = _architecture()
    artifact = artifact_bytes if artifact_bytes is not None else _state_dict_bytes(architecture)
    evidence = json.dumps({"evaluation": "tiny fixture"}).encode("utf-8")
    package_checksums = {"model.pt": _sha256(artifact), "evidence.json": _sha256(evidence)}
    bundle_checksums = {
        DRAIN_CONFIG_NAME: _sha256(drain_ini),
        DRAIN_PARSER_NAME: _sha256(drain_bin),
        EMBEDDINGS_NAME: _sha256(embeddings),
    }
    digest = bundle_digest(bundle_checksums)
    package_manifest = {
        "model_identifier": "attribute-gae",
        "version": version,
        "source_compatibility": "hdfs",
        "format": PACKAGE_FORMAT_V2,
        "metrics": {"best_threshold": 1_000_000.0},
        "architecture": architecture,
        "scoring": {"alpha": 1.0, "beta": 1.0, "gamma": 0.0},
        "files": {
            "artifact": "model.pt",
            "evidence": "evidence.json",
            "checksums": package_checksums,
        },
        "preprocessing_bundle": {
            "identifier": "attribute-gae-preprocessing",
            "version": version,
            "digest": digest,
        },
    }
    bundle_manifest = {
        "identifier": "attribute-gae-preprocessing",
        "version": version,
        "source_compatibility": "hdfs",
        "format": "hdfs-preprocessing-bundle-v1",
        "digest": digest,
        "files": {
            "drain_config": DRAIN_CONFIG_NAME,
            "drain_parser": DRAIN_PARSER_NAME,
            "embeddings": EMBEDDINGS_NAME,
            "checksums": bundle_checksums,
        },
    }
    store.put(f"{package_prefix}/{MANIFEST_NAME}", json.dumps(package_manifest).encode("utf-8"))
    store.put(f"{package_prefix}/model.pt", artifact)
    store.put(f"{package_prefix}/evidence.json", evidence)
    store.put(f"{bundle_prefix}/{MANIFEST_NAME}", json.dumps(bundle_manifest).encode("utf-8"))
    store.put(f"{bundle_prefix}/{DRAIN_CONFIG_NAME}", drain_ini)
    store.put(f"{bundle_prefix}/{DRAIN_PARSER_NAME}", drain_bin)
    store.put(f"{bundle_prefix}/{EMBEDDINGS_NAME}", embeddings)
    dataset_id = uuid4()
    dataset_key = f"projects/{project_id}/datasets/{dataset_id}/hdfs.log"
    store.put(dataset_key, log_bytes)
    database.create_model_version(
        project_id=project_id,
        model_identifier="attribute-gae",
        version=version,
        pipeline_run_id="tiny",
        artifact_reference=f"{package_prefix}/model.pt",
        package_reference=package_prefix,
        artifact_sha256=package_checksums["model.pt"],
        metrics_json=json.dumps(package_manifest["metrics"], sort_keys=True),
        metadata_json=json.dumps(
            {
                "format": PACKAGE_FORMAT_V2,
                "architecture": architecture,
                "scoring": package_manifest["scoring"],
            },
            sort_keys=True,
        ),
        external_evaluation_evidence="evidence.json",
        storage_kind="object",
        checksum=package_checksums["model.pt"],
        actor_user_id=user_id,
        model_id=model_id,
        preprocessing_bundle={
            "id": str(bundle_id),
            "identifier": "attribute-gae-preprocessing",
            "version": version,
            "object_prefix": bundle_prefix,
            "manifest_checksum": digest,
            "metadata_json": "{}",
        },
    )
    database.publish_model_version(model_id, user_id)
    database.create_dataset(
        project_id=project_id,
        storage_kind="object",
        object_reference=dataset_key,
        checksum=_sha256(log_bytes),
        actor_user_id=user_id,
        dataset_id=dataset_id,
    )
    run = database.create_analysis_run(
        project_id=project_id,
        model_version_id=model_id,
        requested_by_user_id=user_id,
        log_reference=dataset_key,
        status="queued",
        validation_report_json="{}",
        error_code=None,
        completed_at=None,
        dataset_id=dataset_id,
    )
    return client, UUID(str(run["id"])), database


@pytest.mark.ml
def test_tiny_frozen_release_completes_block_level_results(tmp_path: Path) -> None:
    client, run_id, database = _seed_queued_job(tmp_path)
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "completed"
    run = database.get_analysis_run(run_id)
    assert run is not None
    summary = json.loads(str(run["results_summary_json"]))
    assert summary["anomaly_count"] + summary["normal_count"] == 2
    assert summary["normal_count"] == 2
    assert database.list_anomaly_results(run_id) == []
    duplicate = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "completed"
    completed = database.get_analysis_run(run_id)
    assert completed is not None
    assert json.loads(str(completed["results_summary_json"])) == summary


@pytest.mark.ml
def test_unmatched_template_fails_without_partial_results(tmp_path: Path) -> None:
    client, run_id, database = _seed_queued_job(
        tmp_path,
        log_bytes=UNMATCHED_LOG,
        fit_bytes=TINY_LOG,
    )
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "failed"
    run = database.get_analysis_run(run_id)
    assert run is not None
    assert run["error_code"] == "UNMATCHED_TEMPLATE"
    assert "frozen Drain" in str(run["validation_report_json"])
    assert database.list_anomaly_results(run_id) == []


@pytest.mark.ml
def test_missing_cluster_embedding_fails(tmp_path: Path) -> None:
    client, run_id, database = _seed_queued_job(tmp_path, cluster_ids_override=[999])
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "failed"
    run = database.get_analysis_run(run_id)
    assert run is not None
    assert run["error_code"] == "MISSING_CLUSTER_EMBEDDING"


@pytest.mark.ml
def test_corrupt_state_dict_fails_model_load(tmp_path: Path) -> None:
    client, run_id, database = _seed_queued_job(tmp_path, artifact_bytes=b"not-a-state-dict")
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "failed"
    run = database.get_analysis_run(run_id)
    assert run is not None
    assert run["error_code"] == "MODEL_LOAD_FAILED"


@pytest.mark.ml
def test_checksum_mismatch_fails_before_load(tmp_path: Path) -> None:
    client, run_id, database = _seed_queued_job(tmp_path)
    run = database.get_analysis_run(run_id)
    assert run is not None
    store = FilesystemObjectStore(_settings(tmp_path).object_store_root)
    job = database.get_inference_execution(run_id)
    assert job is not None
    store.put(f"{job['model_package_reference']}/model.pt", b"tampered-bytes")
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "failed"
    failed = database.get_analysis_run(run_id)
    assert failed is not None
    assert failed["error_code"] == "MODEL_LOAD_FAILED"
