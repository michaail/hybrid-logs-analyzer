"""CLI-only bootstrap for the first API administrator."""

from __future__ import annotations

import argparse
import getpass
from uuid import UUID

from src.api.security import canonical_username, hash_password
from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase


def bootstrap_administrator(settings: ApiSettings, username: str, password: str) -> UUID:
    """Provision the initial Administrator after deployment migrations complete."""
    canonical = canonical_username(username)
    database = ApiDatabase(settings.database_url)
    if database.get_user_by_username(canonical) is not None:
        raise ValueError(f"User {canonical!r} already exists.")
    user = database.create_administrator(
        username=canonical,
        password_hash=hash_password(password),
    )
    return UUID(str(user["id"]))


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
