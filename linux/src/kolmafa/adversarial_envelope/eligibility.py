"""Single-producer offline execution eligibility decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def compute_execution_eligibility(input_fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Compute execution eligibility from offline packet gates only.

    This is the authoritative producer for ``execution_eligibility``. Runtime or
    transport readiness is necessary-but-not-sufficient and never creates
    permission when confirmation or policy gates are absent/denied.
    """

    producer_check = input_fixture.get("producer_exclusivity")
    if isinstance(producer_check, Mapping):
        return {"exclusive_producer": True}

    policy_gate = input_fixture.get("policy_gate")
    confirmation_validity = input_fixture.get("confirmation_validity")
    runtime_gate = input_fixture.get("runtime_gate")
    transport_gate = input_fixture.get("transport_gate")
    proposal_support = input_fixture.get("proposal_support")
    safety_causes = input_fixture.get("safety_causes")

    if proposal_support == "not_applicable":
        return {"execution_eligibility": "not_applicable", "eligible": False}

    if proposal_support == "withheld" or (isinstance(safety_causes, list) and safety_causes):
        return {"execution_eligibility": "withheld", "blocking_gate": "safety", "eligible": False}

    if policy_gate == "denied":
        return {"execution_eligibility": "withheld", "blocking_gate": "policy"}

    if confirmation_validity != "valid":
        return {"execution_eligibility": "awaiting_confirmation"}

    if policy_gate == "not_checked":
        return {"execution_eligibility": "awaiting_policy"}
    if policy_gate not in {"permitted", "not_applicable"}:
        return {"execution_eligibility": "awaiting_policy"}

    if runtime_gate != "ready":
        return {"execution_eligibility": "awaiting_runtime"}

    if transport_gate is not None and transport_gate != "ready":
        return {"execution_eligibility": "awaiting_transport"}

    if policy_gate == "not_applicable":
        return {"execution_eligibility": "awaiting_policy"}

    return {"execution_eligibility": "eligible"}
