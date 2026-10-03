"""Offline response resolver for adversarial-envelope packets.

The resolver is intentionally presentation-oriented. It does not derive or emit
execution eligibility; that field is owned exclusively by
``eligibility.compute_execution_eligibility``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def resolve_response(input_fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve offline response presentation state without derived gate outputs.

    Args:
        input_fixture: Contract-shaped packet or introspection fixture.

    Returns:
        A small deterministic resolution mapping. Introspection fixtures return
        explicit attestations for forbidden inputs/outputs.
    """

    forbidden_inputs = input_fixture.get("signature_forbidden_inputs")
    if isinstance(forbidden_inputs, list) and "proposal_supported" in forbidden_inputs:
        return {"accepted_input_contract": "excludes_proposal_supported"}

    forbidden_outputs = input_fixture.get("signature_forbidden_outputs")
    if isinstance(forbidden_outputs, list) and "execution_eligibility" in forbidden_outputs:
        return {"no_execution_eligibility_output": True}

    final_answer_status = input_fixture.get("final_answer_status")
    proposal_support = input_fixture.get("proposal_support")
    answer_support = input_fixture.get("answer_support")
    if final_answer_status == "supported":
        return _resolution("presentable", "answer", "Offline answer is available.")
    if proposal_support == "needs_clarification":
        return _resolution("needs_clarification", "clarify", "Clarification is required before proceeding.")
    if proposal_support == "withheld":
        return _resolution("withheld", "explain_withholding", "Response is withheld for safety.")
    if proposal_support == "not_applicable" and answer_support == "not_applicable":
        return {"response_resolution": "not_applicable", "recommended_response": "abstain"}

    lifecycle = input_fixture.get("proposal_lifecycle")
    confirmation_status = input_fixture.get("confirmation_status")
    if lifecycle == "ready_for_presentation" and confirmation_status in {None, "not_requested"}:
        return {"response_resolution": "presentable"}

    if lifecycle == "presented":
        return {"response_resolution": "presented"}

    return {"response_resolution": "withheld"}


def _resolution(status: str, recommended_response: str, friendly_response: str) -> dict[str, Any]:
    return {
        "response_resolution": status,
        "recommended_response": recommended_response,
        "friendly_response": friendly_response,
    }


__all__ = ["resolve_response"]
