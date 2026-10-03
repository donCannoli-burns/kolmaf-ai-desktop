"""Secret redaction helpers for persistence, audit, display, and RAG reuse."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


REDACTED = "<redacted>"

_SECRET_KEYS = frozenset(
    {
        "authorization",
        "bearer",
        "cookie",
        "pwd",
        "relay_pwd",
        "relay_hash",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "set_cookie",
        "secret",
        "webhook_secret",
    }
)

_KEY_VALUE_PATTERN = re.compile(
    r"(?i)\b(cookie|set-cookie|pwd|relay_pwd|relay_hash|password|token|access_token|refresh_token|api_key|secret|webhook_secret)\b\s*[:=]\s*([^\s,;]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+([^\s,;]+)")
_AUTHORIZATION_VALUE_PATTERN = re.compile(r"(?i)\bauthorization\b\s*[:=]\s*(?!bearer\b)([^\s,;]+)")
# Match typical JWT tokens: three base64url segments separated by dots,
# where the header segment starts with "eyJ" (base64 of '{"').
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def redact_text(value: object) -> str:
    """Return text with known secret-bearing values replaced by a marker."""

    text = str(value)
    text = _BEARER_PATTERN.sub(f"Authorization: Bearer {REDACTED}", text)
    text = _KEY_VALUE_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED}", text)
    text = _AUTHORIZATION_VALUE_PATTERN.sub(f"authorization={REDACTED}", text)
    return _JWT_PATTERN.sub(REDACTED, text)


def is_secret_key(key: str) -> bool:
    """Return whether a mapping key conventionally carries secret material."""

    normalized = key.lower().replace("-", "_")
    return normalized in _SECRET_KEYS or normalized.endswith(("_token", "_secret", "_password"))


def redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively redact secret-like mapping values."""

    redacted: dict[str, Any] = {}
    for key, value in mapping.items():
        if is_secret_key(key):
            redacted[key] = REDACTED
        elif isinstance(value, Mapping):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [redact_text(item) if not isinstance(item, Mapping) else redact_mapping(item) for item in value]
        elif isinstance(value, str):
            redacted[key] = redact_text(value)
        else:
            redacted[key] = value
    return redacted


def has_unredacted_secret(text: str | None) -> bool:
    """Return whether text still appears to contain secret-bearing material."""

    if text is None:
        return False
    redacted = redact_text(text)
    return redacted != text and REDACTED not in text
