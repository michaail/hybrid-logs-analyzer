"""Password, identity, and JWT helpers for administrator-provisioned accounts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from src.api.settings import ApiSettings

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]{3,64}$")


def canonical_username(username: str) -> str:
    """Return the unique lowercase login identity for a provisioned account."""
    normalized = username.lower()
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Username must be 3-64 characters of lowercase letters, digits, "
            "underscore, dot, or hyphen."
        )
    return normalized


def hash_password(password: str) -> str:
    """Return a salted scrypt password hash without retaining plaintext."""
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            _encode(salt),
            _encode(digest),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    """Compare a password with a stored scrypt hash in constant time."""
    try:
        algorithm, n, r, p, encoded_salt, encoded_digest = encoded_hash.split("$")
        if algorithm != "scrypt":
            return False
        salt = _decode(encoded_salt)
        expected_digest = _decode(encoded_digest)
        actual_digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual_digest, expected_digest)


def create_access_token(user_id: UUID, settings: ApiSettings) -> str:
    """Create a signed, expiring bearer token for one provisioned user."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=settings.jwt_ttl_minutes)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": issued_at,
            "exp": expires_at,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_access_token(token: str, settings: ApiSettings) -> UUID | None:
    """Return the authenticated subject, or ``None`` for any invalid token."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        subject = payload.get("sub")
        return UUID(subject) if isinstance(subject, str) else None
    except (jwt.InvalidTokenError, ValueError):
        return None


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))
