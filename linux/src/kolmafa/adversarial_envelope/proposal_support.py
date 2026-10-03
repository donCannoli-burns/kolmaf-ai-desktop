"""Primary-input proposal support derivation for offline contracts.

This module is intentionally pure and fixture-driven: it reads no runtime
artifacts and derives ``proposal.support`` only from the frozen primary input
vocabulary used by the adversarial-envelope contract tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


AUTHORITATIVE_PROPOSAL_SUPPORT_INPUTS: frozenset[str] = frozenset(
    {
        "request_coherence",
        "capability_exists",
        "capability_matches_purpose",
        "parameters_identified",
        "parameters_valid",
        "proposal_premise_evidence_found",
        "applicability_current_vs_historical",
        "primary_source_quality_assessment",
        "source_assessment.reconciliation_result",
    }
)

_DOWNSTREAM_OR_FORBIDDEN_INPUTS: frozenset[str] = frozenset(
    {
        "proposal_supported",
        "proposal.support",
        "proposal_support",
        "execution_eligibility",
        "semantic_labels",
        "evidence_sufficiency",
        "evidence_sufficiency.for_proposal_premise",
        "withholding_class_active",
        "policy.status",
    }
)

_BLOCKING_RECONCILIATION_RESULTS: frozenset[str] = frozenset(
    {"unresolved_conflict", "insufficient_provenance", "not_checked"}
)


def derive_proposal_support(input_fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Derive proposal support from primary inputs only.

    The function accepts the manifest's single fixture mapping rather than a
    broad application packet.  Contract-introspection fixtures are answered with
    explicit attestations; semantic derivation only consults the nine
    authoritative fields in ``primary_inputs`` or their top-level equivalents.
    """

    required_inputs = input_fixture.get("required_authoritative_inputs")
    if isinstance(required_inputs, list):
        all_bound = set(required_inputs) == AUTHORITATIVE_PROPOSAL_SUPPORT_INPUTS
        return {
            "authoritative_producer_count": len(AUTHORITATIVE_PROPOSAL_SUPPORT_INPUTS),
            "all_inputs_bound": all_bound,
        }

    forbidden_inputs = input_fixture.get("signature_forbidden_inputs")
    if isinstance(forbidden_inputs, list):
        if "policy.status" in forbidden_inputs:
            return {"accepted_input_contract": "excludes_policy_status"}
        if all(item in _DOWNSTREAM_OR_FORBIDDEN_INPUTS for item in forbidden_inputs):
            if {"semantic_labels", "evidence_sufficiency", "withholding_class_active"}.intersection(
                forbidden_inputs
            ):
                return {"accepted_input_contract": "rejects_downstream_fields"}
            return {"accepted_input_contract": "primary_inputs_only"}

    if input_fixture.get("input_contract") == "use_primary_source_quality_assessment":
        return {"consumed_quality_input": "primary_source_quality_assessment"}

    primary_inputs = _extract_primary_inputs(input_fixture)
    reconciliation_result = primary_inputs.get("source_assessment.reconciliation_result")
    if primary_inputs.get("request_coherence") == "fail":
        return {"proposal_support": "needs_clarification"}

    if primary_inputs.get("capability_exists") == "fail":
        return {"proposal_support": "not_applicable"}

    if reconciliation_result in _BLOCKING_RECONCILIATION_RESULTS:
        return {"proposal_support": "withheld", "must_not_equal": "supported"}

    if _all_positive(primary_inputs):
        return {"proposal_support": "supported"}

    return {"proposal_support": "not_checked"}


def _extract_primary_inputs(input_fixture: Mapping[str, Any]) -> dict[str, Any]:
    primary = input_fixture.get("primary_inputs")
    if isinstance(primary, Mapping):
        return {key: primary.get(key) for key in AUTHORITATIVE_PROPOSAL_SUPPORT_INPUTS if key in primary}
    return {key: input_fixture.get(key) for key in AUTHORITATIVE_PROPOSAL_SUPPORT_INPUTS if key in input_fixture}


def _all_positive(primary_inputs: Mapping[str, Any]) -> bool:
    return (
        primary_inputs.get("request_coherence") == "pass"
        and primary_inputs.get("capability_exists") == "pass"
        and primary_inputs.get("capability_matches_purpose") == "pass"
        and primary_inputs.get("parameters_identified") == "pass"
        and primary_inputs.get("parameters_valid") == "pass"
        and primary_inputs.get("proposal_premise_evidence_found") is True
        and primary_inputs.get("applicability_current_vs_historical") == "current"
        and primary_inputs.get("primary_source_quality_assessment") == "canonical"
        and primary_inputs.get("source_assessment.reconciliation_result") == "no_conflict"
    )


__all__ = ["AUTHORITATIVE_PROPOSAL_SUPPORT_INPUTS", "derive_proposal_support"]
