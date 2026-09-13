"""Start an isolated FastAPI process for Playwright E2E runs.

Uses a disposable SQLite database and object store under ``.e2e/``. Does not
read ``DATABASE_URL`` or ``API_JWT_SECRET`` from the developer's ``.env``.
The isolated validator subprocess is the existing Torch-free files-only helper
so E2E never deserializes a ``.pt`` artifact.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.bootstrap import bootstrap_administrator  # noqa: E402
from src.api.main import create_app  # noqa: E402
from src.api.settings import ApiSettings  # noqa: E402
from src.api.storage import ApiDatabase  # noqa: E402

E2E_ROOT = ROOT / ".e2e"
AUTH_DIR = ROOT / "playwright" / ".auth"
FILES_ONLY_VALIDATOR = ROOT / "tests" / "support" / "files_only_validator.py"
DEFAULT_API_PORT = 18000


def _password(env_name: str) -> str:
    configured = os.environ.get(env_name, "").strip()
    if configured:
        if len(configured) < 12:
            raise SystemExit(f"{env_name} must be at least 12 characters.")
        return configured
    return secrets.token_urlsafe(18)


def _username(env_name: str, default: str) -> str:
    return os.environ.get(env_name, default).strip() or default


def prepare_environment(api_port: int) -> ApiSettings:
    if E2E_ROOT.exists():
        shutil.rmtree(E2E_ROOT)
    E2E_ROOT.mkdir(parents=True)
    (E2E_ROOT / "workspace").mkdir()
    (E2E_ROOT / "objects").mkdir()
    (E2E_ROOT / "packages").mkdir()
    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    db_path = (E2E_ROOT / "analyzer.db").resolve()
    settings = ApiSettings(
        database_url=f"sqlite:///{db_path.as_posix()}",
        jwt_secret=secrets.token_urlsafe(48),
        trusted_workspace_root=(E2E_ROOT / "workspace").resolve(),
        jwt_ttl_minutes=120,
        code_root=ROOT,
        model_validator_command=(sys.executable, str(FILES_ONLY_VALIDATOR)),
        object_store_root=(E2E_ROOT / "objects").resolve(),
    )
    ApiDatabase(settings.database_url).apply_migrations()

    admin_username = _username("E2E_ADMIN_USERNAME", "e2e-admin")
    admin_password = _password("E2E_ADMIN_PASSWORD")
    bootstrap_administrator(settings, admin_username, admin_password)

    accounts = {
        "apiOrigin": f"http://127.0.0.1:{api_port}",
        "projectAName": "e2e-project-a",
        "projectBName": "e2e-project-b",
        "admin": {"username": admin_username, "password": admin_password},
        "publisherA": {
            "username": _username("E2E_PUBLISHER_USERNAME", "e2e.publisher.a"),
            "password": _password("E2E_PUBLISHER_PASSWORD"),
        },
        "projectBUser": {
            "username": _username("E2E_PROJECT_B_USER_USERNAME", "e2e.operator.b"),
            "password": _password("E2E_PROJECT_B_USER_PASSWORD"),
        },
    }
    (AUTH_DIR / "accounts.json").write_text(
        json.dumps(accounts, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve an isolated API for Playwright E2E.")
    parser.add_argument("--port", type=int, default=DEFAULT_API_PORT)
    arguments = parser.parse_args()
    settings = prepare_environment(arguments.port)

    import uvicorn

    app = create_app(settings)
    print(f"E2E API listening on http://127.0.0.1:{arguments.port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=arguments.port, log_level="warning")


if __name__ == "__main__":
    main()
