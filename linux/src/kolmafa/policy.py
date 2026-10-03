"""Fail-closed action classification and policy decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ActionClass(StrEnum):
    """Safety class for a proposed action."""

    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    GAME_AFFECTING = "game_affecting"
    UNSAFE_UNKNOWN = "unsafe_unknown"


@dataclass(frozen=True, slots=True)
class AllowlistEntry:
    """Reviewed allowlist entry for exactly one command and mode."""

    allowlist_id: str
    command: str
    mode: str
    action_class: ActionClass
    rollback_note: str | None = None


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """A proposed action to evaluate without executing it."""

    command: str
    mode: str
    arguments: dict[str, object] = field(default_factory=dict)
    advisory_sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModeState:
    """Current safety-relevant mode state."""

    mode: str
    state_binding: str = ""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Policy decision for a proposed action."""

    allowed: bool
    command_class: ActionClass
    reason: str
    allowlist_id: str | None = None
    requires_confirmation: bool = False


class PolicyEngine:
    """Static allowlist policy engine; advisory data never grants permission."""

    def __init__(self, allowlist: list[AllowlistEntry]) -> None:
        self._allowlist = list(allowlist)

    def decide(self, request: ActionRequest, mode_state: ModeState) -> PolicyDecision:
        """Evaluate a request and fail closed for unknown or mismatched inputs."""

        entries = [
            entry
            for entry in self._allowlist
            if entry.command == request.command and entry.mode == request.mode
        ]

        if len(entries) != 1:
            command_class = self._classify_without_authority(request.command)
            return PolicyDecision(False, command_class, "no unique reviewed allowlist entry")

        entry = entries[0]
        if request.mode != mode_state.mode:
            return PolicyDecision(False, entry.action_class, "request mode does not match current mode")

        if entry.action_class is ActionClass.READ_ONLY:
            return PolicyDecision(True, entry.action_class, "read-only allowlisted", entry.allowlist_id)

        if entry.action_class is ActionClass.REVERSIBLE:
            if not entry.rollback_note:
                return PolicyDecision(False, entry.action_class, "reversible action lacks rollback note", entry.allowlist_id)
            return PolicyDecision(True, entry.action_class, "reversible allowlisted", entry.allowlist_id)

        if entry.action_class is ActionClass.GAME_AFFECTING:
            return PolicyDecision(
                False,
                entry.action_class,
                "game-affecting action requires durable exact confirmation",
                entry.allowlist_id,
                requires_confirmation=True,
            )

        return PolicyDecision(False, ActionClass.UNSAFE_UNKNOWN, "unsafe or unknown action denied")

    def _classify_without_authority(self, command: str) -> ActionClass:
        normalized = command.strip().lower()
        if normalized in {"status", "inventory", "session-log"}:
            return ActionClass.READ_ONLY
        if normalized in {"draft-note", "draft-plan"}:
            return ActionClass.REVERSIBLE
        if normalized in {"adventure", "buy", "sell", "use", "craft", "pvp", "trade", "clan", "equip"}:
            return ActionClass.GAME_AFFECTING
        return ActionClass.UNSAFE_UNKNOWN
