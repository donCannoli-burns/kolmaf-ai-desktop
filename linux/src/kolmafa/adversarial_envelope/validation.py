"""Offline validation for serialized adversarial-envelope packets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from kolmafa.adversarial_envelope.eligibility import compute_execution_eligibility


_ACTIONABLE_PART_TYPES: frozenset[str] = frozenset({"action", "mixed"})
_ACTIONABLE_LIFECYCLES_REQUIRING_PRESENTATION: frozenset[str] = frozenset(
    {"presented", "awaiting_confirmation", "confirmed"}
)


def validate_packet(input_fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Validate derived fields and child-action presentation invariants.

    The function is pure and uses only the packet supplied by the caller. It
    does not read test, documentation, schema, or dataset artifacts.
    """

    packet = input_fixture.get("packet")
    if not isinstance(packet, Mapping):
        return {"valid": False, "error": "missing_packet"}

    serialized_eligibility = packet.get("execution_eligibility")
    gates = packet.get("gates")
    if serialized_eligibility is not None and isinstance(gates, Mapping):
        recomputed = compute_execution_eligibility(gates).get("execution_eligibility")
        if recomputed != serialized_eligibility:
            return {"valid": False, "error": "serialized_execution_eligibility_mismatch"}

    parts = packet.get("parts")
    if isinstance(parts, Sequence) and not isinstance(parts, (str, bytes, bytearray)):
        for part in parts:
            if _actionable_child_requires_presentation(part):
                return {"valid": False, "error": "actionable_child_requires_presentation"}

    return {"valid": True}


def _actionable_child_requires_presentation(part: Any) -> bool:
    if not isinstance(part, Mapping):
        return False

    if part.get("part_type") not in _ACTIONABLE_PART_TYPES:
        return False

    if part.get("proposal_lifecycle") not in _ACTIONABLE_LIFECYCLES_REQUIRING_PRESENTATION:
        return False

    presentation = part.get("presentation")
    if not isinstance(presentation, Mapping):
        return True
    return presentation.get("status") != "presented"


__all__ = ["validate_packet"]
