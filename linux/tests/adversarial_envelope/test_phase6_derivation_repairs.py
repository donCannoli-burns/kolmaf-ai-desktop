"""Targeted Phase 6 derivation regressions for adversarial-envelope repairs."""

from __future__ import annotations

import pytest

from kolmafa.adversarial_envelope.eligibility import compute_execution_eligibility
from kolmafa.adversarial_envelope.multipart import aggregate_child_resolutions
from kolmafa.adversarial_envelope.proposal_support import derive_proposal_support
from kolmafa.adversarial_envelope.resolver import resolve_response


def _primary(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "request_coherence": "pass",
        "capability_exists": "pass",
        "capability_matches_purpose": "pass",
        "parameters_identified": "pass",
        "parameters_valid": "pass",
        "proposal_premise_evidence_found": True,
        "applicability_current_vs_historical": "current",
        "primary_source_quality_assessment": "canonical",
        "source_assessment.reconciliation_result": "no_conflict",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "supported"),
        ({"capability_exists": "fail", "primary_source_quality_assessment": "canonical"}, "not_applicable"),
        ({"request_coherence": "fail"}, "needs_clarification"),
        ({"source_assessment.reconciliation_result": "insufficient_provenance"}, "withheld"),
    ],
)
def test_proposal_support_covers_supported_neutral_clarify_and_withheld(
    overrides: dict[str, object], expected: str
) -> None:
    result = derive_proposal_support({"primary_inputs": _primary(**overrides)})

    assert result["proposal_support"] == expected


@pytest.mark.parametrize(
    "cause",
    ["policy_denied", "unsafe_action", "insufficient_provenance"],
)
def test_safety_causes_withhold_without_eligibility_positive(cause: str) -> None:
    result = compute_execution_eligibility(
        {
            "proposal_support": "withheld",
            "safety_causes": [cause],
            "confirmation_validity": "valid",
            "policy_gate": "permitted",
            "runtime_gate": "ready",
            "transport_gate": "ready",
        }
    )

    assert result["execution_eligibility"] == "withheld"
    assert result["eligible"] is False
    assert result["blocking_gate"] == "safety"


def test_not_applicable_proposal_remains_neutral_for_eligibility() -> None:
    result = compute_execution_eligibility(
        {
            "proposal_support": "not_applicable",
            "confirmation_validity": "valid",
            "policy_gate": "permitted",
            "runtime_gate": "ready",
            "transport_gate": "ready",
        }
    )

    assert result == {"execution_eligibility": "not_applicable", "eligible": False}


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ({"final_answer_status": "supported"}, ("answer", True, "presentable")),
        ({"proposal_support": "needs_clarification"}, ("clarify", True, "needs_clarification")),
        ({"proposal_support": "withheld"}, ("explain_withholding", True, "withheld")),
        ({"proposal_support": "not_applicable", "answer_support": "not_applicable"}, ("abstain", False, "not_applicable")),
    ],
)
def test_resolver_returns_status_friendly_text_and_recommended_response_classes(
    fixture: dict[str, object], expected: tuple[str, bool, str]
) -> None:
    result = resolve_response(fixture)

    assert result["recommended_response"] == expected[0]
    assert bool(result.get("friendly_response")) is expected[1]
    assert result["response_resolution"] == expected[2]


def test_multipart_preserves_children_and_aggregates_parent_response_availability() -> None:
    children = [
        {"part_id": "info", "part_type": "informational", "answer_support": "supported"},
        {"part_id": "action", "part_type": "action", "execution_eligibility": "withheld"},
    ]

    result = aggregate_child_resolutions({"children": children, "preserve_children": True})

    assert result["children"] == children
    assert result["overall_status"] == "partial"
    assert result["response_available"] is True
