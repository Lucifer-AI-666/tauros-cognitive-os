"""API token generation and strength checks."""

from __future__ import annotations

import secrets

WEAK_TOKENS = frozenset(
    {
        "change-me-now",
        "changeme",
        "change_me",
        "secret",
        "password",
        "token",
        "tauros",
        "admin",
        "default",
        "test",
        "123456",
        "12345678",
    }
)


class SecurityError(RuntimeError):
    """Security policy violation."""


def generate_api_token(nbytes: int = 32) -> str:
    """Cryptographically strong token. Prefer this over any hand-written secret."""
    return secrets.token_urlsafe(nbytes)


def is_weak_token(token: str | None) -> bool:
    if not token:
        return True
    value = token.strip()
    if len(value) < 24:
        return True
    if value.lower() in WEAK_TOKENS:
        return True
    if value.lower().startswith("change-me"):
        return True
    unique = set(value)
    if len(unique) < 8:
        return True
    if any(ch * 8 in value for ch in unique):
        return True
    if value.isdigit() and len(value) < 40:
        return True
    if value.isalpha() and len(unique) < 10:
        return True
    return False


def assert_strong_token(token: str) -> None:
    if is_weak_token(token):
        raise SecurityError(
            "Token API debole o prevedibile. Usa `tauros init` per generarne uno sicuro "
            "(non inventarlo a mano)."
        )
