"""Private inference service tests. Token and AST checks stay Torch-free at import."""

from __future__ import annotations

import ast
import hashlib
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.object_store import (
    FilesystemObjectStore,
    hdfs_reference_catalog_manifest_key,
    hdfs_reference_catalog_selected_ids_key,
    model_package_object_prefix,
    preprocessing_bundle_object_prefix,
)
from src.api.storage import ApiDatabase
from src.inference_service.errors import (
    InferenceExecutionError,
    map_completeness_catalog_error,
)
from src.inference_service.runner import verify_pinned_catalog
from src.inference_service.main import create_app
from src.inference_service.settings import InferenceSettings
from src.modules.hdfs_completeness import CompletenessCatalogError, REFERENCE_MEMBERSHIP_POLICY
from src.modules.hdfs_evaluation_data import (
    BlockLineCount,
    EvaluationDataManifest,
    EvaluationShardRecord,
    selected_block_ids_order_sha256,
    sha256_file,
)
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
MIXED_LOG = TINY_LOG + (
    "081109 203618 151 INFO dfs.DataNode$DataXceiver: "
    "Receiving block none src: /10.0.0.1:50010 dest: /10.0.0.2:50010\n"
).encode("utf-8")
UNASSIGNED_LOG = (
    "081109 203615 148 INFO dfs.DataNode$DataXceiver: "
    "Receiving block none src: /10.0.0.1:50010 dest: /10.0.0.2:50010\n"
).encode("utf-8")
TRUNCATED_MIXED_LOG = b"\n".join(
    (TINY_LOG.splitlines()[0], TINY_LOG.splitlines()[2], UNASSIGNED_LOG.strip())
) + b"\n"
UNMATCHED_LOG = (
    "081109 203615 148 INFO dfs.UnknownComponent: xyzzy-unmatched-line blk_9\n"
).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_catalog(destination: Path, block_ids: list[str]) -> tuple[Path, str]:
    destination.mkdir(parents=True, exist_ok=True)
    selected = destination / "selected-block-ids.txt"
    selected.write_text("".join(f"{block_id}\n" for block_id in block_ids), encoding="utf-8")
    digest_zero = "0" * 64
    manifest = EvaluationDataManifest(
        schema_version=1,
        corpus_sha256=digest_zero,
        labels_sha256=digest_zero,
        selected_block_ids_sha256=sha256_file(selected),
        selected_block_ids_order_sha256=selected_block_ids_order_sha256(block_ids),
        selected_block_count=len(block_ids),
        source_line_count=1,
        max_source_lines=100_000,
        max_blocks=25_000,
        selected_line_counts=[
            BlockLineCount(block_id=block_id, source_line_count=1) for block_id in block_ids
        ],
        shards=[
            EvaluationShardRecord(
                name="shard-000.log",
                sha256=digest_zero,
                source_line_count=1,
                block_count=len(block_ids),
            )
        ],
        timestamp_warnings=[],
    )
    path = destination / "manifest.json"
    path.write_text(manifest.model_dump_json() + "\n", encoding="utf-8")
    return path.resolve(), sha256_file(path)


def _temporary_catalog_pin(tmp_path: Path) -> tuple[Path, str]:
    return _write_catalog(tmp_path / "hdfs-completeness", ["blk_1", "blk_2"])


def _settings(
    tmp_path: Path,
    *,
    catalog_block_ids: list[str] | None = None,
    catalog_manifest: Path | None = None,
    catalog_sha256: str | None = None,
) -> InferenceSettings:
    if catalog_manifest is None:
        manifest, digest = _write_catalog(
            tmp_path / "hdfs-completeness",
            catalog_block_ids or ["blk_1", "blk_2"],
        )
    else:
        manifest = catalog_manifest
        digest = catalog_sha256 or hashlib.sha256(b"missing-catalog").hexdigest()
    return InferenceSettings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        internal_token=TOKEN,
        code_root=REPO_ROOT,
        object_store_root=(tmp_path / "objects").resolve(),
        hdfs_completeness_manifest=manifest,
        hdfs_completeness_manifest_sha256=digest,
    )


def _client(
    tmp_path: Path,
    *,
    catalog_block_ids: list[str] | None = None,
    catalog_manifest: Path | None = None,
    catalog_sha256: str | None = None,
) -> tuple[TestClient, InferenceSettings, ApiDatabase]:
    settings = _settings(
        tmp_path,
        catalog_block_ids=catalog_block_ids,
        catalog_manifest=catalog_manifest,
        catalog_sha256=catalog_sha256,
    )
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


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _service_log(log_path: Path) -> str:
    try:
        return log_path.read_text(encoding="utf-8")
    except OSError as error:
        return f"<unable to read service log: {type(error).__name__}>"


def _wait_for_service_health(
    process: subprocess.Popen[Any],
    port: int,
    log_path: Path,
    *,
    timeout_seconds: float = 20.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "no connection attempt made"
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise AssertionError(
                f"Private inference service exited before becoming healthy ({return_code}).\n"
                f"{_service_log(log_path)}"
            )
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            body = response.read().decode("utf-8", errors="replace")
            if response.status == 200 and body == '{"status":"ok"}':
                return
            last_error = f"health returned {response.status}: {body}"
        except OSError as error:
            last_error = f"{type(error).__name__}: {error}"
        finally:
            connection.close()
        time.sleep(0.1)
    raise AssertionError(
        f"Private inference service did not become healthy: {last_error}\n{_service_log(log_path)}"
    )


def _post_to_service(port: int, path: str) -> tuple[int, str]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20.0)
    try:
        connection.request("POST", path, body=b"", headers=_auth())
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8", errors="replace")
    finally:
        connection.close()


def _stop_service(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


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
    catalog_block_ids: list[str] | None = None,
) -> tuple[TestClient, UUID, ApiDatabase, InferenceSettings]:
    client, settings, database = _client(tmp_path, catalog_block_ids=catalog_block_ids)
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
                "preprocessing_bundle": package_manifest["preprocessing_bundle"],
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
    return client, UUID(str(run["id"])), database, settings


@pytest.mark.ml
def test_tiny_frozen_release_completes_block_level_results(tmp_path: Path) -> None:
    client, run_id, database, settings = _seed_queued_job(tmp_path)
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "completed"
    run = database.get_analysis_run(run_id)
    assert run is not None
    summary = json.loads(str(run["results_summary_json"]))
    assert summary["anomaly_count"] + summary["normal_count"] == 2
    assert summary["normal_count"] == 2
    assert database.list_anomaly_results(run_id) == []
    assert database.list_provisional_results(run_id) == []
    assert int(run["provisional_count"] or 0) == 0
    assert int(run["unassigned_context_line_count"] or 0) == 0
    assert run["classification_policy"] == REFERENCE_MEMBERSHIP_POLICY
    assert run["classification_catalog_sha256"] == settings.hdfs_completeness_manifest_sha256
    duplicate = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "completed"
    completed = database.get_analysis_run(run_id)
    assert completed is not None
    assert json.loads(str(completed["results_summary_json"])) == summary


@pytest.mark.ml
def test_unmatched_template_fails_without_partial_results(tmp_path: Path) -> None:
    client, run_id, database, _settings = _seed_queued_job(
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
    assert database.list_provisional_results(run_id) == []


@pytest.mark.ml
def test_missing_cluster_embedding_fails(tmp_path: Path) -> None:
    client, run_id, database, _settings = _seed_queued_job(tmp_path, cluster_ids_override=[999])
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "failed"
    run = database.get_analysis_run(run_id)
    assert run is not None
    assert run["error_code"] == "MISSING_CLUSTER_EMBEDDING"
    assert database.list_anomaly_results(run_id) == []
    assert database.list_provisional_results(run_id) == []


@pytest.mark.ml
def test_corrupt_state_dict_fails_model_load(tmp_path: Path) -> None:
    client, run_id, database, _settings = _seed_queued_job(tmp_path, artifact_bytes=b"not-a-state-dict")
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "failed"
    run = database.get_analysis_run(run_id)
    assert run is not None
    assert run["error_code"] == "MODEL_LOAD_FAILED"


@pytest.mark.ml
def test_checksum_mismatch_fails_before_load(tmp_path: Path) -> None:
    client, run_id, database, _settings = _seed_queued_job(tmp_path)
    run = database.get_analysis_run(run_id)
    assert run is not None
    store = FilesystemObjectStore(_settings.object_store_root)
    job = database.get_inference_execution(run_id)
    assert job is not None
    store.put(f"{job['model_package_reference']}/model.pt", b"tampered-bytes")
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "failed"
    failed = database.get_analysis_run(run_id)
    assert failed is not None
    assert failed["error_code"] == "MODEL_LOAD_FAILED"


@pytest.mark.ml
def test_manifest_bundle_binding_mismatch_fails_before_load(tmp_path: Path) -> None:
    client, run_id, database, _settings = _seed_queued_job(tmp_path)
    job = database.get_inference_execution(run_id)
    assert job is not None
    store = FilesystemObjectStore(_settings.object_store_root)
    manifest_key = f"{job['model_package_reference']}/{MANIFEST_NAME}"
    manifest = json.loads(store.get(manifest_key))
    manifest["preprocessing_bundle"]["identifier"] = "substituted-bundle"
    store.put(manifest_key, json.dumps(manifest).encode("utf-8"))

    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())

    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "failed"
    failed = database.get_analysis_run(run_id)
    assert failed is not None
    assert failed["error_code"] == "MODEL_LOAD_FAILED"


@pytest.mark.ml
def test_mixed_run_persists_exclusive_heuristic_and_provisional_outcomes(tmp_path: Path) -> None:
    client, run_id, database, settings = _seed_queued_job(
        tmp_path,
        log_bytes=MIXED_LOG,
        catalog_block_ids=["blk_1"],
    )
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "completed"
    run = database.get_analysis_run(run_id)
    assert run is not None
    summary = json.loads(str(run["results_summary_json"]))
    assert summary["anomaly_count"] == 0
    assert summary["normal_count"] == 1
    assert int(run["provisional_count"] or 0) == 1
    assert int(run["unassigned_context_line_count"] or 0) == 1
    assert run["classification_policy"] == REFERENCE_MEMBERSHIP_POLICY
    assert run["classification_catalog_sha256"] == settings.hdfs_completeness_manifest_sha256
    assert database.list_anomaly_results(run_id) == []
    provisional = database.list_provisional_results(run_id)
    assert len(provisional) == 1
    row = provisional[0]
    assert row["record_reference"] == "blk_2"
    assert row["reason_code"] == "not_in_reference_catalog"
    assert "anomaly_score" not in row.keys()
    assert "decision_threshold" not in row.keys()
    context = json.loads(str(row["context_json"]))
    assert "anomaly_score" not in context
    assert "decision_threshold" not in context
    assert context["matched_line_count"] >= 1
    assert context["source_lines"]


@pytest.mark.ml
def test_private_service_subprocess_persists_split_results(tmp_path: Path) -> None:
    _client, run_id, database, settings = _seed_queued_job(
        tmp_path,
        # blk_1 has only one retained line here: catalog membership remains a
        # heuristic, so it is still eligible for scoring rather than provisional.
        log_bytes=TRUNCATED_MIXED_LOG,
        catalog_block_ids=["blk_1"],
    )
    assert settings.hdfs_completeness_manifest is not None
    port = _available_port()
    log_path = tmp_path / "inference-service.log"
    environment = os.environ.copy()
    environment.update(
        {
            "API_CODE_ROOT": str(REPO_ROOT),
            "API_OBJECT_STORE_ROOT": str(settings.object_store_root),
            "DATABASE_URL": settings.database_url,
            "INFERENCE_HDFS_COMPLETENESS_MANIFEST": str(
                settings.hdfs_completeness_manifest
            ),
            "INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256": (
                settings.hdfs_completeness_manifest_sha256
            ),
            "INFERENCE_INTERNAL_TOKEN": TOKEN,
            "PORT": str(port),
            "PYTHONUNBUFFERED": "1",
            # The test exercises the shared filesystem store. Do not let a local
            # .env enable Bucket mode in the child process.
            "API_OBJECT_STORE_ACCESS_KEY_ID": "",
            "API_OBJECT_STORE_BUCKET": "",
            "API_OBJECT_STORE_ENDPOINT": "",
            "API_OBJECT_STORE_REGION": "",
            "API_OBJECT_STORE_SECRET_ACCESS_KEY": "",
        }
    )
    with log_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "src.inference_service"],
            cwd=REPO_ROOT,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_for_service_health(process, port, log_path)
            status_code, body = _post_to_service(
                port,
                f"/internal/analysis-runs/{run_id}/execute",
            )
            assert status_code == 200, body
            assert json.loads(body) == {"id": str(run_id), "status": "completed"}

            run = database.get_analysis_run(run_id)
            assert run is not None
            assert json.loads(str(run["results_summary_json"])) == {
                "anomaly_count": 0,
                "invalid_records": 0,
                "normal_count": 1,
                "rejected_records": 0,
            }
            assert int(run["provisional_count"] or 0) == 1
            assert int(run["unassigned_context_line_count"] or 0) == 1
            assert run["classification_policy"] == REFERENCE_MEMBERSHIP_POLICY
            assert run["classification_catalog_sha256"] == settings.hdfs_completeness_manifest_sha256
            assert database.list_anomaly_results(run_id) == []

            provisional = database.list_provisional_results(run_id)
            assert len(provisional) == 1
            assert provisional[0]["record_reference"] == "blk_2"
            assert provisional[0]["reason_code"] == "not_in_reference_catalog"
            assert "anomaly_score" not in provisional[0].keys()
            assert "decision_threshold" not in provisional[0].keys()
        except BaseException as error:
            output.flush()
            raise AssertionError(
                f"{error}\nPrivate inference service output:\n{_service_log(log_path)}"
            ) from error
        finally:
            _stop_service(process)


@pytest.mark.ml
def test_catalog_miss_completes_as_all_provisional(tmp_path: Path) -> None:
    client, run_id, database, _settings = _seed_queued_job(
        tmp_path,
        catalog_block_ids=["blk_9"],
    )
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "completed"
    run = database.get_analysis_run(run_id)
    assert run is not None
    summary = json.loads(str(run["results_summary_json"]))
    assert summary["anomaly_count"] == 0
    assert summary["normal_count"] == 0
    assert int(run["provisional_count"] or 0) == 2
    assert database.list_anomaly_results(run_id) == []
    references = {row["record_reference"] for row in database.list_provisional_results(run_id)}
    assert references == {"blk_1", "blk_2"}


@pytest.mark.ml
def test_unassigned_only_run_completes_with_context_count(tmp_path: Path) -> None:
    client, run_id, database, _settings = _seed_queued_job(
        tmp_path,
        log_bytes=UNASSIGNED_LOG,
        catalog_block_ids=["blk_1"],
    )
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "completed"
    run = database.get_analysis_run(run_id)
    assert run is not None
    summary = json.loads(str(run["results_summary_json"]))
    assert summary["anomaly_count"] == 0
    assert summary["normal_count"] == 0
    assert int(run["provisional_count"] or 0) == 0
    assert int(run["unassigned_context_line_count"] or 0) == 1
    assert database.list_anomaly_results(run_id) == []
    assert database.list_provisional_results(run_id) == []


def _queued_run_record(database: ApiDatabase) -> UUID:
    project = database.create_project("stale-running")
    user = database.create_user(
        username="operator",
        password_hash="x",
        is_administrator=False,
    )
    model = database.create_model_version(
        project_id=UUID(str(project["id"])),
        model_identifier="attribute-gae",
        version="stale",
        pipeline_run_id="baseline",
        artifact_reference="outputs/hdfs/baseline/attribute_gae.pt",
        package_reference="packages/hdfs/attribute-gae-v1",
        artifact_sha256="0" * 64,
        metrics_json="{}",
        metadata_json="{}",
        external_evaluation_evidence="evidence",
        actor_user_id=UUID(str(user["id"])),
    )
    dataset = database.upsert_dataset(
        project_id=UUID(str(project["id"])),
        storage_kind="workspace",
        object_reference="data/stored-hdfs.log",
        checksum=None,
        actor_user_id=UUID(str(user["id"])),
    )
    run = database.create_analysis_run(
        project_id=UUID(str(project["id"])),
        model_version_id=UUID(str(model["id"])),
        requested_by_user_id=UUID(str(user["id"])),
        log_reference="data/stored-hdfs.log",
        status="queued",
        validation_report_json="{}",
        error_code=None,
        completed_at=None,
        actor_user_id=UUID(str(user["id"])),
        dataset_id=UUID(str(dataset["id"])),
    )
    return UUID(str(run["id"]))


def _claim_running(database: ApiDatabase, run_id: UUID) -> None:
    database.transition_analysis_run(
        run_id,
        expected_status="queued",
        next_status="running",
        actor_user_id=None,
    )


def _backdate_running_audit(database: ApiDatabase, run_id: UUID) -> None:
    with database.session() as connection:
        connection.execute(
            """
            UPDATE audit_events
            SET created_at = ?
            WHERE resource_type = ? AND resource_id = ? AND action = ?
            """,
            (
                "2000-01-01T00:00:00+00:00",
                "analysis_run",
                str(run_id),
                "analysis.running",
            ),
        )


def test_stale_running_execute_fails_without_scoring(tmp_path: Path) -> None:
    client, _settings, database = _client(tmp_path)
    run_id = _queued_run_record(database)
    _claim_running(database, run_id)
    _backdate_running_audit(database, run_id)

    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())

    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "failed"
    failed = database.get_analysis_run(run_id)
    assert failed is not None
    assert failed["error_code"] == "INFERENCE_FAILED"
    assert "could not complete" in str(failed["validation_report_json"])


def test_fresh_running_execute_is_noop(tmp_path: Path) -> None:
    client, _settings, database = _client(tmp_path)
    run_id = _queued_run_record(database)
    _claim_running(database, run_id)

    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())

    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "running"
    current = database.get_analysis_run(run_id)
    assert current is not None
    assert current["status"] == "running"
    assert current["error_code"] is None


def _clear_inference_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "INFERENCE_INTERNAL_TOKEN",
        "DATABASE_URL",
        "API_CODE_ROOT",
        "API_OBJECT_STORE_ROOT",
        "INFERENCE_STALE_RUNNING_SECONDS",
        "INFERENCE_HDFS_COMPLETENESS_MANIFEST",
        "INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256",
        "API_OBJECT_STORE_ENDPOINT",
        "API_OBJECT_STORE_BUCKET",
        "API_OBJECT_STORE_ACCESS_KEY_ID",
        "API_OBJECT_STORE_SECRET_ACCESS_KEY",
        "API_OBJECT_STORE_REGION",
    ):
        monkeypatch.setenv(name, "")


def test_inference_settings_reject_incomplete_catalog_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_inference_env(monkeypatch)
    monkeypatch.setenv("INFERENCE_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}")
    manifest, digest = _temporary_catalog_pin(tmp_path)

    monkeypatch.setenv("INFERENCE_HDFS_COMPLETENESS_MANIFEST", str(manifest))
    with pytest.raises(RuntimeError, match="must be set together"):
        InferenceSettings.from_environment()

    monkeypatch.setenv("INFERENCE_HDFS_COMPLETENESS_MANIFEST", "")
    monkeypatch.setenv("INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256", digest)
    with pytest.raises(RuntimeError, match="must be set together"):
        InferenceSettings.from_environment()

    monkeypatch.setenv("INFERENCE_HDFS_COMPLETENESS_MANIFEST", str(manifest))
    monkeypatch.setenv("INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256", "not-a-digest")
    with pytest.raises(RuntimeError, match="64-character hex SHA-256"):
        InferenceSettings.from_environment()

    monkeypatch.setenv("INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256", digest)
    loaded = InferenceSettings.from_environment()
    assert loaded.hdfs_completeness_manifest == manifest
    assert loaded.hdfs_completeness_manifest_object_key is None
    assert loaded.hdfs_completeness_manifest_sha256 == digest


def test_inference_settings_treat_relative_key_as_object_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_inference_env(monkeypatch)
    monkeypatch.setenv("INFERENCE_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}")
    monkeypatch.setenv(
        "INFERENCE_HDFS_COMPLETENESS_MANIFEST",
        "hdfs/reference-catalog/manifest.json",
    )
    monkeypatch.setenv("INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256", "a" * 64)
    loaded = InferenceSettings.from_environment()
    assert loaded.hdfs_completeness_manifest is None
    assert loaded.hdfs_completeness_manifest_object_key == (
        "hdfs/reference-catalog/manifest.json"
    )


def test_health_returns_503_when_catalog_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "absent-catalog" / "manifest.json"
    client, _settings, _database = _client(
        tmp_path,
        catalog_manifest=missing,
        catalog_sha256="a" * 64,
    )
    health = client.get("/health")
    assert health.status_code == 503
    detail = str(health.json()["detail"])
    assert "catalog" in detail.lower()
    assert "absent-catalog" not in detail


def test_object_store_catalog_verifies_without_leaking_keys(tmp_path: Path) -> None:
    manifest, digest = _write_catalog(tmp_path / "catalog-src", ["blk_1"])
    store = FilesystemObjectStore(tmp_path / "objects")
    key = hdfs_reference_catalog_manifest_key()
    store.put(key, manifest.read_bytes())
    store.put(
        hdfs_reference_catalog_selected_ids_key(key),
        (manifest.parent / "selected-block-ids.txt").read_bytes(),
    )
    verify_pinned_catalog(
        store,
        manifest_path=None,
        manifest_object_key=key,
        expected_sha256=digest,
    )
    with pytest.raises(InferenceExecutionError) as caught:
        verify_pinned_catalog(
            store,
            manifest_path=None,
            manifest_object_key="hdfs/reference-catalog/missing.json",
            expected_sha256=digest,
        )
    assert caught.value.code == "COMPLETENESS_CATALOG_UNAVAILABLE"
    assert "reference-catalog" not in caught.value.public_message
    assert "missing.json" not in caught.value.public_message


def test_catalog_failures_map_to_safe_unavailable_error(tmp_path: Path) -> None:
    error = CompletenessCatalogError(
        f"catalog at {tmp_path / 'secret-catalog' / 'manifest.json'} failed",
        reason="manifest_digest_mismatch",
    )
    mapped = map_completeness_catalog_error(error)
    assert mapped.code == "COMPLETENESS_CATALOG_UNAVAILABLE"
    assert mapped.cause == "manifest_digest_mismatch"
    assert str(tmp_path) not in mapped.public_message
    assert "secret-catalog" not in mapped.public_message
    assert mapped.public_message == InferenceExecutionError(
        "COMPLETENESS_CATALOG_UNAVAILABLE"
    ).public_message


def _assert_catalog_failure_leaves_no_results(
    tmp_path: Path,
    client: TestClient,
    database: ApiDatabase,
    run_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _must_not_score(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not score")

    monkeypatch.setattr(
        "src.inference_service.runner._infer_from_materialized",
        _must_not_score,
    )
    executed = client.post(f"/internal/analysis-runs/{run_id}/execute", headers=_auth())
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "failed"
    failed = database.get_analysis_run(run_id)
    assert failed is not None
    assert failed["error_code"] == "COMPLETENESS_CATALOG_UNAVAILABLE"
    report = str(failed["validation_report_json"])
    assert "unavailable or failed verification" in report
    assert str(tmp_path) not in report
    assert "hdfs-completeness" not in report
    assert "manifest.json" not in report
    assert database.list_anomaly_results(run_id) == []
    assert database.list_provisional_results(run_id) == []


def test_missing_catalog_fails_without_partial_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    missing = tmp_path / "absent-catalog" / "manifest.json"
    client, _settings, database = _client(
        tmp_path,
        catalog_manifest=missing,
        catalog_sha256="0" * 64,
    )
    run_id = _queued_run_record(database)
    with caplog.at_level("ERROR"):
        _assert_catalog_failure_leaves_no_results(tmp_path, client, database, run_id, monkeypatch)
    assert "manifest_missing" in caplog.text
    assert "COMPLETENESS_CATALOG_UNAVAILABLE" in caplog.text
    failed = database.get_analysis_run(run_id)
    assert failed is not None
    report = str(failed["validation_report_json"])
    assert "absent-catalog" not in report
    assert str(missing) not in report


def test_altered_catalog_digest_fails_without_partial_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, digest = _write_catalog(tmp_path / "hdfs-completeness", ["blk_1"])
    wrong = "ab" * 32
    assert wrong != digest
    client, _settings, database = _client(
        tmp_path,
        catalog_manifest=manifest,
        catalog_sha256=wrong,
    )
    run_id = _queued_run_record(database)
    _assert_catalog_failure_leaves_no_results(tmp_path, client, database, run_id, monkeypatch)


def test_malformed_catalog_fails_without_partial_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_dir = tmp_path / "hdfs-completeness"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    manifest = catalog_dir / "manifest.json"
    manifest.write_text("{not-json", encoding="utf-8")
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    client, _settings, database = _client(
        tmp_path,
        catalog_manifest=manifest,
        catalog_sha256=digest,
    )
    run_id = _queued_run_record(database)
    _assert_catalog_failure_leaves_no_results(tmp_path, client, database, run_id, monkeypatch)


def test_health_reclaims_stale_running_runs(tmp_path: Path) -> None:
    client, _settings, database = _client(tmp_path)
    run_id = _queued_run_record(database)
    _claim_running(database, run_id)
    _backdate_running_audit(database, run_id)

    health = client.get("/health")

    assert health.status_code == 200
    failed = database.get_analysis_run(run_id)
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["error_code"] == "INFERENCE_FAILED"
