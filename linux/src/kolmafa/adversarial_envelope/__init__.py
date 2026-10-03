"""Offline adversarial-envelope schema helpers.

This package contains pure schema vocabulary used by lifecycle contract tests.
It does not perform runtime execution, network access, subprocess calls, or
artifact/file reads at import time.
"""

from kolmafa.adversarial_envelope.schema import (
    CANONICAL_FIELD_PATHS,
    PROPOSAL_SUPPORT_FIELD_VALUES,
    ProposalSupport,
    assert_canonical_field_paths,
)
from kolmafa.adversarial_envelope.dataset_projection import project_dataset_packet

__all__ = [
    "CANONICAL_FIELD_PATHS",
    "PROPOSAL_SUPPORT_FIELD_VALUES",
    "ProposalSupport",
    "assert_canonical_field_paths",
    "project_dataset_packet",
]
