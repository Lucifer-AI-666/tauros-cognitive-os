"""Secret redaction for logs, audit payloads, and nested objects."""

from __future__ import annotations

import logging
import re
from typing import Any

# Never capture secret *values* into groups that get re-emitted.
_REDACT_KV = re.compile(
    r"(?i)\b("
    r"[a-z0-9_]*(?:api[_-]?token|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"auth[_-]?token|client[_-]?secret|private[_-]?key|secret[_-]?key|"
    r"password|passwd|pwd|openai_api_key|anthropic_api_key|"
    r"github_token|gh_token|google_api_key|aws_secret_access_key|"
    r"aws_session_token|database_url|db_password|connection_string|"
    r"proxy_authorization|session_cookie|jwt)"
    r")\b\s*[:=]\s*\S+"
)
_REDACT_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_REDACT_BASIC = re.compile(r"(?i)\bbasic\s+[a-z0-9+/=]{8,}")
_REDACT_OPENAI = re.compile(r"(?i)\bsk-[a-z0-9]{10,}")
_REDACT_ANTHROPIC = re.compile(r"(?i)\bsk-ant-[a-z0-9\-_]{10,}")
_REDACT_GITHUB = re.compile(r"(?i)\b(ghp|gho|ghu|ghs|ghr)_[a-z0-9]{20,}")
_REDACT_GOOGLE = re.compile(r"(?i)\bAIza[0-9A-Za-z\-_]{20,}")
_REDACT_JWT = re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b")
_REDACT_CONN = re.compile(
    r"(?i)\b(postgres|postgresql|mysql|mongodb|redis|amqp|mssql)://\S+"
)

SENSITIVE_DICT_KEYS = frozenset(
    {
        "token",
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "set_cookie",
        "jwt",
        "access_token",
        "refresh_token",
        "private_key",
        "client_secret",
        "connection_string",
        "database_url",
    }
)

_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "authorization",
    "cookie",
)


def redact_text(text: str) -> str:
    """Redact secrets without ever re-emitting secret values."""
    if not text:
        return text
    out = _REDACT_KV.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    out = _REDACT_BEARER.sub("Bearer [REDACTED]", out)
    out = _REDACT_BASIC.sub("Basic [REDACTED]", out)
    out = _REDACT_OPENAI.sub("sk-[REDACTED]", out)
    out = _REDACT_ANTHROPIC.sub("sk-ant-[REDACTED]", out)
    out = _REDACT_GITHUB.sub("[REDACTED_GITHUB_TOKEN]", out)
    out = _REDACT_GOOGLE.sub("[REDACTED_GOOGLE_KEY]", out)
    out = _REDACT_JWT.sub("[REDACTED_JWT]", out)
    out = _REDACT_CONN.sub(lambda m: f"{m.group(1)}://[REDACTED]", out)
    return out


def _is_sensitive_key(key: str) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    if normalized in SENSITIVE_DICT_KEYS:
        return True
    return any(frag in normalized for frag in _SENSITIVE_KEY_FRAGMENTS)


def redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if _is_sensitive_key(k) else redact_obj(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_obj(v) for v in value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_obj(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact_obj(a) if isinstance(a, (str, dict, list, tuple)) else a
                    for a in record.args
                )
        return True


def install_log_redaction() -> None:
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "tauros"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in logger.filters):
            logger.addFilter(RedactingFilter())
