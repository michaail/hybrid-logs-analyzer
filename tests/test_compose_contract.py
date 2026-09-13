"""Lock Compose isolation and published ports without a Docker daemon."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "compose.yaml"
EXPECTED_SERVICES = frozenset(
    {"postgres", "migrate", "web", "inference", "model-validator"}
)
OBJECT_VOLUME = "objects"
_FORBIDDEN_VALIDATOR_ENV = (
    "DATABASE_URL",
    "API_JWT_SECRET",
)
_FORBIDDEN_VALIDATOR_ENV_PREFIXES = ("API_OBJECT_STORE_",)


def _compose_document() -> dict[str, Any]:
    loaded = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _services() -> dict[str, Any]:
    services = _compose_document().get("services")
    assert isinstance(services, dict)
    return services


def _environment(service: dict[str, Any]) -> dict[str, str]:
    raw = service.get("environment") or {}
    if isinstance(raw, dict):
        return {str(key): "" if value is None else str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        parsed: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, str) or "=" not in item:
                continue
            key, value = item.split("=", 1)
            parsed[key] = value
        return parsed
    raise AssertionError(f"unexpected environment: {raw!r}")


def _published_host_ports(service: dict[str, Any]) -> list[int]:
    published: list[int] = []
    for item in service.get("ports") or []:
        if isinstance(item, int):
            published.append(item)
        elif isinstance(item, str):
            parts = item.split(":")
            if len(parts) == 2:
                published.append(int(parts[0]))
            elif len(parts) >= 3:
                published.append(int(parts[-2]))
        elif isinstance(item, dict) and item.get("published") is not None:
            published.append(int(item["published"]))
        else:
            raise AssertionError(f"unexpected port mapping: {item!r}")
    return published


def _volume_entries(service: dict[str, Any]) -> list[Any]:
    volumes = service.get("volumes") or []
    assert isinstance(volumes, list)
    return volumes


def _volume_sources(service: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for item in _volume_entries(service):
        if isinstance(item, str):
            sources.append(item.split(":", 1)[0])
        elif isinstance(item, dict) and item.get("source") is not None:
            sources.append(str(item["source"]))
        else:
            raise AssertionError(f"unexpected volume mapping: {item!r}")
    return sources


def test_compose_defines_mvp_services() -> None:
    assert set(_services()) == EXPECTED_SERVICES


def test_compose_publishes_only_web_and_postgres_host_ports() -> None:
    published = {
        name: _published_host_ports(service) for name, service in _services().items()
    }
    assert published["web"] == [8000]
    assert published["postgres"] == [5433]
    for name, ports in published.items():
        if name in {"web", "postgres"}:
            continue
        assert ports == [], name


def test_compose_validator_env_has_no_app_secrets() -> None:
    env = _environment(_services()["model-validator"])
    for name in _FORBIDDEN_VALIDATOR_ENV:
        assert name not in env
    for key in env:
        assert not key.startswith(_FORBIDDEN_VALIDATOR_ENV_PREFIXES)
    assert set(env) == {"MODEL_VALIDATOR_INTERNAL_TOKEN"}


def test_compose_validator_has_no_object_volume() -> None:
    validator = _services()["model-validator"]
    assert OBJECT_VOLUME not in _volume_sources(validator)
    assert _volume_entries(validator) == []


def test_compose_inference_has_catalog_bind_and_sha() -> None:
    inference = _services()["inference"]
    env = _environment(inference)
    assert env["INFERENCE_HDFS_COMPLETENESS_MANIFEST"].endswith("/manifest.json")
    assert "INFERENCE_HDFS_COMPLETENESS_MANIFEST_SHA256" in env
    sources = _volume_sources(inference)
    assert OBJECT_VOLUME in sources
    catalog_binds = [
        item
        for item in _volume_entries(inference)
        if isinstance(item, str)
        and "HDFS_COMPLETENESS_CATALOG_DIR" in item
        and ":-" in item
        and item.endswith(":ro")
    ]
    assert catalog_binds, sources


def test_compose_web_has_private_service_urls() -> None:
    env = _environment(_services()["web"])
    assert env["INFERENCE_SERVICE_URL"] == "http://inference:8080"
    assert env["MODEL_VALIDATOR_SERVICE_URL"] == "http://model-validator:8080"
    assert OBJECT_VOLUME in _volume_sources(_services()["web"])
    assert "HDFS_COMPLETENESS_CATALOG_DIR" not in " ".join(
        str(item) for item in _volume_entries(_services()["web"])
    )


def test_compose_hardcodes_postgres_database_url() -> None:
    services = _services()
    for name in ("web", "migrate", "inference"):
        url = _environment(services[name])["DATABASE_URL"]
        assert "${DATABASE_URL}" not in url
        assert "postgres:5432" in url
    assert "DATABASE_URL" not in _environment(services["model-validator"])
    assert OBJECT_VOLUME not in _volume_sources(services["migrate"])
