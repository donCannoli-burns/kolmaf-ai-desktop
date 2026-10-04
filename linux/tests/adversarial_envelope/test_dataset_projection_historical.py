"""Exact historical projection alignment verification (local_artifact).

Consumes the intentionally non-public historical evaluation artifacts under
KOLMAF_PRIVATE_EVAL_ROOT and verifies the projection output matches the
frozen expected-packets export byte-for-byte at the structural level. These
assertions are unchanged from the original portable contract file; only the
artifact path resolution moved behind the private-artifact boundary.

Skipped precisely when KOLMAF_PRIVATE_EVAL_ROOT is unset or an artifact is
missing. See tests/fixtures/private_eval.py.
"""

from __future__ import annotations

import json

import pytest

from kolmafa.adversarial_envelope.dataset_projection import project_dataset_packet
from fixtures.private_eval import require_private_eval_artifact

pytestmark = pytest.mark.local_artifact


def _aligned_case(case_id: str) -> dict[str, object]:
    path = require_private_eval_artifact(
        "adversarial-envelope-aligned-v2.0.0-preprototype.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    return next(case for case in data["cases"] if case["id"] == case_id)  # type: ignore[no-any-return]


def _expected_packet(case_id: str) -> dict[str, object]:
    path = require_private_eval_artifact(
        "adversarial-envelope-expected-packets-v2.0.0-preprototype.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["expected_packets"][case_id]  # type: ignore[no-any-return]


@pytest.mark.parametrize("case_id", ["A074", "A080", "A084"])
def test_projection_preserves_residual_multipart_child_shape(case_id: str) -> None:
    case = _aligned_case(case_id)
    expected = _expected_packet(case_id)

    packet = project_dataset_packet(case)

    assert packet["request"] == expected["request"]
    assert packet["parts"] == expected["parts"]
    assert packet["parent_aggregation"] == expected["parent_aggregation"]


@pytest.mark.parametrize("case_id", ["A044", "A046", "A048"])
def test_projection_uses_standard_malformed_request_clarification_prompt(case_id: str) -> None:
    case = _aligned_case(case_id)
    expected = _expected_packet(case_id)

    packet = project_dataset_packet(case)

    assert case["semantic_labels"] == ["malformed_request"]
    assert packet["answer"]["clarification_possible"] is True
    assert packet["answer"]["clarification_prompt"] == expected["answer"]["clarification_prompt"]
