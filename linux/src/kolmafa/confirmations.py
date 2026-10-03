"""Durable one-shot confirmation records for game-affecting actions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import sqlite3

from kolmafa.policy import ActionClass
from kolmafa.redaction import redact_text


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def canonical_hash(value: object) -> str:
    """Hash canonical raw values for exact action comparisons.

    The digest is safe to persist for equality checks, but callers must keep
    redacted display/audit fields separate and must never persist the raw value
    alongside the digest.
    """

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfirmationProposal:
    """Data persisted before asking an operator to confirm an action."""

    confirmation_id: str
    policy_decision_id: str
    actor_id: str
    actor_surface: str
    command_class: ActionClass
    transport: str
    action_text: str
    arguments: Mapping[str, object]
    state_binding: str
    allowlist_id: str
    expires_at: datetime
    session_id: str | None = None
    task_id: str | None = None
    mode: str = ""
    transport_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class ConsumptionRequest:
    """Exact action details supplied immediately before execution."""

    confirmation_id: str
    actor_id: str
    action_text: str
    arguments: Mapping[str, object]
    transport: str
    mode: str
    allowlist_id: str
    state_binding: str
    command_log_id: str
    transport_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class ConsumptionResult:
    """Result of attempting to consume a confirmation."""

    allowed: bool
    reason: str


class ConfirmationStore:
    """SQLite-backed confirmation lifecycle API."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_pending(self, proposal: ConfirmationProposal) -> None:
        """Persist a pending confirmation and its policy decision trail."""

        action_text_redacted = redact_text(proposal.action_text)
        self.connection.execute(
            """
            INSERT OR IGNORE INTO policy_decisions(
                policy_decision_id, session_id, task_id, decision, command_class, allowlist_id,
                requires_confirmation, reason_redacted, expires_at
            ) VALUES (?, ?, ?, 'needs_confirmation', ?, ?, 1, ?, ?)
            """,
            (
                proposal.policy_decision_id,
                proposal.session_id,
                proposal.task_id,
                proposal.command_class.value,
                proposal.allowlist_id,
                "confirmation required",
                _utc_text(proposal.expires_at),
            ),
        )
        self.connection.execute(
            """
            INSERT INTO action_confirmations(
                confirmation_id, session_id, task_id, policy_decision_id, actor_id, actor_surface,
                command_class, transport, action_text_redacted, action_hash, arguments_hash,
                mode_hash, state_binding_hash, allowlist_id, transport_fingerprint, status, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                proposal.confirmation_id,
                proposal.session_id,
                proposal.task_id,
                proposal.policy_decision_id,
                proposal.actor_id,
                proposal.actor_surface,
                proposal.command_class.value,
                proposal.transport,
                action_text_redacted,
                canonical_hash(proposal.action_text),
                canonical_hash(proposal.arguments),
                canonical_hash(proposal.mode),
                canonical_hash(proposal.state_binding),
                proposal.allowlist_id,
                proposal.transport_fingerprint,
                _utc_text(proposal.expires_at),
            ),
        )
        self.connection.commit()

    def consume(self, request: ConsumptionRequest) -> ConsumptionResult:
        """Atomically consume a matching confirmed row exactly once."""

        row = self.connection.execute(
            "SELECT * FROM action_confirmations WHERE confirmation_id = ?",
            (request.confirmation_id,),
        ).fetchone()
        if row is None:
            return ConsumptionResult(False, "confirmation not found")
        if row["status"] != "confirmed" or row["consumed_at"] is not None:
            return ConsumptionResult(False, "confirmation is not consumable")
        if _parse_utc(row["expires_at"]) <= datetime.now(UTC):
            self.connection.execute(
                "UPDATE action_confirmations SET status = 'expired', invalidated_reason_redacted = 'expired' WHERE confirmation_id = ?",
                (request.confirmation_id,),
            )
            self.connection.commit()
            return ConsumptionResult(False, "confirmation expired")
        if row["actor_id"] != request.actor_id:
            return ConsumptionResult(False, "actor mismatch")
        if row["action_hash"] != canonical_hash(request.action_text):
            return ConsumptionResult(False, "action mismatch")
        if row["arguments_hash"] != canonical_hash(request.arguments):
            return ConsumptionResult(False, "argument mismatch")
        if row["transport"] != request.transport:
            return ConsumptionResult(False, "transport mismatch")
        if request.transport_fingerprint and row["transport_fingerprint"] != request.transport_fingerprint:
            return ConsumptionResult(False, "transport identity mismatch")
        if row["mode_hash"] != canonical_hash(request.mode):
            return ConsumptionResult(False, "mode mismatch")
        if row["allowlist_id"] != request.allowlist_id:
            return ConsumptionResult(False, "allowlist mismatch")
        if row["state_binding_hash"] != canonical_hash(request.state_binding):
            return ConsumptionResult(False, "state mismatch")

        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE action_confirmations
                SET status = 'consumed', consumed_at = CURRENT_TIMESTAMP, consumed_by_command_log_id = ?
                WHERE confirmation_id = ? AND status = 'confirmed' AND consumed_at IS NULL
                """,
                (request.command_log_id, request.confirmation_id),
            )
            if cursor.rowcount != 1:
                return ConsumptionResult(False, "confirmation replay denied")
        return ConsumptionResult(True, "consumed")


def confirm_action(connection: sqlite3.Connection, confirmation_id: str) -> None:
    """Mark a pending confirmation as operator-confirmed."""

    connection.execute(
        "UPDATE action_confirmations SET status = 'confirmed' WHERE confirmation_id = ? AND status = 'pending'",
        (confirmation_id,),
    )
    connection.commit()
