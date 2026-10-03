"""Purpose-scoped evidence sufficiency helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def compute_evidence_sufficiency(input_fixture: Mapping[str, Any]) -> dict[str, str]:
    """Return sufficiency by purpose without cross-purpose promotion."""

    purpose_results = input_fixture.get("purpose_results", {})
    if not isinstance(purpose_results, Mapping):
        purpose_results = {}
    return {
        "for_informational_answer": str(purpose_results.get("informational_answer", "not_checked")),
        "for_proposal_premise": str(purpose_results.get("proposal_premise", "not_checked")),
    }


__all__ = ["compute_evidence_sufficiency"]
