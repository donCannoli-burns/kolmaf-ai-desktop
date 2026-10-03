"""Relay sideCommand transport for KoLmafia."""

from __future__ import annotations

from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from kolmafa.redaction import redact_text
from kolmafa.bridge import CommandResult, RELAY_TRANSPORT
from kolmafa.devtest.transport_identity import (
    TransportIdentityError,
    validate_relay_destination,
)


def _execute_relay_side_command(
    relay_base_url: str,
    relay_pwd: str,
    command: str,
    timeout: float,
) -> CommandResult:
    """Execute one KoLmafia relay sideCommand and redact response before returning."""

    # T2-gated helper: own loopback safety check before any network I/O.
    try:
        validate_relay_destination(relay_base_url)
    except TransportIdentityError as exc:
        return CommandResult(
            command=redact_text(command),
            transport=RELAY_TRANSPORT,
            return_code=2,
            stdout="",
            stderr=f"{exc.classification}: {exc}\n",
        )

    payload = urlencode({"pwd": relay_pwd, "cmd": command}).encode("utf-8")
    request = Request(urljoin(relay_base_url.rstrip("/") + "/", "sideCommand"), data=payload, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return CommandResult(
            command=redact_text(command),
            transport=RELAY_TRANSPORT,
            return_code=1,
            stdout="",
            stderr=f"relay send failed: {redact_text(exc)}\n",
        )
    return CommandResult(
        command=redact_text(command),
        transport=RELAY_TRANSPORT,
        return_code=0,
        stdout=redact_text(body),
        stderr="",
    )
