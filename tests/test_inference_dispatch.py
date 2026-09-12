"""Dispatch configuration, bounded retry, and non-terminal activation failures."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from src.api.inference_dispatch import dispatch_analysis_run
from src.api.settings import ApiSettings


def _settings(tmp_path: Path, **overrides: object) -> ApiSettings:
    base = ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        jwt_secret="test-secret-not-for-production",
        trusted_workspace_root=tmp_path / "workspace",
        inference_service_url="http://inference.test",
        inference_internal_token="super-secret-inference-token",
        inference_retry_attempts=3,
        inference_retry_backoff_seconds=0.0,
        inference_connect_timeout_seconds=0.1,
        inference_read_timeout_seconds=0.1,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_retries_after_first_startup_failure_then_succeeds(tmp_path: Path) -> None:
    attempts: list[str] = []
    run_id = uuid4()

    def post(url: str, headers: Mapping[str, str], connect: float, read: float) -> int:
        del connect, read
        assert url == f"http://inference.test/internal/analysis-runs/{run_id}/execute"
        assert headers["Authorization"] == "Bearer super-secret-inference-token"
        attempts.append("call")
        if len(attempts) == 1:
            raise ConnectionRefusedError("connection refused")
        return 200

    dispatch_analysis_run(run_id, _settings(tmp_path), post=post, sleep=lambda _: None)
    assert len(attempts) == 2


def test_retries_transient_http_then_succeeds(tmp_path: Path) -> None:
    statuses: list[int] = []

    def post(url: str, headers: Mapping[str, str], connect: float, read: float) -> int:
        del url, headers, connect, read
        statuses.append(503 if not statuses else 200)
        return statuses[-1]

    dispatch_analysis_run(uuid4(), _settings(tmp_path), post=post, sleep=lambda _: None)
    assert statuses == [503, 200]


def test_exhausted_retry_does_not_raise(tmp_path: Path) -> None:
    calls = {"n": 0}

    def post(url: str, headers: Mapping[str, str], connect: float, read: float) -> int:
        del url, headers, connect, read
        calls["n"] += 1
        raise TimeoutError("connect timed out")

    dispatch_analysis_run(uuid4(), _settings(tmp_path), post=post, sleep=lambda _: None)
    assert calls["n"] == 3


def test_network_errors_are_logged_without_secrets(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    token = "super-secret-inference-token"

    def post(url: str, headers: Mapping[str, str], connect: float, read: float) -> int:
        del url, headers, connect, read
        raise ConnectionError("network down")

    with caplog.at_level(logging.WARNING, logger="src.api.inference_dispatch"):
        dispatch_analysis_run(
            uuid4(),
            _settings(tmp_path, inference_internal_token=token),
            post=post,
            sleep=lambda _: None,
        )
    assert caplog.records
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert token not in combined
    assert "Authorization" not in combined
    assert "Bearer" not in combined


def test_unauthorized_response_is_not_retried(tmp_path: Path) -> None:
    calls = {"n": 0}

    def post(url: str, headers: Mapping[str, str], connect: float, read: float) -> int:
        del url, headers, connect, read
        calls["n"] += 1
        return 401

    dispatch_analysis_run(uuid4(), _settings(tmp_path), post=post, sleep=lambda _: None)
    assert calls["n"] == 1


def test_unconfigured_dispatch_is_a_no_op(tmp_path: Path) -> None:
    def post(url: str, headers: Mapping[str, str], connect: float, read: float) -> int:
        del url, headers, connect, read
        raise AssertionError("unconfigured dispatch must not POST")

    dispatch_analysis_run(
        uuid4(),
        _settings(tmp_path, inference_service_url=None, inference_internal_token=None),
        post=post,
        sleep=lambda _: None,
    )


def _clear_inference_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "INFERENCE_SERVICE_URL",
        "INFERENCE_INTERNAL_TOKEN",
        "INFERENCE_CONNECT_TIMEOUT_SECONDS",
        "INFERENCE_READ_TIMEOUT_SECONDS",
        "INFERENCE_RETRY_ATTEMPTS",
        "INFERENCE_RETRY_BACKOFF_SECONDS",
        "API_OBJECT_STORE_ENDPOINT",
        "API_OBJECT_STORE_BUCKET",
        "API_OBJECT_STORE_ACCESS_KEY_ID",
        "API_OBJECT_STORE_SECRET_ACCESS_KEY",
        "API_OBJECT_STORE_REGION",
    ):
        monkeypatch.setenv(name, "")


def test_inference_settings_require_url_and_token_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_inference_env(monkeypatch)
    monkeypatch.setenv("API_JWT_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}")
    monkeypatch.setenv("API_TRUSTED_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("INFERENCE_SERVICE_URL", "http://inference.test")
    with pytest.raises(RuntimeError, match="must be set together"):
        ApiSettings.from_environment()

    monkeypatch.setenv("INFERENCE_INTERNAL_TOKEN", "token-value")
    loaded = ApiSettings.from_environment()
    assert loaded.inference_service_url == "http://inference.test"
    assert loaded.inference_internal_token == "token-value"
    assert loaded.inference_retry_attempts == 5
