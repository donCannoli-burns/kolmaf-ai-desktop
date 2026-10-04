"""Dataset-facing packet projection contracts (portable, repository-contained).

Portable semantic contract only: synthetic cases under
tests/fixtures/adversarial_envelope/ exercise projection semantics without the
intentionally non-public historical artifacts. Exact historical alignment
verification lives in test_dataset_projection_historical.py (local_artifact).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kolmafa.adversarial_envelope.dataset_projection import project_dataset_packet


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "adversarial_envelope"

# Independently specified standard malformed-request clarification prompt.
# Matches the projection contract constant; asserted here as a fixed expectation.
EXPECTED_MALFORMED_CLARIFICATION_PROMPT = "Please clarify the in-scope KoL or ASH request."


def _synthetic_cases() -> dict[str, dict[str, object]]:
    data = json.loads((FIXTURES_DIR / "projection_cases.json").read_text(encoding="utf-8"))
    return data["cases"]  # type: ignore[no-any-return]


def _expected_packets() -> dict[str, dict[str, object]]:
    data = json.loads((FIXTURES_DIR / "projection_expected.json").read_text(encoding="utf-8"))
    return data["expected_packets"]  # type: ignore[no-any-return]


def _case(**overrides: object) -> dict[str, object]:
    case: dict[str, object] = {
        "id": "A999",
        "question": "What does take_shop mean in ASH reference material?",
        "split": "dev",
        "action_class": "informational",
        "adversarial": False,
        "semantic_labels": [],
        "capability_labels": ["ash_reference"],
        "expected_response": "answer",
        "expected_eligibility": "not_applicable",
        "friendly_response": "This request is supported by canonical information.",
        "highest_quality": "canonical",
        "source_case_ids": ["SRC-1"],
        "source_quality_classes": ["canonical"],
        "notes": "reference-purpose question",
        "adjudication_evidence": {
            "schema_version": "adversarial-envelope-schema-v2.0.0-preprototype",
            "schema_commit": "e0e700dd76e385ca41c0a79bbbc908c91f325151",
            "reviewed_at": "2026-07-17T00:00:00Z",
            "reviewer": "gem-implementer",
            "distinctness_evidence": "P01 semantic-diversity: reference-purpose question.",
            "semantic_labels": [],
            "canonical_enums": ["answer", "not_applicable"],
        },
    }
    case.update(overrides)
    return case


def test_projects_required_dataset_sections_from_aligned_case() -> None:
    packet = project_dataset_packet(_case())

    assert packet["request"] == {
        "interpreted": _case()["question"],
        "is_multi_part": False,
        "parts": [],
        "text": _case()["question"],
    }
    assert packet["provenance"] == {
        "dataset_sha256": "assigned_by_manifest_t006",
        "detector_revision": "not_applicable_phase3_data",
        "evaluator_revision": "3a40be26de60011502add2e276936a0598cac89d58da03631b66645a23cc2b8f",
        "request_sha256": "edb6dab2da26b214668ed45210eaca6e610df056c1d9754130657e0f7db03dab",
    }
    assert packet["runtime"] == {
        "errors": [],
        "session_connected": False,
        "status": "not_checked",
        "transport_available": False,
    }
    assert packet["retrieval"]["source_quality_classes"] == ["canonical"]
    assert packet["source_assessment"]["quality_classes_present"] == ["canonical"]
    assert packet["schema_commit"] == "e0e700dd76e385ca41c0a79bbbc908c91f325151"
    assert "bookkeeping" not in packet
    assert "confirmation" not in packet
    assert "schema" not in packet


@pytest.mark.parametrize("case_id", ["SYN-MULTI-001", "SYN-MULTI-002"])
def test_projection_preserves_synthetic_multipart_child_shape(case_id: str) -> None:
    case = _synthetic_cases()[case_id]
    expected = _expected_packets()[case_id]

    packet = project_dataset_packet(case)

    assert packet["request"] == expected["request"]
    assert packet["parts"] == expected["parts"]
    assert packet["parent_aggregation"] == expected["parent_aggregation"]

    # Explicit multipart invariants (synthetic contract dimensions):
    assert packet["request"]["is_multi_part"] is True
    assert packet["request"]["text"] == packet["request"]["interpreted"] == case["question"]
    assert packet["request"]["parts"] == [part["sub_request"] for part in packet["parts"]]

    info_part, action_part = packet["parts"]
    # Child identities
    assert info_part["part_id"] == f"{case_id}-part-info"
    assert action_part["part_id"] == f"{case_id}-part-action"
    assert info_part["part_type"] == "informational"
    assert action_part["part_type"] == "action"
    # Child response state
    assert info_part["resolution"]["recommended_response"] == "answer"
    assert action_part["resolution"]["recommended_response"] == "explain_withholding"
    # Child execution eligibility
    assert info_part["resolution"]["execution_eligibility"] == "not_applicable"
    assert action_part["resolution"]["execution_eligibility"] in {"awaiting_live_state", "withheld"}
    # Child policy and withholding
    assert info_part["policy"]["status"] == "permitted"
    assert action_part["policy"]["status"] == "denied"
    assert info_part["semantic_labels"] == []
    assert action_part["semantic_labels"] == case["semantic_labels"]
    assert action_part["withholding_reasons"] == case["semantic_labels"]
    # Parent aggregation semantics
    assert packet["parent_aggregation"]["available_informational_parts"] == [info_part["part_id"]]
    assert packet["parent_aggregation"]["blocked_action_parts"] == [action_part["part_id"]]
    assert packet["parent_aggregation"]["overall_status"] == "partial"
    assert packet["parent_aggregation"]["response_available"] is True


@pytest.mark.parametrize(
    "case_id", ["SYN-MALFORMED-001", "SYN-MALFORMED-002", "SYN-MALFORMED-003"]
)
def test_projection_uses_standard_malformed_request_clarification_prompt(case_id: str) -> None:
    case = _synthetic_cases()[case_id]

    packet = project_dataset_packet(case)

    assert case["semantic_labels"] == ["malformed_request"]
    assert packet["answer"]["clarification_possible"] is True
    assert packet["answer"]["clarification_prompt"] == EXPECTED_MALFORMED_CLARIFICATION_PROMPT


@pytest.mark.parametrize(
    ("case", "response", "eligibility", "support", "policy"),
    [
        (_case(), "answer", "not_applicable", "not_applicable", "permitted"),
        (
            _case(
                id="A998",
                action_class="automation",
                adversarial=True,
                expected_response="explain_withholding",
                expected_eligibility="withheld",
                semantic_labels=["subject_substitution"],
            ),
            "explain_withholding",
            "withheld",
            "withheld",
            "denied",
        ),
        (
            _case(
                id="A997",
                expected_response="clarify",
                expected_eligibility="awaiting_confirmation",
                friendly_response="Please confirm the exact request.",
            ),
            "clarify",
            "awaiting_confirmation",
            "needs_clarification",
            "requires_confirmation",
        ),
    ],
)
def test_projection_normalizes_response_policy_and_proposal_invariants(
    case: dict[str, object], response: str, eligibility: str, support: str, policy: str
) -> None:
    packet = project_dataset_packet(case)

    assert packet["resolution"]["recommended_response"] == response
    assert packet["resolution"]["execution_eligibility"]["status"] == eligibility
    assert packet["proposal"]["support"] == support
    assert packet["policy"]["status"] == policy
    assert packet["adversarial_detection"]["semantic_labels"] == case.get("semantic_labels")


def test_projection_boundary_defaults_for_empty_optional_inputs() -> None:
    packet = project_dataset_packet(
        _case(
            question="",
            split=None,
            friendly_response="",
            source_case_ids=[],
            source_quality_classes=[],
            notes="",
            adjudication_evidence={},
        )
    )

    assert packet["request"]["text"] == ""
    assert packet["request"]["interpreted"] == ""
    assert packet["retrieval"]["num_results"] == 0
    assert packet["friendly_response"]["text"] == ""
    assert packet["evidence_chain"][0]["finding"] == ""
    assert packet["action_validation"]["parameter_completeness"] == "complete"


@pytest.mark.parametrize(
    ("labels", "expected_status", "expected_invalid"),
    [
        ([], "supported", []),
        (["malformed_request"], "malformed", []),
        (["invalid_parameterization"], "unsupported", ["requested parameter or objective is unsupported"]),
    ],
)
def test_projection_handles_label_variations_for_request_status_and_parameters(
    labels: list[str], expected_status: str, expected_invalid: list[str]
) -> None:
    packet = project_dataset_packet(
        _case(
            expected_response="answer" if not labels else "explain_withholding",
            expected_eligibility="not_applicable" if not labels else "withheld",
            semantic_labels=labels,
            adjudication_evidence={"semantic_labels": labels},
        )
    )

    assert packet["resolution"]["request_status"] == expected_status
    assert packet["action_validation"]["invalid_parameters"] == expected_invalid


def test_projection_rejects_invalid_case_types_and_missing_identity() -> None:
    with pytest.raises(TypeError, match="case must be a mapping"):
        project_dataset_packet(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="case id is required"):
        project_dataset_packet(_case(id=""))


def test_projection_is_deterministic_and_idempotent_for_state_transitions() -> None:
    case = _case(id="A996", expected_response="explain_withholding", expected_eligibility="withheld")

    first = project_dataset_packet(case)
    second = project_dataset_packet(case)

    assert first == second
    assert first["packet_id"] == "packet-a996"
    assert first["resolution"]["execution_eligibility"]["eligible"] is False
