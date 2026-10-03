"""Canonical offline schema vocabulary for adversarial-envelope packets.

The module is intentionally data-only and deterministic.  It exposes enum and
field-path contracts without reading tests, docs, datasets, or evidence
artifacts at import time or during validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class ProposalSupport(StrEnum):
    """Canonical serialized values for the ``proposal.support`` field."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    NEEDS_CLARIFICATION = "needs_clarification"
    WITHHELD = "withheld"
    NOT_APPLICABLE = "not_applicable"
    NOT_CHECKED = "not_checked"


PROPOSAL_SUPPORT_FIELD_VALUES: tuple[str, ...] = tuple(member.value for member in ProposalSupport)
"""Allowed serialized values for ``proposal.support``.

This tuple is derived from :class:`ProposalSupport` so the enum and field
definition cannot drift independently.
"""


CANONICAL_FIELD_PATHS: frozenset[str] = frozenset(
    {
        "proposal.support",
        "policy.status",
    }
)
"""Canonical field paths required by the offline adversarial-envelope schema."""


def assert_canonical_field_paths(input_fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Validate canonical path normalization for caller-provided fixture data.

    Args:
        input_fixture: Mapping with a ``forbidden_path`` and ``canonical_path``.

    Returns:
        A contract-shaped result containing a zero match count for non-canonical
        aliases and the accepted canonical path.

    Raises:
        ValueError: If the requested canonical path is not part of the offline
            schema vocabulary.
    """

    canonical_path = input_fixture.get("canonical_path")
    if not isinstance(canonical_path, str) or canonical_path not in CANONICAL_FIELD_PATHS:
        raise ValueError(f"unknown canonical field path: {canonical_path!r}")

    forbidden_path = input_fixture.get("forbidden_path")
    forbidden_path_matches = int(forbidden_path == canonical_path)
    return {
        "forbidden_path_matches": forbidden_path_matches,
        "canonical_path": canonical_path,
    }
