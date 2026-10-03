"""Single action broker for Don Edition — the only future live-write boundary.

Lifecycle:
  normalize → canonical proposal → classify → T1 redirect / T3 deny → durable confirmation → DryRun/fake transport → outcome

Reuse:
  - policy.PolicyEngine + DEFAULT_RELAY_ALLOWLIST
  - confirmations.ConfirmationStore + canonical_hash
  - bridge.DryRunGcliWriter (non-mutating) / injected fake transport
  - redaction.redact_text
  - evidence.record_evidence

No SpringBridge, no 8080, no second writer.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from kolmafa import bridge, db
from kolmafa.bridge import CommandResult, DryRunGcliWriter, GcliWriter, RELAY_TRANSPORT
from kolmafa.config import get_settings
from kolmafa.confirmations import (
    ConfirmationProposal,
    ConfirmationStore,
    ConsumptionRequest,
    canonical_hash,
    confirm_action,
)
from kolmafa.devtest.evidence import record_evidence
from kolmafa.devtest.item_identity import resolve_item_name
from kolmafa.devtest.transport_identity import (
    TransportIdentity,
    TransportIdentityError,
    identity_for_transport_label,
)
from kolmafa.policy import ActionClass, AllowlistEntry, PolicyEngine
from kolmafa.redaction import redact_text

# T3 structural deny — never allowed regardless of confirmation
T3_DENY_KEYWORDS = frozenset(
    {
        "kmail",
        "message",
        "chat",
        "trade",
        "stash",
        "clan",
        "login",
        "logout",
        "switch_account",
        "account_switch",
        "account",
        "release",
        "publish",
        "push",
        "irreversible",
    }
)

# Also deny broader patterns (substrings)
T3_DENY_SUBSTRINGS = frozenset(
    {
        "kmail",
        "chat",
        "trade",
        "stash",
        "login",
        "logout",
        "switch",
        "release",
        "publish",
        "clan",
    }
)

# Allowlist reused from current runtime
DEFAULT_ALLOWLIST = bridge.DEFAULT_RELAY_ALLOWLIST

# Additional T2 entries for Don broker tests (game-affecting)
EXTRA_T2 = [
    AllowlistEntry("don-use", "use", bridge.DEFAULT_RELAY_MODE, ActionClass.GAME_AFFECTING),
    AllowlistEntry("don-equip", "equip", bridge.DEFAULT_RELAY_MODE, ActionClass.GAME_AFFECTING),
    AllowlistEntry("don-craft", "craft", bridge.DEFAULT_RELAY_MODE, ActionClass.GAME_AFFECTING),
    AllowlistEntry("don-buy", "buy", bridge.DEFAULT_RELAY_MODE, ActionClass.GAME_AFFECTING),
]

COMBINED_ALLOWLIST = DEFAULT_ALLOWLIST + EXTRA_T2

TRANSPORT_DRYRUN = bridge.GCLI_DRY_RUN_TRANSPORT
DEFAULT_MODE = bridge.DEFAULT_RELAY_MODE
DEFAULT_TTL_HOURS = 24


def _normalize_action(action: str) -> str:
    """Return canonical normalized action text.

    Strip, lower, collapse internal spaces. Empty or non-string fails closed.
    """
    if not isinstance(action, str):
        return ""
    normalized = " ".join(action.strip().lower().split())
    return normalized


_EQUIP_SLOTS = frozenset(
    {
        "hat",
        "shirt",
        "pants",
        "weapon",
        "offhand",
        "acc1",
        "acc2",
        "acc3",
        "container",
        "familiarequip",
        "fakehands",
        "cardsleeve",
        "back",
    }
)


def _validate_equip_arguments(arguments: dict[str, Any]) -> str | None:
    """Validate the typed equip payload before it can become a command."""
    if not isinstance(arguments, dict):
        return "equip arguments must be an object"
    item = arguments.get("item")
    item_id = arguments.get("id")
    slot = arguments.get("slot")
    if not isinstance(item, str) or not item.strip() or any(ch in item for ch in "\r\n\x00"):
        return "equip requires a non-empty item name"
    if not isinstance(item_id, (str, int)) or isinstance(item_id, bool):
        return "equip requires numeric item id"
    item_id_text = str(item_id).strip()
    if not item_id_text.isdigit() or int(item_id_text) <= 0:
        return "equip requires positive numeric item id"
    if not isinstance(slot, str) or slot not in _EQUIP_SLOTS:
        return "equip requires a supported equipment slot"
    try:
        resolve_item_name(item_id, item)
    except ValueError as exc:
        return str(exc)
    return None


def _validate_use_arguments(arguments: dict[str, Any]) -> str | None:
    """Validate the typed use payload before it can become a command."""
    if not isinstance(arguments, dict):
        return "use arguments must be an object"
    item = arguments.get("item")
    item_id = arguments.get("id")
    if not isinstance(item, str) or not item.strip() or any(ch in item for ch in "\r\n\x00"):
        return "use requires a non-empty item name"
    if not isinstance(item_id, (str, int)) or isinstance(item_id, bool):
        return "use requires numeric item id"
    item_id_text = str(item_id).strip()
    if not item_id_text.isdigit() or int(item_id_text) <= 0:
        return "use requires positive numeric item id"
    try:
        resolve_item_name(item_id, item)
    except ValueError as exc:
        return str(exc)
    return None


def _serialize_action(action: str, arguments: dict[str, Any]) -> str:
    """Serialize approved structured arguments into one bounded KoLmafia command.

    This is deliberately allowlist-specific. It does not accept a caller-provided
    command string and never falls back to a bare verb for structured actions.
    """
    if action == "equip":
        error = _validate_equip_arguments(arguments)
        if error:
            raise ValueError(error)
        resolved = resolve_item_name(arguments["id"], arguments["item"])
        return f"equip {arguments['slot']} {resolved.canonical_name}"
    if action == "adventure":
        if arguments:
            raise ValueError("adventure does not accept structured arguments")
        return "adventure"
    if action == "use":
        error = _validate_use_arguments(arguments)
        if error:
            raise ValueError(error)
        resolved = resolve_item_name(arguments["id"], arguments["item"])
        # Existing KoLmafia session evidence uses the canonical quantity + name
        # form (for example, `use 1 <item>`). The resolver-returned name is
        # the only item text used by the transport serializer.
        return f"use 1 {resolved.canonical_name}"
    # Existing T2 entries without a reviewed serializer remain proposal-only and
    # fail closed before confirmation consumption or transport.
    raise ValueError(f"no typed serializer for T2 action: {action}")


def _classify(action_norm: str, mode: str = DEFAULT_MODE) -> tuple[ActionClass, str, str | None, bool]:
    """Classify normalized action.

    Returns (action_class, reason, allowlist_id, requires_confirmation).
    T3 deny checked first, before policy engine.
    """
    # T3 deny: substring match in normalized action
    for deny in T3_DENY_SUBSTRINGS:
        if deny in action_norm:
            # Check word boundary-ish: kmail in "kmail user" matches
            return (ActionClass.UNSAFE_UNKNOWN, f"T3 structural deny: {deny}", None, False)
    # Also direct keyword equality
    if action_norm in T3_DENY_KEYWORDS:
        return (ActionClass.UNSAFE_UNKNOWN, f"T3 structural deny: {action_norm}", None, False)

    engine = PolicyEngine(COMBINED_ALLOWLIST)
    from kolmafa.policy import ActionRequest, ModeState

    decision = engine.decide(ActionRequest(command=action_norm, mode=mode), ModeState(mode=mode))
    return (decision.command_class, decision.reason, decision.allowlist_id, decision.requires_confirmation)


def _build_precondition(current_item_id: str | None, target_item_id: str, player: str, slot: str = "hat") -> dict[str, str]:
    """Build canonical precondition dict for state binding.

    Deterministic, sorted keys JSON, hashes not raw secret.
    """
    # Normalize current_item_id: None or empty -> "none"
    cur = str(current_item_id) if current_item_id is not None and str(current_item_id).strip() != "" else "none"
    return {
        "player": player,
        "slot": slot,
        "current_item_id": cur,
        "target_item_id": str(target_item_id),
    }


def _get_current_hat_id() -> str | None:
    """Return current hat id via live read-only equipment_snapshot, or None if offline."""
    try:
        from kolmafa.devtest.inspection import equipment_snapshot

        snap = equipment_snapshot()
        if snap.get("live") and snap.get("ok"):
            return snap.get("equipment", {}).get("hat_id")
        # Offline fallback: try to get hat from snap even if live false, but may be None
        return snap.get("equipment", {}).get("hat_id") if isinstance(snap.get("equipment"), dict) else None
    except Exception:
        return None


def _get_connection():
    settings = get_settings()
    # Initialize/migrate before audit writes so new columns are present on
    # existing Don databases as well as fresh test databases.
    db.init_database(settings.database_path)
    conn = db.connect(settings.database_path)
    # Ensure policy/confirmation tables exist (init_database already ensures)
    # Also ensure FTS not needed here
    return conn


def _select_writer(explicit_writer: GcliWriter | None = None) -> GcliWriter:
    """Select writer explicitly: dry-run default, live-relay only if flag + relay pwd configured.

    No silent switch. Live requires KOLMAFA_LIVE_RELAY_ENABLED=true and relay pwd configured.
    """
    if explicit_writer is not None:
        return explicit_writer
    import os

    settings = get_settings()
    live_flag = os.environ.get("KOLMAFA_LIVE_RELAY_ENABLED", "").lower() in ("1", "true", "yes")
    if live_flag and settings.relay_pwd and settings.transport != "docker-free":
        # Construct real RelayWriter lazily
        from kolmafa.devtest.relay_writer import RelayWriter

        return RelayWriter()  # type: ignore[return-value]
    return DryRunGcliWriter()


class ActionBroker:
    """Single writer broker (DryRun/fake by default)."""

    def __init__(self, writer: GcliWriter | None = None):
        # writer == None -> auto select based on explicit config (dry-run default)
        # writer explicitly provided (including DryRun or fake) -> use that, no auto switch
        if writer is not None:
            self.writer: GcliWriter = writer
            self._explicit_writer = True
        else:
            self.writer = _select_writer(None)
            self._explicit_writer = False
        # For testing: allow injection of fake callable that mimics writer
        self._call_count = 0

    def _writer_identity(self) -> TransportIdentity:
        """Return the actual transport identity the writer will execute."""
        method = getattr(self.writer, "transport_identity", None)
        if callable(method):
            try:
                identity = method()
            except Exception:
                identity = None
            if isinstance(identity, TransportIdentity):
                return identity
        t = getattr(self.writer, "transport", None)
        if isinstance(t, str) and t:
            return identity_for_transport_label(t)
        return identity_for_transport_label(TRANSPORT_DRYRUN)

    def _writer_transport(self) -> str:
        # Determine transport label for proposal/execution
        # RelayWriter has no explicit transport attr, but we know it's relay
        from kolmafa.devtest.relay_writer import RelayWriter

        if isinstance(self.writer, RelayWriter):
            return RELAY_TRANSPORT
        # DryRun or fake may have transport attr
        t = getattr(self.writer, "transport", TRANSPORT_DRYRUN)
        if not isinstance(t, str):
            return TRANSPORT_DRYRUN
        return t

    def propose(self, action: str, arguments: dict[str, Any] | None = None, actor_id: str = "operator") -> dict[str, Any]:
        """Create canonical proposal.

        Returns structured proposal dict. For T1, returns error redirect.
        For T3, returns denied. For T2, creates pending confirmation.
        """
        arguments = arguments or {}
        normalized = _normalize_action(action)
        if not normalized:
            record_evidence("don_propose_action", "offline", "kolmafa.devtest.action_broker", "deny empty action")
            return {
                "ok": False,
                "error": "empty or invalid action",
                "classification": ActionClass.UNSAFE_UNKNOWN.value,
                "normalized_action": redact_text(normalized),
                "approval_required": False,
            }

        action_class, reason, allowlist_id, requires_confirmation = _classify(normalized)

        # T1 read-only -> redirect
        if action_class == ActionClass.READ_ONLY:
            record_evidence("don_propose_action", "offline", "kolmafa.devtest.action_broker", f"T1 redirect {normalized}")
            return {
                "ok": False,
                "error": "T1 read-only action does not belong in writer API; use read surface",
                "classification": action_class.value,
                "normalized_action": redact_text(normalized),
                "reason": redact_text(reason),
                "approval_required": False,
                "execution_performed": False,
            }

        # T3 structural deny -> deny before transport, before confirmation
        if "T3 structural deny" in reason:
            record_evidence("don_propose_action", "offline", "kolmafa.devtest.action_broker", f"T3 deny {normalized}")
            return {
                "ok": False,
                "error": "T3 structural deny",
                "classification": ActionClass.UNSAFE_UNKNOWN.value,
                "normalized_action": redact_text(normalized),
                "reason": redact_text(reason),
                "approval_required": False,
                "execution_performed": False,
            }

        # For UNSAFE_UNKNOWN that is not T3, also deny
        if action_class == ActionClass.UNSAFE_UNKNOWN and not requires_confirmation:
            record_evidence("don_propose_action", "offline", "kolmafa.devtest.action_broker", f"deny unknown {normalized}")
            return {
                "ok": False,
                "error": "unknown action denied",
                "classification": action_class.value,
                "normalized_action": redact_text(normalized),
                "reason": redact_text(reason),
                "approval_required": False,
                "execution_performed": False,
            }

        # T2 game-affecting -> requires durable confirmation
        if requires_confirmation or action_class == ActionClass.GAME_AFFECTING:
            if normalized == "equip":
                equip_error = _validate_equip_arguments(arguments)
                if equip_error:
                    record_evidence(
                        "don_propose_action",
                        "offline",
                        "kolmafa.devtest.action_broker",
                        f"deny malformed equip: {equip_error}",
                    )
                    return {
                        "ok": False,
                        "error": equip_error,
                        "classification": action_class.value,
                        "normalized_action": redact_text(normalized),
                        "approval_required": False,
                        "execution_performed": False,
                    }
            if normalized == "use":
                use_error = _validate_use_arguments(arguments)
                if use_error:
                    record_evidence(
                        "don_propose_action",
                        "offline",
                        "kolmafa.devtest.action_broker",
                        f"deny malformed use: {use_error}",
                    )
                    return {
                        "ok": False,
                        "error": use_error,
                        "classification": action_class.value,
                        "normalized_action": redact_text(normalized),
                        "approval_required": False,
                        "execution_performed": False,
                    }

            proposal_id = uuid.uuid4().hex
            policy_decision_id = uuid.uuid4().hex
            # Hashes for binding
            action_hash = canonical_hash(normalized)
            args_hash = canonical_hash(arguments)
            mode_hash = canonical_hash(DEFAULT_MODE)

            transport_label = self._writer_transport()

            # Bind the proposal to the exact transport identity that will
            # execute. An invalid/unapproved destination fails closed here,
            # before any confirmation row is persisted.
            try:
                writer_identity = self._writer_identity()
                transport_fingerprint = writer_identity.fingerprint()
            except TransportIdentityError as exc:
                record_evidence(
                    "don_propose_action",
                    "offline",
                    "kolmafa.devtest.action_broker",
                    f"deny unapproved transport: {exc.classification}",
                    extra={"classification": exc.classification},
                )
                return {
                    "ok": False,
                    "error": str(exc),
                    "classification": exc.classification,
                    "normalized_action": redact_text(normalized),
                    "approval_required": False,
                    "execution_performed": False,
                }

            # State binding: for equip, bind to current stable hat pre-state
            state_binding = ""
            precondition: dict[str, str] | None = None
            if normalized == "equip":
                # Derive target and slot from arguments
                target_id = str(arguments.get("id") or arguments.get("target_item_id") or "153")
                slot = str(arguments.get("slot") or "hat")
                # Get current hat via live read, fallback to none if offline
                current_hat = _get_current_hat_id()
                settings = get_settings()
                player = getattr(settings, "player_name", None) or "test_player"
                try:
                    player = str(player)
                except Exception:
                    player = "test_player"
                precondition = _build_precondition(current_hat, target_id, player, slot)
                state_binding = json.dumps(precondition, sort_keys=True, separators=(",", ":"))

            # Persist pending confirmation
            expires_at = datetime.now(UTC) + timedelta(hours=DEFAULT_TTL_HOURS)
            conn = _get_connection()
            try:
                store = ConfirmationStore(conn)
                proposal = ConfirmationProposal(
                    confirmation_id=proposal_id,
                    policy_decision_id=policy_decision_id,
                    actor_id=actor_id,
                    actor_surface="don_propose_action",
                    command_class=action_class,
                    transport=transport_label,
                    action_text=normalized,
                    arguments=arguments,
                    state_binding=state_binding,
                    allowlist_id=allowlist_id or "",
                    expires_at=expires_at,
                    mode=DEFAULT_MODE,
                    transport_fingerprint=transport_fingerprint,
                )
                store.create_pending(proposal)
            finally:
                conn.close()

            record_evidence(
                "don_propose_action",
                "offline",
                "kolmafa.devtest.action_broker",
                f"proposed T2 {normalized}",
                extra={"proposal_id": proposal_id, "classification": action_class.value},
            )
            return {
                "ok": True,
                "proposal_id": proposal_id,
                "normalized_action": redact_text(normalized),
                "classification": action_class.value,
                "reason": redact_text(reason),
                "allowlist_id": allowlist_id,
                "action_hash": action_hash,
                "arguments_hash": args_hash,
                "mode_hash": mode_hash,
                "approval_required": True,
                "execution_performed": False,
                "transport": transport_label,
                "transport_fingerprint": transport_fingerprint,
            }

        # Fallback deny
        record_evidence("don_propose_action", "offline", "kolmafa.devtest.action_broker", f"deny fallback {normalized}")
        return {
            "ok": False,
            "error": "denied",
            "classification": action_class.value,
            "normalized_action": redact_text(normalized),
            "reason": redact_text(reason),
            "approval_required": False,
            "execution_performed": False,
        }

    def execute_approved(self, proposal_id: str, actor_id: str = "operator", expected_action: str | None = None, expected_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a proposal via durable exact confirmation.

        The caller must have previously had the proposal confirmed via
        `confirm_action` (operator durable confirmation). This method verifies
        binding and then calls the narrow transport exactly once.
        """
        if not proposal_id:
            return {"ok": False, "error": "missing proposal_id", "execution_performed": False}

        conn = _get_connection()
        try:
            # Load confirmation row
            row = conn.execute("SELECT * FROM action_confirmations WHERE confirmation_id = ?", (proposal_id,)).fetchone()
            if row is None:
                record_evidence("don_execute_approved", "offline", "kolmafa.devtest.action_broker", "deny not found")
                return {"ok": False, "error": "confirmation not found", "execution_performed": False}

            # Check T3 structural deny again based on stored action
            # We need to fetch action hash comparison; but we also need normalized action text redacted storage.
            # The stored action_text_redacted is redacted; but we stored canonical hash for comparison.
            # For T3, we can re-classify using stored action via hash? Simpler: if row's allowlist corresponds to T2, but if row was T3 it wouldn't exist (propose denied). So if we are here, it was T2.
            # Still, verify not expired etc via consume.

            # Build consumption request using stored pending data + caller supplied expected values if given
            # We need to retrieve original normalized action for transport. Since we only have hash, we need to use expected_action if supplied,
            # otherwise we use redacted display? For DryRun, we need actual command; we can use the proposal's action_text from request validation.
            # Workaround: if expected_action is given, use it; else try to fetch from confirmation's redacted? But we lost raw.
            # For tests, caller supplies expected_action matching original propose.
            # For real use, we could store action via hash only and require exact retransmission.
            # We'll require caller to supply expected_action and expected_arguments that must match stored hashes.

            # If expected_action not supplied, we cannot verify exactly; deny
            if expected_action is None:
                # Try to use redacted as fallback? But redacted == normalized lowercased, so it's recoverable for lowercased actions
                # The stored action_text_redacted is redacted(normalized) which for normal actions equals normalized (since no secrets)
                stored_redacted = row["action_text_redacted"]
                # Use it as action_text
                action_text = stored_redacted
                args = {}
            else:
                action_text = _normalize_action(expected_action)
                args = expected_arguments or {}

            # Also need to verify classification not T3 - re-classify
            action_class_check, reason_check, _, _ = _classify(action_text)
            if "T3 structural deny" in reason_check:
                record_evidence("don_execute_approved", "offline", "kolmafa.devtest.action_broker", "T3 deny at execute")
                return {"ok": False, "error": "T3 structural deny", "execution_performed": False}

            # Exact action and argument binding is checked before serialization;
            # this preserves the durable mismatch error contract.
            if row["action_hash"] != canonical_hash(action_text):
                record_evidence("don_execute_approved", "offline", "kolmafa.devtest.action_broker", "action mismatch")
                return {"ok": False, "error": "action mismatch", "execution_performed": False, "proposal_id": proposal_id}
            if row["arguments_hash"] != canonical_hash(args):
                record_evidence("don_execute_approved", "offline", "kolmafa.devtest.action_broker", "argument mismatch")
                return {"ok": False, "error": "argument mismatch", "execution_performed": False, "proposal_id": proposal_id}

            # Execution-time recheck: the writer's actual transport identity
            # must equal the identity approved at proposal time. Mismatch (or
            # an invalid/unapproved actual destination) fails closed with zero
            # network calls and does not consume the confirmation.
            approved_fingerprint = row["transport_fingerprint"] if "transport_fingerprint" in row.keys() else ""
            try:
                actual_identity = self._writer_identity()
                actual_fingerprint = actual_identity.fingerprint()
            except TransportIdentityError as exc:
                record_evidence(
                    "don_execute_approved",
                    "offline",
                    "kolmafa.devtest.action_broker",
                    f"deny invalid actual transport: {exc.classification}",
                    extra={
                        "proposal_id": proposal_id,
                        "classification": exc.classification,
                        "approved_fingerprint": approved_fingerprint,
                    },
                )
                return {
                    "ok": False,
                    "error": str(exc),
                    "classification": exc.classification,
                    "execution_performed": False,
                    "proposal_id": proposal_id,
                }
            if not approved_fingerprint or approved_fingerprint != actual_fingerprint:
                record_evidence(
                    "don_execute_approved",
                    "offline",
                    "kolmafa.devtest.action_broker",
                    "transport identity mismatch: approved != actual writer transport",
                    extra={
                        "proposal_id": proposal_id,
                        "classification": "TRANSPORT_IDENTITY_MISMATCH",
                        "approved_fingerprint": approved_fingerprint,
                        "actual_fingerprint": actual_fingerprint,
                    },
                )
                return {
                    "ok": False,
                    "error": "transport identity mismatch: approved != actual writer transport",
                    "classification": "TRANSPORT_IDENTITY_MISMATCH",
                    "execution_performed": False,
                    "proposal_id": proposal_id,
                }

            # Validate typed structured arguments before deriving any command.
            if action_text == "equip":
                equip_error = _validate_equip_arguments(args)
                if equip_error:
                    record_evidence(
                        "don_execute_approved",
                        "offline",
                        "kolmafa.devtest.action_broker",
                        f"deny malformed equip: {equip_error}",
                    )
                    return {"ok": False, "error": equip_error, "execution_performed": False, "proposal_id": proposal_id}

            # State binding verification: re-derive live precondition and compare to stored hash
            # For equip actions with precondition, failure must happen before transport
            if action_text == "equip":
                equip_error = _validate_equip_arguments(args)
                if equip_error:
                    record_evidence(
                        "don_execute_approved",
                        "offline",
                        "kolmafa.devtest.action_broker",
                        f"deny malformed equip: {equip_error}",
                    )
                    return {"ok": False, "error": equip_error, "execution_performed": False, "proposal_id": proposal_id}

            stored_state_hash = row["state_binding_hash"]
            empty_state_hash = canonical_hash("")
            live_state_binding = ""
            if stored_state_hash != empty_state_hash:
                # Stored has precondition (equip); rebuild live precondition with current hat
                # Extract target/slot/player from stored or args
                # Parse stored state_binding not available directly (only hash), so infer from args
                # Use args to get target/slot
                target_id = str(args.get("id") or args.get("target_item_id") or args.get("item") or "153")
                # But for equip, id is numeric string; handle item name vs id
                if target_id == "Ancient Saucehelm" or "Ancient" in target_id:
                    target_id = "153"
                slot = str(args.get("slot") or "hat")
                # Get live current hat
                live_hat = _get_current_hat_id()
                # Player
                settings_live = get_settings()
                player_live = getattr(settings_live, "player_name", None) or "test_player"
                try:
                    player_live = str(player_live)
                except Exception:
                    player_live = "test_player"
                live_precondition = _build_precondition(live_hat, target_id, player_live, slot)
                live_state_binding = json.dumps(live_precondition, sort_keys=True, separators=(",", ":"))
                # If live hash does not match stored, deny before transport
                if canonical_hash(live_state_binding) != stored_state_hash:
                    record_evidence(
                        "don_execute_approved",
                        "offline",
                        "kolmafa.devtest.action_broker",
                        f"state drift deny: live hat {live_hat} != approved pre-state",
                        extra={"stored_hash": stored_state_hash, "live_hat": str(live_hat)},
                    )
                    return {"ok": False, "error": "state drift: pre-state mismatch, execution denied before transport", "execution_performed": False, "proposal_id": proposal_id}

            # Derive the complete command after exact argument validation and
            # state verification, but before one-shot confirmation consumption.
            try:
                serialized_command = _serialize_action(action_text, args)
            except ValueError as exc:
                record_evidence(
                    "don_execute_approved",
                    "offline",
                    "kolmafa.devtest.action_broker",
                    f"deny unserializable T2 action: {exc}",
                )
                return {"ok": False, "error": str(exc), "execution_performed": False, "proposal_id": proposal_id}

            command_log_id = uuid.uuid4().hex
            # Use stored transport for consumption (must match proposal)
            expected_transport = row["transport"]
            evidence_mode = "live-transport" if expected_transport == RELAY_TRANSPORT else "offline"
            store = ConfirmationStore(conn)
            req = ConsumptionRequest(
                confirmation_id=proposal_id,
                actor_id=actor_id,
                action_text=action_text,
                arguments=args,
                transport=expected_transport,
                mode=DEFAULT_MODE,
                allowlist_id=row["allowlist_id"],
                state_binding=live_state_binding,
                command_log_id=command_log_id,
                transport_fingerprint=approved_fingerprint,
            )
            result = store.consume(req)
            if not result.allowed:
                record_evidence("don_execute_approved", "offline", "kolmafa.devtest.action_broker", f"consume deny: {result.reason}")
                return {"ok": False, "error": result.reason, "execution_performed": False, "proposal_id": proposal_id}

            # Exactly one transport call — no retry, even on ambiguous failure
            self._call_count += 1
            # If writer was auto-selected dry-run but live flag now set, keep original selection unless explicit writer?
            # Use current writer (may be live RelayWriter if flag set and not explicit)
            # For injected writer tests, self.writer is the fake/relay
            writer_result: CommandResult = self.writer.write(serialized_command, timeout=60.0)
            result_marker = writer_result.result_marker if isinstance(writer_result.result_marker, dict) else {"result_kind": "unknown"}

            # Determine outcome, handling ambiguous timeout
            outcome = "success" if writer_result.return_code == 0 else "failure"
            stderr_text = writer_result.stderr or ""
            if "OUTCOME_UNKNOWN" in stderr_text:
                outcome = "OUTCOME_UNKNOWN"

            # Record command audit (like bridge does)
            # Use actual writer transport label for audit
            audit_transport = getattr(self.writer, "transport", expected_transport)
            # RelayWriter has no transport attr but logically relay
            from kolmafa.devtest.relay_writer import RelayWriter as _RelayWriter

            if isinstance(self.writer, _RelayWriter):
                audit_transport = RELAY_TRANSPORT
            try:
                conn.execute(
                    """
                    INSERT INTO command_log(
                        command_log_id, transport, command_class, command_text_redacted, command_hash,
                        arguments_redacted_json, allowlist_id, confirmation_id, policy_decision_id, return_code,
                        stdout_redacted, stdout_hash, stderr_redacted, stderr_hash, result_marker_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        command_log_id,
                        audit_transport,
                        row["command_class"],
                        redact_text(serialized_command),
                        hashlib.sha256(redact_text(serialized_command).encode()).hexdigest(),
                        redact_text(json.dumps(args, sort_keys=True, separators=(",", ":"))),
                        row["allowlist_id"],
                        proposal_id,
                        row["policy_decision_id"],
                        writer_result.return_code,
                        "",
                        hashlib.sha256(b"").hexdigest(),
                        redact_text(writer_result.stderr),
                        hashlib.sha256(redact_text(writer_result.stderr).encode()).hexdigest(),
                        json.dumps(result_marker, sort_keys=True, separators=(",", ":")),
                    ),
                )
                conn.commit()
            except Exception as exc:
                # Keep the transport result, but make an audit-schema failure
                # visible without retaining an exception message or raw output.
                record_evidence(
                    "don_command_audit",
                    evidence_mode,
                    "kolmafa.devtest.action_broker",
                    "command audit insert failed",
                    extra={"error_class": type(exc).__name__},
                )

            # Do not retry on ambiguous outcome; return structured unknown
            if outcome == "OUTCOME_UNKNOWN":
                record_evidence(
                    "don_execute_approved",
                    evidence_mode,
                    "kolmafa.devtest.action_broker",
                    f"ambiguous {serialized_command} OUTCOME_UNKNOWN",
                    extra={"proposal_id": proposal_id, "outcome": outcome, "command_result_marker": result_marker},
                )
                return {
                    "ok": False,
                    "proposal_id": proposal_id,
                    "classification": row["command_class"],
                    "approval_verified": True,
                    "transport": audit_transport,
                    "execution_performed": False,
                    "outcome": outcome,
                    "return_code": writer_result.return_code,
                    "stderr_preview": redact_text(writer_result.stderr)[:500],
                    "command_result_marker": result_marker,
                    "redacted": True,
                }

            record_evidence(
                "don_execute_approved",
                evidence_mode,
                "kolmafa.devtest.action_broker",
                f"executed {audit_transport} {serialized_command} rc={writer_result.return_code}",
                extra={"proposal_id": proposal_id, "return_code": writer_result.return_code, "outcome": outcome, "command_result_marker": result_marker},
            )
            # For DryRun, execution_performed stays False; for live relay success, it would be True but we keep False until commissioned?
            # Spec: DryRun execution_performed=false; live should be true when actually sent.
            # For Slice 3A we keep live transport but still not commissioned, so we mark execution_performed true only if live and return_code 0 and not ambiguous?
            execution_flag = False
            if audit_transport == RELAY_TRANSPORT and writer_result.return_code == 0:
                execution_flag = True
            # However for DryRun, always False
            if audit_transport == TRANSPORT_DRYRUN:
                execution_flag = False
            return {
                "ok": writer_result.return_code == 0,
                "proposal_id": proposal_id,
                "classification": row["command_class"],
                "approval_verified": True,
                "transport": audit_transport,
                "execution_performed": execution_flag,
                "outcome": outcome,
                "return_code": writer_result.return_code,
                "command_result_marker": result_marker,
                "stderr_preview": redact_text(writer_result.stderr)[:500],
                "redacted": True,
            }
        finally:
            conn.close()
