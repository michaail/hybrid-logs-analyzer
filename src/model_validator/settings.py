"""Settings for the private model-validator HTTP service. No application secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

_FORBIDDEN_ENV = (
    "API_JWT_SECRET",
    "DATABASE_URL",
    "API_OBJECT_STORE_ENDPOINT",
    "API_OBJECT_STORE_BUCKET",
    "API_OBJECT_STORE_ACCESS_KEY_ID",
    "API_OBJECT_STORE_SECRET_ACCESS_KEY",
)


@dataclass(frozen=True)
class ValidatorSettings:
    """Token-only settings. This process has no database or object store."""

    internal_token: str

    @classmethod
    def from_environment(cls) -> "ValidatorSettings":
        """Load the service token and refuse JWT, database, and Bucket credentials."""

        load_dotenv()
        present = [name for name in _FORBIDDEN_ENV if os.environ.get(name, "").strip()]
        if present:
            raise RuntimeError(
                "Model validator must not receive JWT, database, or object-store "
                f"credentials ({', '.join(present)})."
            )
        token = os.environ.get("MODEL_VALIDATOR_INTERNAL_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "MODEL_VALIDATOR_INTERNAL_TOKEN must be set before starting the "
                "model validator."
            )
        return cls(internal_token=token)
