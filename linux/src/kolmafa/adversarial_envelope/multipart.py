"""Offline multipart aggregation for adversarial-envelope child resolutions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_ACTION_PART_TYPES: frozenset[str] = frozenset({"action", "mixed"})


def aggregate_child_resolutions(input_fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate child part outcomes without granting parent execution.

    Informational answers may remain available when an action child is withheld,
    but parent approval is blocked by any withheld action child.
    """

    children = input_fixture.get("children")
    if not isinstance(children, Sequence) or isinstance(children, (str, bytes, bytearray)):
        return {"overall_status": "empty", "response_available": False}

    has_supported_information = False
    has_action_child = False
    has_withheld_action = False
    all_actions_eligible = True

    for child in children:
        if not isinstance(child, Mapping):
            continue

        part_type = child.get("part_type")
        if part_type == "informational" and child.get("answer_support") == "supported":
            has_supported_information = True

        if part_type in _ACTION_PART_TYPES:
            has_action_child = True
            eligibility = child.get("execution_eligibility")
            if eligibility == "withheld":
                has_withheld_action = True
            if eligibility != "eligible":
                all_actions_eligible = False

    if has_withheld_action and has_supported_information:
        result: dict[str, Any] = {"overall_status": "partial", "response_available": True}
        if input_fixture.get("preserve_children") is True:
            result["children"] = list(children)
        return result

    if has_withheld_action:
        return {"overall_status": "blocked", "response_available": False}

    if has_action_child and all_actions_eligible:
        return {"overall_status": "approved", "response_available": True}

    if has_supported_information:
        return {"overall_status": "answerable", "response_available": True}

    return {"overall_status": "blocked", "response_available": False}


def validate_child_confirmation_independence(input_fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Ensure parent confirmation does not mutate child action state."""

    child = input_fixture.get("child")
    if not isinstance(child, Mapping):
        return {"child_proposal_lifecycle": None, "child_execution_eligibility": None}

    return {
        "child_proposal_lifecycle": child.get("proposal_lifecycle"),
        "child_execution_eligibility": child.get("execution_eligibility"),
    }


__all__ = ["aggregate_child_resolutions", "validate_child_confirmation_independence"]
