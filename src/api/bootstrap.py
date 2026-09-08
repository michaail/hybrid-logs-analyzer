"""CLI-only bootstrap for the first API administrator."""

from __future__ import annotations

import argparse
import getpass
import json
from uuid import UUID

from src.api.security import hash_password
from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase


def bootstrap_administrator(settings: ApiSettings, username: str, password: str) -> UUID:
    """Provision the initial Administrator without exposing a public registration route."""
    database = ApiDatabase(settings.database_path)
    database.initialize()
    if database.get_user_by_username(username) is not None:
        raise ValueError(f"User {username!r} already exists.")
    user = database.create_user(
        username=username,
        password_hash=hash_password(password),
        is_administrator=True,
    )
    user_id = UUID(str(user["id"]))
    database.add_audit_event(
        actor_user_id=None,
        project_id=None,
        action="user.bootstrapped",
        resource_type="user",
        resource_id=user_id,
        details_json=json.dumps({"username": username}, sort_keys=True),
    )
    return user_id


def main() -> None:
    """Run the initial-administrator bootstrap command."""
    parser = argparse.ArgumentParser(description="Provision the first API administrator.")
    parser.add_argument("--username", required=True)
    arguments = parser.parse_args()
    password = getpass.getpass("Password: ")
    if len(password) < 12:
        parser.error("Password must contain at least 12 characters.")

    try:
        user_id = bootstrap_administrator(ApiSettings.from_environment(), arguments.username, password)
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(f"Bootstrapped administrator {arguments.username} ({user_id}).")


if __name__ == "__main__":
    main()
