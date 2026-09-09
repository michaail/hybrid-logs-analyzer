"""Test bootstrap for the repository's uninstalled ``src`` package."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from src.api.storage import ApiDatabase

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def postgres_database() -> Iterator[ApiDatabase]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is unset")
    try:
        import psycopg
        from psycopg import sql
    except ImportError:
        pytest.skip("psycopg is required for postgres-marked tests")

    parsed = urlsplit(url)
    database_name = f"f01_{uuid4().hex}"
    admin_url = urlunsplit(
        (str(parsed.scheme), str(parsed.netloc), "/postgres", str(parsed.query), str(parsed.fragment))
    )
    test_url = urlunsplit(
        (
            str(parsed.scheme),
            str(parsed.netloc),
            f"/{database_name}",
            str(parsed.query),
            str(parsed.fragment),
        )
    )
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    finally:
        admin.close()
    database = ApiDatabase(test_url)
    try:
        yield database
    finally:
        cleanup = psycopg.connect(admin_url, autocommit=True)
        try:
            cleanup.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
        finally:
            cleanup.close()
