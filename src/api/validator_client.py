"""Bounded HTTP client for the private HDFS model-validator service."""

from __future__ import annotations

import http.client
import json
import logging
import secrets
from collections.abc import Mapping
from urllib.parse import urlparse

from src.api.settings import ApiSettings
from src.api.validation import ValidatorUnavailableError
from src.modules.model_package import PackageValidationResult

logger = logging.getLogger(__name__)

_MAX_VALIDATOR_RESPONSE_BYTES = 1_048_576
_UNAVAILABLE = "Model package validator is unavailable."
_MALFORMED = "Model package validator returned a malformed report."


def post_package_validation(
    package_bytes: bytes,
    bundle_bytes: bytes,
    settings: ApiSettings,
) -> PackageValidationResult:
    """POST original ZIP bytes to the private validator. Never log the token."""

    service_url = settings.model_validator_service_url
    token = settings.model_validator_internal_token
    if not service_url or not token:
        raise ValidatorUnavailableError(_UNAVAILABLE)

    parsed = urlparse(service_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValidatorUnavailableError(_UNAVAILABLE)
    if parsed.username or parsed.password:
        raise ValidatorUnavailableError(_UNAVAILABLE)
    host = parsed.hostname
    if not host:
        raise ValidatorUnavailableError(_UNAVAILABLE)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path.rstrip("/") or ""
    path = f"{path}/internal/packages/validate"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    boundary = f"----ValidatorBoundary{secrets.token_hex(16)}"
    body = _encode_multipart(
        {
            "package": ("package.zip", package_bytes, "application/zip"),
            "preprocessing_bundle": ("bundle.zip", bundle_bytes, "application/zip"),
        },
        boundary,
    )
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    connection_cls = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_cls(
        host, port, timeout=settings.model_validator_connect_timeout_seconds
    )
    try:
        connection.connect()
        if connection.sock is not None:
            connection.sock.settimeout(settings.model_validator_read_timeout_seconds)
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read(_MAX_VALIDATOR_RESPONSE_BYTES + 1)
        status_code = int(response.status)
    except Exception as error:
        logger.warning("Model validator request failed: %s", type(error).__name__)
        raise ValidatorUnavailableError(_UNAVAILABLE) from error
    finally:
        connection.close()

    if status_code != 200:
        logger.warning("Model validator request returned HTTP %s", status_code)
        raise ValidatorUnavailableError(_UNAVAILABLE)
    if len(payload) > _MAX_VALIDATOR_RESPONSE_BYTES:
        raise ValidatorUnavailableError(_MALFORMED)
    try:
        parsed_payload = json.loads(payload.decode("utf-8"))
        return PackageValidationResult.model_validate(parsed_payload)
    except Exception as error:
        raise ValidatorUnavailableError(_MALFORMED) from error


def _encode_multipart(
    fields: Mapping[str, tuple[str, bytes, str]],
    boundary: str,
) -> bytes:
    parts: list[bytes] = []
    marker = boundary.encode("ascii")
    for name, (filename, content, content_type) in fields.items():
        header = (
            b"--"
            + marker
            + b"\r\n"
            + (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        parts.append(header + content + b"\r\n")
    parts.append(b"--" + marker + b"--\r\n")
    return b"".join(parts)
