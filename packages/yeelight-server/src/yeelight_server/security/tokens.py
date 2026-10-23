"""Password and token primitives (stdlib only)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string
import time
from typing import Iterable

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

MANAGER_TOKEN_PREFIX = "ylm_"
PAIRING_ALPHABET = string.ascii_uppercase + string.digits


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Hash a user password with scrypt."""

    if not isinstance(password, str) or not password:
        raise ValueError("Password must not be empty")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
        maxmem=64 * 1024 * 1024,
    )
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}$"
        f"{salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password without leaking timing information."""

    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_manager_token() -> str:
    return MANAGER_TOKEN_PREFIX + secrets.token_urlsafe(32)


def new_pairing_code(length: int = 8) -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(length))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def expires_at(seconds: float) -> float:
    return time.time() + seconds


def normalize_username(value: str) -> str:
    return value.strip().lower()


def password_is_strong(password: str, *, minimum: int = 8) -> bool:
    return isinstance(password, str) and len(password) >= minimum


def mask_token(token: str | None) -> str:
    """Return a non-secret fingerprint for logs/audit."""

    if not token:
        return ""
    return token_hash(token)[:12]
