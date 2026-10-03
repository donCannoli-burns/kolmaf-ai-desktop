"""Real RelayWriter for Don Edition — small adapter around current relay implementation.

Conforms to GcliWriter protocol. Only invoked via ActionBroker.
No arbitrary URL, no general POST, no pwd logging, no retry on ambiguous outcome.
"""

from __future__ import annotations

import re
import socket
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from kolmafa.bridge import CommandResult, RELAY_TRANSPORT
from kolmafa.config import get_settings
from kolmafa.devtest.transport_identity import (
    TransportIdentity,
    TransportIdentityError,
    relay_identity_from_url,
    validate_relay_destination,
)
from kolmafa.redaction import redact_text
from kolmafa.devtest.evidence import record_evidence


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers):
        return None


def _default_opener() -> Callable:
    """Credential-bearing mutations never silently follow redirects."""
    return build_opener(_NoRedirect()).open



# OUTCOME_UNKNOWN sentinel for ambiguous network failures (timeout after send)
OUTCOME_UNKNOWN_TOKEN = "OUTCOME_UNKNOWN"

_UNKNOWN_MARKER: dict[str, Any] = {"result_kind": "unknown"}
_ALLOWED_REDIRECT_PATHS = frozenset({"choice.php", "main.php", "inventory.php", "inv_use.php"})
_ERROR_MARKERS = (
    ("insufficient_items", "insufficient items to use"),
    ("missing_item", "you don't have that item"),
    ("missing_item", "you don't have the item you're trying to use"),
    ("equip_restriction", "you can't equip a"),
    ("equip_restriction", "you can't wear a"),
    ("already_equipped", "you are already wearing"),
)


def command_result_marker(body: str) -> dict[str, Any]:
    """Extract only deterministic, allowlisted markers from a relay response.

    The response body is never returned. Unrecognized bodies fail closed to a
    single unknown marker; no arbitrary text, HTML, query string, or secret is
    retained.
    """

    if not isinstance(body, str) or not body.strip():
        return dict(_UNKNOWN_MARKER)
    text = body.casefold()
    choice = re.search(r"whichchoice\s*[=/:]\s*(\d{1,6})", text)
    if choice:
        return {"result_kind": "choice", "choice_id": int(choice.group(1))}
    redirect = re.search(
        r"(?:redirect(?:ed)?(?:\s+to)?|location)\s*[:=]?\s*['\"]?/?([a-z0-9_.-]+\.php)",
        text,
    )
    if redirect and redirect.group(1) in _ALLOWED_REDIRECT_PATHS:
        return {"result_kind": "redirect", "redirect_path": redirect.group(1)}
    for error_class, marker in _ERROR_MARKERS:
        if marker in text:
            return {"result_kind": "error", "error_class": error_class}
    return dict(_UNKNOWN_MARKER)


def _is_ambiguous_error(exc: BaseException) -> bool:
    """Return True for timeout / connection reset / EOF after send — ambiguous.

    These imply the mutation may have reached KoLmafia but client didn't get response.
    """
    msg = str(exc).lower()
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    ambiguous_phrases = ("timed out", "timeout", "connection reset", "eof", "broken pipe", "reset by peer")
    return any(p in msg for p in ambiguous_phrases)


class RelayWriter:
    """Real writer that POSTs to KoLmafia relay sideCommand.

    Obtains relay_base_url and relay_pwd only from get_settings() (env/config).
    Never logs pwd. Single responsibility: one POST to sideCommand.
    Transport is explicitly injected for testability; production uses real urlopen.
    """

    def __init__(
        self,
        relay_base_url: str | None = None,
        relay_pwd: str | None = None,
        timeout: float = 30.0,
        opener: Callable | None = None,
    ):
        # Explicit params are captured; when omitted the destination and
        # credential are re-resolved from settings on each write so that a
        # post-approval config mutation cannot silently substitute transport.
        self._explicit_base_url = relay_base_url
        self._explicit_pwd = relay_pwd
        self.timeout = timeout
        self._opener: Callable | None = opener
        self.transport = RELAY_TRANSPORT

    @property
    def relay_base_url(self) -> str:
        if self._explicit_base_url is not None:
            return self._explicit_base_url
        return get_settings().relay_base_url

    @property
    def relay_pwd(self) -> str | None:
        if self._explicit_pwd is not None:
            return self._explicit_pwd
        return get_settings().relay_pwd

    def transport_identity(self) -> TransportIdentity:
        # Coordinate with the actual opener: a real (None) opener is the
        # uniform no-redirect opener; an injected (fake) opener is reported
        # distinctly so the identity no longer lies about the executor.
        opener_class = "no-redirect-opener" if self._opener is None else "injected-opener"
        return relay_identity_from_url(self.relay_base_url, opener_class=opener_class)

    def write(self, command: str, timeout: float = 60.0) -> CommandResult:
        """Send one relay sideCommand; handle secrets and ambiguous outcomes."""

        # Fail closed if auth not configured — do not send without pwd
        if not self.relay_pwd:
            return CommandResult(
                command=redact_text(command),
                transport=RELAY_TRANSPORT,
                return_code=2,
                stdout="",
                stderr="relay auth not configured: KOLMAFA_RELAY_PWD required\n",
            )

        # Fail closed if command empty
        normalized = command.strip().lower()
        if not normalized:
            return CommandResult(
                command=redact_text(command),
                transport=RELAY_TRANSPORT,
                return_code=2,
                stdout="",
                stderr="empty command denied\n",
            )

        # Only allow non-empty normalized command; broker already classified, but double-check no arbitrary URL
        # Never accept URL-like command
        if "://" in command or "http" in command.lower():
            return CommandResult(
                command=redact_text(command),
                transport=RELAY_TRANSPORT,
                return_code=2,
                stdout="",
                stderr="arbitrary URL denied\n",
            )

        effective_timeout = timeout if timeout is not None else self.timeout

        # Credential boundary: parse destination, validate loopback, and only
        # then construct the credential-bearing request. Zero network I/O may
        # happen before this validation succeeds.
        try:
            validate_relay_destination(self.relay_base_url)
        except TransportIdentityError as exc:
            record_evidence(
                "don_relay_write",
                "offline",
                "kolmafa.devtest.relay_writer",
                f"blocked {exc.classification}",
                extra={"classification": exc.classification},
            )
            return CommandResult(
                command=redact_text(command),
                transport=RELAY_TRANSPORT,
                return_code=2,
                stdout="",
                stderr=f"{exc.classification}: {exc}\n",
            )

        payload = urlencode({"pwd": self.relay_pwd, "cmd": command}).encode("utf-8")
        request = Request(urljoin(self.relay_base_url.rstrip("/") + "/", "sideCommand"), data=payload, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        open_fn = self._opener if self._opener is not None else _default_opener()

        try:
            with open_fn(request, timeout=effective_timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                # Extra defense: if relay echo somehow contains pwd, strip it
                if self.relay_pwd and self.relay_pwd in body:
                    body = body.replace(self.relay_pwd, "<redacted>")
        except HTTPError as exc:
            # Redirect following is disabled for credential-bearing mutations;
            # any redirect response fails closed, independent of target.
            if 300 <= exc.code < 400:
                record_evidence(
                    "don_relay_write",
                    "offline",
                    "kolmafa.devtest.relay_writer",
                    "blocked REDIRECT_DESTINATION_REJECTED",
                    extra={"classification": "REDIRECT_DESTINATION_REJECTED"},
                )
                return CommandResult(
                    command=redact_text(command),
                    transport=RELAY_TRANSPORT,
                    return_code=2,
                    stdout="",
                    stderr="REDIRECT_DESTINATION_REJECTED: redirect following disabled for credential-bearing mutations\n",
                )
            text = redact_text(str(exc))
            if self.relay_pwd and self.relay_pwd in text:
                text = text.replace(self.relay_pwd, "<redacted>")
            return CommandResult(
                command=redact_text(command),
                transport=RELAY_TRANSPORT,
                return_code=1,
                stdout="",
                stderr=f"relay send failed: {text}\n",
            )
        except (OSError, URLError, socket.timeout, TimeoutError) as exc:  # pragma: no cover - network edge
            # Never leak pwd in stderr — redact both via pattern and literal replacement
            text = redact_text(str(exc))
            if self.relay_pwd and self.relay_pwd in text:
                text = text.replace(self.relay_pwd, "<redacted>")
            if _is_ambiguous_error(exc):
                return CommandResult(
                    command=redact_text(command),
                    transport=RELAY_TRANSPORT,
                    return_code=2,
                    stdout="",
                    stderr=f"relay send ambiguous ({OUTCOME_UNKNOWN_TOKEN}): {text}\n",
                )
            return CommandResult(
                command=redact_text(command),
                transport=RELAY_TRANSPORT,
                return_code=1,
                stdout="",
                stderr=f"relay send failed: {text}\n",
            )
        except Exception as exc:  # pragma: no cover
            text = redact_text(str(exc))
            if self.relay_pwd and self.relay_pwd in text:
                text = text.replace(self.relay_pwd, "<redacted>")
            return CommandResult(
                command=redact_text(command),
                transport=RELAY_TRANSPORT,
                return_code=1,
                stdout="",
                stderr=f"relay send failed: {text}\n",
            )

        return CommandResult(
            command=redact_text(command),
            transport=RELAY_TRANSPORT,
            return_code=0,
            stdout="",
            stderr="",
            result_marker=command_result_marker(body),
        )
