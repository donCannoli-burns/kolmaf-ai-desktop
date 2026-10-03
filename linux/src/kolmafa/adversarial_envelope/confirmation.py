"""Pure offline confirmation validation for adversarial envelopes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def validate_confirmation(input_fixture: Mapping[str, Any]) -> dict[str, str]:
    """Validate confirmation binding, scope, and lifecycle invalidation.

    Confirmation requires an existing presentation and exact binding to the
    presented proposal/part payload. Expiry, supersession, state drift, and
    payload drift invalidate otherwise-confirmed records.
    """

    confirmation = _mapping(input_fixture.get("confirmation"))
    presentation = _mapping(input_fixture.get("presentation"))

    if input_fixture.get("proposal_lifecycle") in {"expired", "superseded"}:
        return {"confirmation_validity": "invalidated"}

    scope_result = _validate_exact_part_scope(input_fixture, confirmation)
    if scope_result is not None:
        return scope_result

    if confirmation.get("status") != "confirmed":
        return {"confirmation_validity": "not_obtained"}

    if presentation.get("status") != "presented":
        return {"confirmation_validity": "invalid", "reason": "confirmation_requires_presentation"}

    presented_proposal_id = presentation.get("presented_proposal_id")
    confirmation_proposal_id = confirmation.get("proposal_id")
    if (
        presented_proposal_id is not None
        and confirmation_proposal_id is not None
        and presented_proposal_id != confirmation_proposal_id
    ):
        return {"confirmation_validity": "invalid", "reason": "proposal_id_mismatch"}

    if _both_present_and_different(
        presentation.get("presented_payload_hash"),
        confirmation.get("payload_hash"),
    ):
        return {"confirmation_validity": "invalid", "reason": "payload_hash_mismatch"}

    if _both_present_and_different(
        presentation.get("presented_state_hash"),
        confirmation.get("state_or_precondition_hash"),
    ):
        return {"confirmation_validity": "invalid", "reason": "state_hash_mismatch"}

    validity = confirmation.get("validity")
    if validity in {"invalid", "invalidated"}:
        return {"confirmation_validity": str(validity)}

    return {"confirmation_validity": "valid"}


def _validate_exact_part_scope(
    input_fixture: Mapping[str, Any],
    confirmation: Mapping[str, Any],
) -> dict[str, str] | None:
    if confirmation.get("scope") != "exact_part":
        return None

    target_part_id = confirmation.get("target_part_id")
    if not isinstance(target_part_id, str) or not target_part_id:
        return {"confirmation_validity": "invalid", "reason": "missing_or_invalid_target_part_id"}

    relevant_part_id = input_fixture.get("relevant_part_id")
    if isinstance(relevant_part_id, str) and target_part_id != relevant_part_id:
        return {"confirmation_validity": "invalid", "reason": "wrong_part_id"}

    request_parts = input_fixture.get("request_parts")
    if isinstance(request_parts, Sequence) and not isinstance(request_parts, (str, bytes)):
        parts = [_mapping(part) for part in request_parts]
        matching_parts = [part for part in parts if part.get("part_id") == target_part_id]
        if not matching_parts:
            return {"confirmation_validity": "invalid", "reason": "missing_or_invalid_target_part_id"}
        if matching_parts[0].get("part_type") == "informational":
            return {"confirmation_validity": "invalid", "reason": "informational_child_not_confirmable"}

    return None



def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _both_present_and_different(left: Any, right: Any) -> bool:
    return left is not None and right is not None and left != right
