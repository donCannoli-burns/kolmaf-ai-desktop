"""Canonical transport identity for approved==executed transport binding.

Fields (minimum): kind, scheme, host, port, path_class, method.
Canonicalization: lowercase scheme/host, strip trailing dot, explicit or
default port per scheme, credentials/userinfo rejected, path_class is the
visible endpoint class. Fingerprint is sha256 of the canonical field dict.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlsplit

RELAY_KIND = "relay-writer"
DRYRUN_KIND = "gcli-dry-run"
FAKE_KIND_PREFIX = "fake"

_ALLOWED_SCHEMES = ("http",)
_DEFAULT_PORTS = {"http": 80}

# Explicit, small accepted loopback set (literal canonical host match only).
# RFC1918/LAN/public IPs, arbitrary hostnames, and encoded/exotic IP forms are
# never accepted. Private network is not loopback. ::1 is rejected; any future
# reopening requires an explicit spec amendment.
ACCEPTED_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})


class TransportIdentityError(ValueError):
    def __init__(self, classification: str, message: str):
        super().__init__(message)
        self.classification = classification


def _canonical_host(raw: str) -> str:
    host = raw.strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host.endswith("."):
        host = host[:-1]
    return host


def validate_relay_destination(url: str) -> tuple[str, str, int]:
    """Validate a credential-bearing relay destination.

    Returns (scheme, canonical_host, port) or raises TransportIdentityError
    with classification INVALID_RELAY_URL or NON_LOOPBACK_RELAY_REJECTED.
    No network I/O; pure parser policy.
    """
    if not isinstance(url, str) or not url.strip():
        raise TransportIdentityError("INVALID_RELAY_URL", "missing relay base URL")
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        raise TransportIdentityError("INVALID_RELAY_URL", "malformed relay URL")
    scheme = parts.scheme.strip().lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise TransportIdentityError("INVALID_RELAY_URL", f"unsupported scheme: {scheme or '<missing>'}")
    if "@" in parts.netloc:
        raise TransportIdentityError("INVALID_RELAY_URL", "userinfo not allowed in relay URL")
    host = parts.hostname
    if not host:
        raise TransportIdentityError("INVALID_RELAY_URL", "missing host")
    try:
        port = parts.port
    except ValueError:
        raise TransportIdentityError("INVALID_RELAY_URL", "invalid port")
    if port is None:
        port = _DEFAULT_PORTS[scheme]
    if not (0 < port < 65536):
        raise TransportIdentityError("INVALID_RELAY_URL", "port out of range")
    canonical = _canonical_host(host)
    if canonical not in ACCEPTED_LOOPBACK_HOSTS:
        raise TransportIdentityError(
            "NON_LOOPBACK_RELAY_REJECTED", f"relay destination must be loopback: {canonical}"
        )
    return scheme, canonical, port


@dataclass(frozen=True, slots=True)
class TransportIdentity:
    kind: str
    scheme: str
    host: str
    port: int
    path_class: str
    method: str
    opener_class: str = "not-applicable"
    environment_flag: str = "disabled"

    def canonical_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scheme": self.scheme,
            "host": self.host,
            "port": self.port,
            "path_class": self.path_class,
            "method": self.method,
            "opener_class": self.opener_class,
            "environment_flag": self.environment_flag,
        }

    def fingerprint(self) -> str:
        payload = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def relay_identity_from_url(url: str, *, opener_class: str = "no-redirect-opener") -> TransportIdentity:
    scheme, host, port = validate_relay_destination(url)
    return TransportIdentity(
        kind=RELAY_KIND,
        scheme=scheme,
        host=host,
        port=port,
        path_class="/sideCommand",
        method="POST",
        opener_class=opener_class,
        environment_flag=_live_flag_normalized(),
    )


def _live_flag_normalized() -> str:
    """Normalize KOLMAFA_LIVE_RELAY_ENABLED to 'enabled'/'disabled'."""
    import os

    raw = os.environ.get("KOLMAFA_LIVE_RELAY_ENABLED", "")
    return "enabled" if raw.strip().lower() in ("1", "true", "yes") else "disabled"


def identity_for_transport_label(transport: str) -> TransportIdentity:
    label = (transport or "").strip().lower()
    if not label:
        raise TransportIdentityError("UNAPPROVED_TRANSPORT", "missing transport label")
    return TransportIdentity(
        kind=label,
        scheme="local",
        host="",
        port=0,
        path_class="",
        method="local",
        opener_class="not-applicable",
        environment_flag=_live_flag_normalized(),
    )
