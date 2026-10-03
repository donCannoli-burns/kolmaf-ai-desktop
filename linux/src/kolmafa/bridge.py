"""KoLmafia command transport and session log tailing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import time
from typing import Any, Protocol
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
import uuid


from kolmafa.config import validate_player_name
from kolmafa.policy import ActionClass, ActionRequest, AllowlistEntry, ModeState, PolicyDecision, PolicyEngine
from kolmafa.redaction import redact_text


REDACTED_COMMAND = "<redacted>"
SEND_GATE_TRANSPORT = "send-gate"
SEND_GATE_DENY_CODE = 2
GCLI_DRY_RUN_TRANSPORT = "gcli-dry-run"
KOLMAFA_USER_PREFIX = "KOLMAFA_USER:"
KOLMAFA_OUTPUT_PREFIX = "KOL-AI:"
FIXED_RESPONSE_MESSAGE = "hello, I am online"
KOLMAFIA_GCLI_PROMPT_PREFIX = "> "
MAX_SESSION_LINE_BYTES = 4096
MAX_KOLMAFA_OUTPUT_BYTES = 2048
SEND_GATE_DENY_REASON = (
    "Kolmafa send is disabled by default until reviewed policy and human "
    "confirmation gates are implemented. Raw live relay, CLI, and fallback "
    "send transports fail closed."
)
RELAY_TRANSPORT = "relay"
DEFAULT_RELAY_MODE = "normal"
DEFAULT_RELAY_ALLOWLIST = [
    AllowlistEntry("relay-read-status", "status", DEFAULT_RELAY_MODE, ActionClass.READ_ONLY),
    AllowlistEntry("relay-read-version", "version", DEFAULT_RELAY_MODE, ActionClass.READ_ONLY),
    AllowlistEntry("relay-game-adventure", "adventure", DEFAULT_RELAY_MODE, ActionClass.GAME_AFFECTING),
]


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Result of sending one command to KoLmafia."""

    command: str
    transport: str
    return_code: int
    stdout: str
    stderr: str
    result_marker: dict[str, Any] | None = None


class BridgeError(RuntimeError):
    """Raised when bridge transport is not configured or fails."""


class GcliWriter(Protocol):
    """Boundary for writing one command to KoLmafia's GCLI surface."""

    def write(self, command: str, timeout: float = 60.0) -> CommandResult:
        """Return an audit-safe command result without exposing live mechanisms."""


@dataclass(frozen=True, slots=True)
class BridgeStatus:
    """Basic bridge readiness information."""

    database_path: Path
    kolmafia_home: Path
    session_dir: Path
    cli_command: str | None
    transport: str
    relay_base_url: str
    relay_pwd_configured: bool
    docker_available: bool
    container_running: bool | None
    player_name: str | None = None
    session_file: Path | None = None
    docker_free_ready: bool = False
    docker_free_problems: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SessionPrefixEvent:
    """A redacted player-originated event parsed from a KoLmafia session log."""

    event_id: str
    player_name: str
    message_redacted: str
    source_surface: str
    provenance: dict[str, object]


@dataclass(frozen=True, slots=True)
class SessionFileIdentity:
    """Durable identity for a session log inode observed by the listener."""

    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class SessionListenerCursor:
    """Durable tail cursor for a player session log."""

    cursor_id: str
    player_name: str
    source_path: str
    file_device: int | None
    file_inode: int | None
    file_mtime_ns: int | None
    byte_offset: int
    file_size: int
    rotation_state: str


@dataclass(frozen=True, slots=True)
class DryRunGcliWriter:
    """Non-mutating GCLI writer stub for proving write boundaries in tests.

    This writer never types, clicks, starts Docker, launches Java, or contacts a
    relay endpoint. It only returns a redacted ``CommandResult`` that can be
    stored by the existing command audit path.
    """

    transport: str = GCLI_DRY_RUN_TRANSPORT

    def write(self, command: str, timeout: float = 60.0) -> CommandResult:
        """Return a successful dry-run result without executing the command."""

        del timeout
        return CommandResult(
            command=redact_text(command),
            transport=self.transport,
            return_code=0,
            stdout="dry-run: GCLI command accepted by writer boundary; not executed\n",
            stderr="",
        )


@dataclass(frozen=True, slots=True)
class DeniedGcliWriter:
    """Fail-closed GCLI writer used when live or risky mechanisms are selected."""

    extra_reason: str = ""

    def write(self, command: str, timeout: float = 60.0) -> CommandResult:
        """Deny the write without inspecting, executing, or persisting raw command text."""

        del command, timeout
        return deny_send_result(self.extra_reason)


def default_gcli_writer(cli_command: str | None = None) -> GcliWriter:
    """Return the safe default GCLI writer for the configured CLI command.

    The default is a docker-free dry-run writer. Known second-instance fallbacks
    are refused before dry-run so tests and operators cannot normalize a risky
    path as safe. Live writes are intentionally out of scope.
    """

    if is_docker_cli_fallback(cli_command):
        return DeniedGcliWriter(
            " The Docker CLI fallback can start a second KoLmafia Java process and is blocked."
        )
    return DryRunGcliWriter()


def deny_send_result(extra_reason: str = "") -> CommandResult:
    """Return an audit-safe default-deny result for any send attempt."""

    return CommandResult(
        command=REDACTED_COMMAND,
        transport=SEND_GATE_TRANSPORT,
        return_code=SEND_GATE_DENY_CODE,
        stdout="",
        stderr=f"{SEND_GATE_DENY_REASON}{extra_reason}\n",
    )


def is_docker_cli_fallback(cli_command: str | None) -> bool:
    """Return whether the configured transport launches a second KoLmafia process."""

    return bool(cli_command and "kolmafia-gcli-docker.sh" in cli_command)


def send_relay_command(
    relay_base_url: str,
    relay_pwd: str | None,
    command: str,
    timeout: float = 30.0,
    *,
    connection: sqlite3.Connection | None = None,
    policy_engine: PolicyEngine | None = None,
    confirmation_id: str | None = None,
    actor_id: str = "operator",
    mode: str = DEFAULT_RELAY_MODE,
    state_binding: str = "",
) -> CommandResult:
    """Audit a relay command proposal without contacting live sideCommand by default.

    The live relay sideCommand transport remains quarantined behind a disabled
    future feature flag. Public calls preserve policy/audit behavior, but they
    fail closed before constructing a relay POST payload, encoding ``pwd``, or
    consuming a game-affecting confirmation.
    """

    if connection is None:
        return deny_send_result()

    arguments = {"command": command}
    if not _is_canonical_relay_command(command):
        decision = PolicyDecision(False, ActionClass.UNSAFE_UNKNOWN, "noncanonical relay command not reviewed")
    else:
        command_name = _policy_command_name(command)
        engine = policy_engine or PolicyEngine(DEFAULT_RELAY_ALLOWLIST)
        decision = engine.decide(
            ActionRequest(command=command_name, mode=mode, arguments=arguments),
            ModeState(mode=mode, state_binding=state_binding),
        )
    policy_decision_id = _record_policy_decision(connection, decision)

    if not decision.allowed and not decision.requires_confirmation:
        return _audit_denial(
            connection,
            command,
            decision,
            policy_decision_id,
            f"{SEND_GATE_DENY_REASON} policy denied relay send: {redact_text(decision.reason)}\n",
            confirmation_id=confirmation_id,
            redact_command=True,
        )
    return _audit_denial(
        connection,
        command,
        decision,
        policy_decision_id,
        f"{SEND_GATE_DENY_REASON} live relay sideCommand transport is quarantined; use dry-run or propose.\n",
        confirmation_id=confirmation_id,
        redact_command=True,
    )


def send_gcli_dry_run_command(
    command: str,
    timeout: float = 60.0,
    *,
    connection: sqlite3.Connection | None = None,
    policy_engine: PolicyEngine | None = None,
    writer: GcliWriter | None = None,
    confirmation_id: str | None = None,
    actor_id: str = "operator",
    mode: str = DEFAULT_RELAY_MODE,
    state_binding: str = "",
) -> CommandResult:
    """Send a dry-run GCLI command through policy, audit, and confirmation gates.

    This is the policy-bound writer entry point. It intentionally uses the same
    reviewed policy and durable confirmation path as relay sends, but the final
    transport is a non-mutating writer boundary. Live GCLI execution remains
    blocked.
    """

    if connection is None:
        return deny_send_result()

    arguments = {"command": command}
    if not _is_canonical_relay_command(command):
        decision = PolicyDecision(False, ActionClass.UNSAFE_UNKNOWN, "noncanonical writer command not reviewed")
    else:
        engine = policy_engine or PolicyEngine(DEFAULT_RELAY_ALLOWLIST)
        decision = engine.decide(
            ActionRequest(command=_policy_command_name(command), mode=mode, arguments=arguments),
            ModeState(mode=mode, state_binding=state_binding),
        )
    policy_decision_id = _record_policy_decision(connection, decision)

    if not decision.allowed and not decision.requires_confirmation:
        return _audit_denial(
            connection,
            command,
            decision,
            policy_decision_id,
            f"{SEND_GATE_DENY_REASON} policy denied dry-run writer send: {redact_text(decision.reason)}\n",
            confirmation_id=confirmation_id,
            redact_command=True,
        )

    command_log_id = uuid.uuid4().hex
    if decision.requires_confirmation:
        if not confirmation_id:
            return _audit_denial(
                connection,
                command,
                decision,
                policy_decision_id,
                "confirmation is required for game-affecting dry-run writer send\n",
            )
        if not _confirmation_exists(connection, confirmation_id):
            return _audit_denial(
                connection,
                command,
                decision,
                policy_decision_id,
                "confirmation not found\n",
            )
        if _confirmation_expired(connection, confirmation_id):
            return _audit_denial(
                connection,
                command,
                decision,
                policy_decision_id,
                "confirmation expired\n",
            )
        if not _confirmation_consumable(connection, confirmation_id):
            return _audit_denial(
                connection,
                command,
                decision,
                policy_decision_id,
                "confirmation replay denied\n",
            )
        _insert_command_audit(
            connection,
            command_log_id=command_log_id,
            command=command,
            transport=GCLI_DRY_RUN_TRANSPORT,
            command_class=decision.command_class,
            allowlist_id=decision.allowlist_id,
            policy_decision_id=policy_decision_id,
            confirmation_id=confirmation_id,
        )
    else:
        _insert_command_audit(
            connection,
            command_log_id=command_log_id,
            command=command,
            transport=GCLI_DRY_RUN_TRANSPORT,
            command_class=decision.command_class,
            allowlist_id=decision.allowlist_id,
            policy_decision_id=policy_decision_id,
        )

    result = (writer or DryRunGcliWriter()).write(command, timeout)
    _update_command_audit_result(connection, command_log_id, result)
    return result


def check_status(
    database_path: Path,
    kolmafia_home: Path,
    cli_command: str | None,
    transport: str = "relay",
    relay_base_url: str = "http://localhost:60080",
    relay_pwd: str | None = None,
    player_name: str | None = None,
) -> BridgeStatus:
    """Inspect local bridge readiness without changing game state."""

    session_dir = kolmafia_home / "sessions"
    configured_session_file = session_file(kolmafia_home, player_name) if player_name else None
    docker_free_problems = _docker_free_problems(kolmafia_home, session_dir, configured_session_file)
    docker_free_ready = not docker_free_problems
    docker_available = False
    container_running: bool | None = None
    if transport != "docker-free":
        try:
            docker_available = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                check=False,
                text=True,
            ).returncode == 0
        except FileNotFoundError:
            docker_available = False

        if docker_available:
            container_name = "kolmafia-web"
            if cli_command:
                parts = shlex.split(cli_command)
                if "docker" in parts and "exec" in parts:
                    try:
                        exec_index = parts.index("exec")
                        container_name = next(part for part in parts[exec_index + 1 :] if not part.startswith("-"))
                    except (StopIteration, ValueError):
                        container_name = "kolmafia-web"
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True,
                check=False,
                text=True,
            )
            container_running = result.stdout.strip() == "true" if result.returncode == 0 else False

    return BridgeStatus(
        database_path=database_path,
        kolmafia_home=kolmafia_home,
        session_dir=session_dir,
        cli_command=cli_command,
        transport=transport,
        relay_base_url=relay_base_url,
        relay_pwd_configured=bool(relay_pwd),
        docker_available=docker_available,
        container_running=container_running,
        player_name=player_name,
        session_file=configured_session_file,
        docker_free_ready=docker_free_ready,
        docker_free_problems=docker_free_problems,
    )


def _docker_free_problems(
    kolmafia_home: Path,
    session_dir: Path,
    configured_session_file: Path | None,
) -> tuple[str, ...]:
    """Return read-only docker-free readiness problems without creating paths."""

    problems: list[str] = []
    if not kolmafia_home.is_dir():
        problems.append("kolmafia_home_missing")
    if not session_dir.is_dir():
        problems.append("session_dir_missing")
    if configured_session_file is None:
        problems.append("player_name_unset")
    elif not configured_session_file.is_file():
        problems.append("session_log_missing")
    return tuple(problems)


def log_command(connection: sqlite3.Connection, result: CommandResult) -> None:
    """Store command result for operator review."""

    command_redacted = redact_text(result.command)
    stdout_redacted = redact_text(result.stdout)
    stderr_redacted = redact_text(result.stderr)
    marker_json = json.dumps(result.result_marker or {"result_kind": "unknown"}, sort_keys=True)
    connection.execute(
        """
        INSERT INTO command_log(
            transport, command_text_redacted, command_hash, return_code,
            stdout_redacted, stdout_hash, stderr_redacted, stderr_hash, result_marker_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.transport,
            command_redacted,
            _audit_hash(command_redacted),
            result.return_code,
            stdout_redacted,
            _audit_hash(stdout_redacted),
            stderr_redacted,
            _audit_hash(stderr_redacted),
            marker_json,
        ),
    )
    connection.commit()


def _audit_hash(value: str | None) -> str | None:
    """Return a stable review hash for an already-redacted audit value."""

    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _policy_command_name(command: str) -> str:
    """Return the reviewed policy command key for an exact relay command."""

    return command


def _is_canonical_relay_command(command: str) -> bool:
    """Return whether raw input is already the reviewed canonical form."""

    return command == command.strip() and command == command.lower()


def _record_policy_decision(connection: sqlite3.Connection, decision: PolicyDecision) -> str:
    """Persist one redacted policy decision and return its durable ID."""

    policy_decision_id = uuid.uuid4().hex
    decision_text = "allow" if decision.allowed else "needs_confirmation" if decision.requires_confirmation else "deny"
    connection.execute(
        """
        INSERT INTO policy_decisions(
            policy_decision_id, decision, command_class, allowlist_id,
            requires_confirmation, reason_redacted
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            policy_decision_id,
            decision_text,
            decision.command_class.value,
            decision.allowlist_id,
            int(decision.requires_confirmation),
            redact_text(decision.reason),
        ),
    )
    connection.commit()
    return policy_decision_id


def _confirmation_exists(connection: sqlite3.Connection, confirmation_id: str) -> bool:
    """Return whether a confirmation reference can be safely linked in audit."""

    return connection.execute(
        "SELECT 1 FROM action_confirmations WHERE confirmation_id = ?",
        (confirmation_id,),
    ).fetchone() is not None


def _confirmation_expired(connection: sqlite3.Connection, confirmation_id: str) -> bool:
    """Return whether a confirmed confirmation has passed its expiry."""

    row = connection.execute(
        "SELECT expires_at FROM action_confirmations WHERE confirmation_id = ? AND status = 'confirmed'",
        (confirmation_id,),
    ).fetchone()
    if row is None:
        return True
    expires = datetime.fromisoformat(row["expires_at"])
    return expires <= datetime.now(UTC)


def _confirmation_consumable(connection: sqlite3.Connection, confirmation_id: str) -> bool:
    """Return whether a confirmation can still be linked to a new command audit.

    The dry-run path does not call ``ConfirmationStore.consume``, so the
    ``action_confirmations.consumed_at`` column is never set.  Instead we
    check that the confirmation has not already been linked to a
    ``command_log`` row (the one-shot index
    ``idx_command_log_confirmation_one_shot`` enforces this at the schema
    level).
    """

    already_bound = connection.execute(
        "SELECT 1 FROM command_log WHERE confirmation_id = ?",
        (confirmation_id,),
    ).fetchone() is not None
    return not already_bound


def _audit_denial(
    connection: sqlite3.Connection,
    command: str,
    decision: PolicyDecision,
    policy_decision_id: str,
    stderr: str,
    *,
    confirmation_id: str | None = None,
    redact_command: bool = False,
) -> CommandResult:
    """Persist and return a fail-closed denial without linking confirmations.

    ``command_log.confirmation_id`` is a one-shot success link. Denied or
    failed pre-consume attempts must leave it unset so they cannot poison a
    later valid confirmation consume through the schema uniqueness guard.
    """

    del confirmation_id
    result = CommandResult(REDACTED_COMMAND, SEND_GATE_TRANSPORT, SEND_GATE_DENY_CODE, "", redact_text(stderr))
    _insert_command_audit(
        connection,
        command_log_id=uuid.uuid4().hex,
        command=REDACTED_COMMAND if redact_command else command,
        transport=SEND_GATE_TRANSPORT,
        command_class=decision.command_class,
        allowlist_id=decision.allowlist_id,
        policy_decision_id=policy_decision_id,
        confirmation_id=None,
        result=result,
    )
    return result


def _insert_command_audit(
    connection: sqlite3.Connection,
    *,
    command_log_id: str,
    command: str,
    transport: str,
    command_class: ActionClass,
    allowlist_id: str | None,
    policy_decision_id: str,
    confirmation_id: str | None = None,
    result: CommandResult | None = None,
) -> None:
    """Insert an audit row with redacted command/output and policy references."""

    stdout = redact_text(result.stdout) if result is not None else None
    stderr = redact_text(result.stderr) if result is not None else None
    command_redacted = redact_text(command)
    connection.execute(
        """
        INSERT INTO command_log(
            command_log_id, transport, command_class, command_text_redacted, command_hash,
            allowlist_id, confirmation_id, policy_decision_id, return_code,
            stdout_redacted, stdout_hash, stderr_redacted, stderr_hash, result_marker_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            command_log_id,
            transport,
            command_class.value,
            command_redacted,
            _audit_hash(command_redacted),
            allowlist_id,
            confirmation_id,
            policy_decision_id,
            result.return_code if result is not None else None,
            stdout,
            _audit_hash(stdout),
            stderr,
            _audit_hash(stderr),
            json.dumps(result.result_marker or {"result_kind": "unknown"}, sort_keys=True) if result is not None else "{}",
        ),
    )
    connection.commit()


def _update_command_audit_result(
    connection: sqlite3.Connection,
    command_log_id: str,
    result: CommandResult,
) -> None:
    """Update an existing audit row with redacted execution output."""

    connection.execute(
        """
        UPDATE command_log
        SET return_code = ?, stdout_redacted = ?, stdout_hash = ?, stderr_redacted = ?, stderr_hash = ?, result_marker_json = ?
        WHERE command_log_id = ?
        """,
        (
            result.return_code,
            redact_text(result.stdout),
            _audit_hash(redact_text(result.stdout)),
            redact_text(result.stderr),
            _audit_hash(redact_text(result.stderr)),
            json.dumps(result.result_marker or {"result_kind": "unknown"}, sort_keys=True),
            command_log_id,
        ),
    )
    connection.commit()


def _sanitize_file_identity(identity: str) -> str:
    """Return opaque identity, hashing values that contain path or basename signals.

    This is a defence-in-depth guard so that outward provenance never leaks a
    raw filesystem path, basename, home directory, or filename-derived
    ``location_hint`` even if a caller inadvertently passes one.
    """
    if "/" in identity or "\\" in identity or identity.startswith("~"):
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return identity


def parse_kolmafa_user_line(
    line: str,
    *,
    player_name: str,
    line_number: int | None = None,
    byte_offset: int | None = None,
    file_identity: str | None = None,
    max_line_bytes: int = MAX_SESSION_LINE_BYTES,
) -> SessionPrefixEvent | None:
    """Parse one deterministic ``KOLMAFA_USER:`` session line.

    The prefix is the only trusted routing signal. The message body is external
    player input, so this function redacts before returning an event and fails
    closed for malformed, empty, self-output, and oversized lines.
    """

    raw_line = line.rstrip("\r\n")
    if len(raw_line.encode("utf-8", errors="replace")) > max_line_bytes:
        return None
    candidate_line = raw_line
    if candidate_line.startswith(KOLMAFIA_GCLI_PROMPT_PREFIX):
        candidate_line = candidate_line[len(KOLMAFIA_GCLI_PROMPT_PREFIX) :]

    if not candidate_line.startswith(KOLMAFA_USER_PREFIX):
        return None

    message = candidate_line[len(KOLMAFA_USER_PREFIX) :].strip()
    if not message or message.startswith(KOLMAFA_OUTPUT_PREFIX):
        return None

    message_redacted = redact_text(message)
    event_id = _session_event_id(
        player_name,
        message_redacted,
        file_identity=file_identity,
        byte_offset=byte_offset,
    )
    provenance: dict[str, object] = {
        "prefix": KOLMAFA_USER_PREFIX,
        "player_name": player_name,
        "redaction_status": "redacted",
    }
    if line_number is not None:
        provenance["line_number"] = line_number
    if byte_offset is not None:
        provenance["byte_offset"] = byte_offset
    if file_identity is not None:
        provenance["file_identity"] = _sanitize_file_identity(file_identity)

    return SessionPrefixEvent(
        event_id=event_id,
        player_name=player_name,
        message_redacted=message_redacted,
        source_surface="kolmafia-session-log",
        provenance=provenance,
    )


def persist_session_event(connection: sqlite3.Connection, event: SessionPrefixEvent) -> bool:
    """Persist a redacted session event, returning ``False`` for duplicates."""

    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO session_events(
            event_id, player_name, message_redacted, message_hash, source_surface, provenance_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.player_name,
            event.message_redacted,
            _audit_hash(event.message_redacted),
            event.source_surface,
            json.dumps(event.provenance, sort_keys=True, separators=(",", ":")),
        ),
    )
    connection.commit()
    return cursor.rowcount == 1


def observe_session_file(
    path: Path,
    player_name: str,
    connection: sqlite3.Connection,
    *,
    max_line_bytes: int = MAX_SESSION_LINE_BYTES,
) -> list[SessionPrefixEvent]:
    """Parse and persist appended session-log user events without tailing forever.

    On first observation the listener records the current file identity and EOF
    offset, then returns no events. This avoids importing unrelated historical
    private session logs by default. Later calls tail only appended bytes, with
    rotation/truncation detected before event dedupe.
    """

    source_path = str(path)
    if not path.exists():
        _upsert_session_listener_cursor(
            connection,
            player_name=player_name,
            source_path=source_path,
            identity=None,
            byte_offset=0,
            file_size=0,
            rotation_state="missing",
        )
        return []

    identity = _session_file_identity(path)
    cursor = _get_session_listener_cursor(connection, player_name, source_path)
    if cursor is None or cursor.rotation_state == "missing":
        _upsert_session_listener_cursor(
            connection,
            player_name=player_name,
            source_path=source_path,
            identity=identity,
            byte_offset=identity.size,
            file_size=identity.size,
            rotation_state="initialized",
        )
        return []

    offset, rotation_state = _next_session_read_window(cursor, identity)
    events: list[SessionPrefixEvent] = []
    file_identity = _format_session_file_identity(identity)
    final_offset = offset
    with path.open("rb") as file:
        file.seek(offset)
        line_number = 1
        while True:
            byte_offset = file.tell()
            raw_line = file.readline(max_line_bytes + 1)
            if not raw_line:
                break
            if len(raw_line) > max_line_bytes and not raw_line.endswith(b"\n"):
                _discard_oversized_remainder(file)
                final_offset = file.tell()
                line_number += 1
                continue
            line = raw_line.decode("utf-8", errors="replace")
            event = parse_kolmafa_user_line(
                line,
                player_name=player_name,
                line_number=line_number,
                byte_offset=byte_offset,
                file_identity=file_identity,
                max_line_bytes=max_line_bytes,
            )
            final_offset = file.tell()
            if event is not None and persist_session_event(connection, event):
                events.append(event)
            line_number += 1
    _upsert_session_listener_cursor(
        connection,
        player_name=player_name,
        source_path=source_path,
        identity=identity,
        byte_offset=final_offset,
        file_size=identity.size,
        rotation_state=rotation_state,
    )
    return events


def build_kolmafa_output(
    message: str,
    *,
    max_output_bytes: int = MAX_KOLMAFA_OUTPUT_BYTES,
) -> str | None:
    """Build a constrained KoLmafia-visible output line or fail closed."""

    redacted = redact_text(message).strip()
    output = f"{KOLMAFA_OUTPUT_PREFIX} {redacted}"
    if not redacted or len(output.encode("utf-8", errors="replace")) > max_output_bytes:
        return None
    return output


def build_smart_response_proposal(
    event: SessionPrefixEvent,
    connection: sqlite3.Connection,
    *,
    max_output_bytes: int = MAX_KOLMAFA_OUTPUT_BYTES,
) -> str | None:
    """Build a RAG-enhanced response proposal based on the session event message.

    This function searches the local FTS5 index using the event's message as a query
    and constructs a proposal from the top results. It is proposal-only.
    """
    from kolmafa import rag

    query = event.message_redacted
    results = rag.search(connection, query)

    if not results:
        # No local RAG hits: fall back to the deterministic MVP proposal.
        return build_fixed_response_proposal(max_output_bytes=max_output_bytes)

    # Construct a response from the top snippet
    top_hit = results[0]
    snippet = top_hit["snippet"]
    source = top_hit["source_label"]
    message = f"Based on {source}: {snippet}"

    return build_kolmafa_output(message, max_output_bytes=max_output_bytes)


def build_llm_response_proposal(
    event: SessionPrefixEvent,
    connection: sqlite3.Connection,
    provider: object,
    *,
    max_output_bytes: int = MAX_KOLMAFA_OUTPUT_BYTES,
) -> str | None:
    """Build an LLM-synthesized response proposal using a provider-agnostic backend.

    The provider must implement the async ``generate(prompt, system_prompt)``
    contract from ``kolmafa.llm``. Retrieval context comes from the local FTS5
    index. The result is formatted as a KoLmafia-visible line and remains a
    proposal only.
    """
    from kolmafa import rag
    from kolmafa.llm import PromptBuilder, run_provider

    query = event.message_redacted
    results = rag.search(connection, query)
    context_parts = []
    for hit in results[:3]:
        context_parts.append(f"- {hit['source_label']}: {hit['snippet']}")
    context = "\n".join(context_parts)

    builder = PromptBuilder()
    user_prompt = builder.build(event.message_redacted, context)
    response = run_provider(provider, user_prompt, builder.get_system_prompt())

    # Strip any leading "KOL-AI:" or "KOLMAFA:" prefix the LLM may have
    # included (the prompt hints at the new format), so build_kolmafa_output
    # won't produce a double prefix.  Handle plain and markdown-bold variants.
    text = response.text.strip()
    text = text.removeprefix("**KOL-AI:**").removeprefix("**KOLMAFA:**")
    text = text.removeprefix("KOL-AI:").removeprefix("KOLMAFA:").strip()
    # Strip Unicode emoji — KoLmafia GCLI cannot render them. ASCII
    # emoticons like :) :p ;D are fine and are not affected.
    text = _strip_emoji(text)
    # Neutralize tool-call / function-call / command-action shaped output
    # so the provider cannot inject unexecuted action payloads into GCLI.
    text = _sanitize_provider_text(text)
    return build_kolmafa_output(text, max_output_bytes=max_output_bytes)


def _strip_emoji(text: str) -> str:
    """Remove Unicode emoji characters, keeping ASCII emoticons intact."""
    # Covers the most common emoji ranges used by LLMs
    # Note: \U requires exactly 8 hex digits; pad to the left.
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001FAFF"  # Misc symbols, emoticons, supplemental
        "\U00002600-\U000027BF"  # Misc symbols, dingbats
        "\U0000FE00-\U0000FE0F"  # Variation selectors
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        "\U0001FB00-\U0001FBFF"  # Symbols for Legacy Computing
        "\U0000200D"            # Zero-width joiner
        "\U000E007F"            # Cancel tag  (U+E007F, padded to 8)
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def _sanitize_provider_text(text: str) -> str:
    """Detect and neutralize tool-call/function-call/command-action shaped output.

    Providers (especially general-purpose LLMs) may return JSON that looks like
    a tool invocation, function call, or action command.  This function detects
    such patterns and replaces them with a safe no-action proposal so the raw
    payload is never emitted to the GCLI.

    Patterns checked:
    - ``"tool_calls"`` (OpenAI-style parallel tool calls)
    - ``"function_call"`` (older OpenAI-style single function call)
    - ``"function": {`` (function block inside a message)
    - Top-level JSON with ``"command"`` key
    - Top-level JSON with ``"action"`` key

    Non-JSON plain-text responses pass through unchanged.
    """
    stripped = text.strip()

    # Fast-path: if the text does not look like JSON at all, skip parsing.
    if not stripped.startswith("{"):
        return text

    # Check for tool/function call markers in raw text
    toolcall_markers = ('"tool_calls"', '"function_call"', '"function": {')
    if any(marker in stripped for marker in toolcall_markers):
        return "proposal only — tool/function call suppressed (not executed)"

    # Try parsing as JSON to check for command/action keys
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return text

    if not isinstance(parsed, dict):
        return text

    if "command" in parsed or "action" in parsed:
        return "proposal only — action request suppressed (not executed)"

    return text


def build_fixed_response_proposal(*, max_output_bytes: int = MAX_KOLMAFA_OUTPUT_BYTES) -> str | None:

    """Return the deterministic MVP response proposal or fail closed.

    The proposal is intentionally independent of player-supplied event text so
    the response loop never echoes user bodies by default. It is only a console
    audit proposal; callers must not treat it as a live write-back action.
    """

    return build_kolmafa_output(FIXED_RESPONSE_MESSAGE, max_output_bytes=max_output_bytes)


def _session_file_identity(path: Path) -> SessionFileIdentity:
    """Return durable identity and size for a present session log."""

    stat = path.stat()
    return SessionFileIdentity(
        device=stat.st_dev,
        inode=stat.st_ino,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def _format_session_file_identity(identity: SessionFileIdentity) -> str:
    """Return a redaction-safe string identity for provenance and dedupe."""

    return f"dev={identity.device}:ino={identity.inode}"


def _get_session_listener_cursor(
    connection: sqlite3.Connection,
    player_name: str,
    source_path: str,
) -> SessionListenerCursor | None:
    """Load the durable listener cursor for one player/path pair."""

    row = connection.execute(
        """
        SELECT cursor_id, player_name, source_path, file_device, file_inode, file_mtime_ns,
               byte_offset, file_size, rotation_state
        FROM session_listener_cursors
        WHERE player_name = ? AND source_path = ?
        """,
        (player_name, source_path),
    ).fetchone()
    if row is None:
        return None
    return SessionListenerCursor(
        cursor_id=row["cursor_id"],
        player_name=row["player_name"],
        source_path=row["source_path"],
        file_device=row["file_device"],
        file_inode=row["file_inode"],
        file_mtime_ns=row["file_mtime_ns"],
        byte_offset=row["byte_offset"],
        file_size=row["file_size"],
        rotation_state=row["rotation_state"],
    )


def _upsert_session_listener_cursor(
    connection: sqlite3.Connection,
    *,
    player_name: str,
    source_path: str,
    identity: SessionFileIdentity | None,
    byte_offset: int,
    file_size: int,
    rotation_state: str,
) -> None:
    """Persist listener file identity, byte offset, and rotation state."""

    cursor_id = hashlib.sha256(f"session-cursor\0{player_name}\0{source_path}".encode("utf-8")).hexdigest()
    metadata = {
        "redaction_status": "metadata-only",
        "mtime_ns": identity.mtime_ns if identity is not None else None,
    }
    connection.execute(
        """
        INSERT INTO session_listener_cursors(
            cursor_id, player_name, source_path, file_device, file_inode, file_mtime_ns,
            byte_offset, file_size, rotation_state, metadata_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(player_name, source_path) DO UPDATE SET
            file_device = excluded.file_device,
            file_inode = excluded.file_inode,
            file_mtime_ns = excluded.file_mtime_ns,
            byte_offset = excluded.byte_offset,
            file_size = excluded.file_size,
            rotation_state = excluded.rotation_state,
            metadata_json = excluded.metadata_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            cursor_id,
            player_name,
            source_path,
            identity.device if identity is not None else None,
            identity.inode if identity is not None else None,
            identity.mtime_ns if identity is not None else None,
            byte_offset,
            file_size,
            rotation_state,
            json.dumps(metadata, sort_keys=True, separators=(",", ":")),
        ),
    )
    connection.commit()


def _next_session_read_window(
    cursor: SessionListenerCursor,
    identity: SessionFileIdentity,
) -> tuple[int, str]:
    """Return byte offset and rotation state for the next bounded read."""

    same_file = cursor.file_device == identity.device and cursor.file_inode == identity.inode
    if not same_file:
        return 0, "rotated"
    if identity.size < cursor.byte_offset:
        return 0, "truncated"
    return cursor.byte_offset, "steady"


def _discard_oversized_remainder(file: object) -> None:
    """Consume the rest of an oversized binary line without decoding it."""

    while True:
        chunk = file.readline(MAX_SESSION_LINE_BYTES)
        if not chunk or chunk.endswith(b"\n"):
            return


def _session_event_id(
    player_name: str,
    message_redacted: str,
    *,
    file_identity: str | None = None,
    byte_offset: int | None = None,
) -> str:
    """Return a stable duplicate key for one redacted session-log position."""

    position = f"{file_identity or 'unknown-file'}\0{byte_offset if byte_offset is not None else 'unknown-offset'}"
    material = f"kolmafa-user\0{player_name}\0{position}\0{message_redacted}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def session_file(kolmafia_home: Path, player_name: str) -> Path:
    """Return expected KoLmafia session log path for a player."""

    safe_player_name = validate_player_name(player_name)
    if safe_player_name is None:
        raise BridgeError("KOLMAFA_PLAYER_NAME is required")
    return kolmafia_home / "sessions" / f"{safe_player_name}.txt"


def read_safe_session_events(path: Path, player_name: str) -> list[SessionPrefixEvent]:
    """Return redacted prefixed session events without exposing raw log lines."""

    if not path.is_file():
        raise BridgeError("session log is not an existing file; tail will not create live paths")
    events: list[SessionPrefixEvent] = []
    identity = _format_session_file_identity(_session_file_identity(path))
    with path.open("rb") as file:
        line_number = 1
        while True:
            byte_offset = file.tell()
            raw_line = file.readline(MAX_SESSION_LINE_BYTES + 1)
            if not raw_line:
                break
            if len(raw_line) > MAX_SESSION_LINE_BYTES and not raw_line.endswith(b"\n"):
                _discard_oversized_remainder(file)
                line_number += 1
                continue
            event = parse_kolmafa_user_line(
                raw_line.decode("utf-8", errors="replace"),
                player_name=player_name,
                line_number=line_number,
                byte_offset=byte_offset,
                file_identity=identity,
            )
            if event is not None:
                events.append(event)
            line_number += 1
    return events


def follow_session(path: Path, player_name: str = "unknown", poll_seconds: float = 0.5) -> None:
    """Print appended redacted KOLMAFA_USER session events forever."""

    if not path.is_file():
        raise BridgeError("session log is not an existing file; tail will not create live paths")
    identity = _format_session_file_identity(_session_file_identity(path))
    with path.open("rb") as file:
        file.seek(0, 2)
        line_number = 1
        while True:
            byte_offset = file.tell()
            raw_line = file.readline(MAX_SESSION_LINE_BYTES + 1)
            if raw_line:
                if len(raw_line) > MAX_SESSION_LINE_BYTES and not raw_line.endswith(b"\n"):
                    _discard_oversized_remainder(file)
                    line_number += 1
                    continue
                event = parse_kolmafa_user_line(
                    raw_line.decode("utf-8", errors="replace"),
                    player_name=player_name,
                    line_number=line_number,
                    byte_offset=byte_offset,
                    file_identity=identity,
                )
                if event is not None:
                    print(event.message_redacted)
                line_number += 1
            else:
                time.sleep(poll_seconds)
