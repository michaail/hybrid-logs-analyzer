"""Bounded on-demand activation of the private HDFS inference service."""

from __future__ import annotations

import http.client
import logging
import time
from collections.abc import Callable, Mapping
from urllib.parse import urlparse
from uuid import UUID

from src.api.settings import ApiSettings

logger = logging.getLogger(__name__)

_TRANSIENT_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    BrokenPipeError,
    OSError,
    http.client.RemoteDisconnected,
    http.client.CannotSendRequest,
)

PostFn = Callable[[str, Mapping[str, str], float, float], int]
SleepFn = Callable[[float], None]


def dispatch_analysis_run(
    run_id: UUID,
    settings: ApiSettings,
    *,
    post: PostFn | None = None,
    sleep: SleepFn | None = None,
) -> None:
    """Activate inference for ``run_id`` without writing terminal run state.

    Missing configuration, exhausted retries, and network errors are logged
    without a token or object-store secret. The queued row is left unchanged.
    """

    try:
        _dispatch(run_id, settings, post=post, sleep=sleep)
    except Exception as error:
        logger.warning(
            "Inference dispatch failed for run %s: %s",
            run_id,
            type(error).__name__,
        )


def post_inference_execute(
    url: str,
    headers: Mapping[str, str],
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
) -> int:
    """POST an empty body with separate connect and read socket timeouts."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Inference service URL must be http or https.")
    if parsed.username or parsed.password:
        raise ValueError("Inference service URL must not include credentials.")
    host = parsed.hostname
    if not host:
        raise ValueError("Inference service URL must include a host.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    connection_cls = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_cls(host, port, timeout=connect_timeout_seconds)
    try:
        connection.connect()
        if connection.sock is not None:
            connection.sock.settimeout(read_timeout_seconds)
        connection.request("POST", path, body=b"", headers=dict(headers))
        response = connection.getresponse()
        response.read()
        return int(response.status)
    finally:
        connection.close()


def _dispatch(
    run_id: UUID,
    settings: ApiSettings,
    *,
    post: PostFn | None,
    sleep: SleepFn | None,
) -> None:
    service_url = settings.inference_service_url
    token = settings.inference_internal_token
    if not service_url or not token:
        logger.debug("Inference dispatch skipped for run %s; private service is not configured.", run_id)
        return

    poster = post or post_inference_execute
    sleeper = sleep or time.sleep
    execute_url = f"{service_url.rstrip('/')}/internal/analysis-runs/{run_id}/execute"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    attempts = max(1, settings.inference_retry_attempts)

    for attempt in range(1, attempts + 1):
        try:
            status_code = poster(
                execute_url,
                headers,
                settings.inference_connect_timeout_seconds,
                settings.inference_read_timeout_seconds,
            )
        except _RETRYABLE_EXCEPTIONS as error:
            if attempt >= attempts:
                logger.warning(
                    "Inference dispatch exhausted retries for run %s after %s attempts: %s",
                    run_id,
                    attempts,
                    type(error).__name__,
                )
                return
            _backoff(sleeper, settings.inference_retry_backoff_seconds, attempt)
            continue
        except Exception as error:
            logger.warning(
                "Inference dispatch failed for run %s: %s",
                run_id,
                type(error).__name__,
            )
            return

        if status_code < 400:
            return
        if status_code not in _TRANSIENT_STATUS_CODES or attempt >= attempts:
            logger.warning(
                "Inference dispatch received HTTP %s for run %s after %s attempt(s)",
                status_code,
                run_id,
                attempt,
            )
            return
        _backoff(sleeper, settings.inference_retry_backoff_seconds, attempt)


def _backoff(sleep: SleepFn, backoff_seconds: float, attempt: int) -> None:
    delay = backoff_seconds * attempt
    if delay > 0:
        sleep(delay)
