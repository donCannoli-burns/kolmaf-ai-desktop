"""Exact historical evaluation-artifact SHA-256 preservation (local_artifact).

Verifies the intentionally non-public dataset.json and checkpoint-002.json
bytes under KOLMAF_PRIVATE_EVAL_ROOT still match the frozen pins. The pins
are unchanged from the original portable test; only artifact path resolution
moved behind the private-artifact boundary.

Skipped precisely when KOLMAF_PRIVATE_EVAL_ROOT is unset or an artifact is
missing. See tests/fixtures/private_eval.py.
"""

from __future__ import annotations

import hashlib

import pytest

from fixtures.private_eval import require_private_eval_artifact

pytestmark = pytest.mark.local_artifact

DATASET_EXPECTED_SHA256 = "0874fdc79d66ee2f42aa94e06144ff2fa0309ad535e49106e34b05f352720a6a"
CHECKPOINT_EXPECTED_SHA256 = "6795d2f95263bb06399aad5a1c3a2350999d837d691c29e4e20973644ddf519e"


def test_original_artifact_sha256() -> None:
    """Verify original dataset and checkpoint bytes match supplied SHA-256 (§7.1)."""
    dataset_path = require_private_eval_artifact("dataset.json")
    dataset_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    assert dataset_hash == DATASET_EXPECTED_SHA256, (
        f"dataset.json SHA-256 mismatch: got {dataset_hash}, "
        f"expected {DATASET_EXPECTED_SHA256}"
    )

    checkpoint_path = require_private_eval_artifact("checkpoint-002.json")
    checkpoint_hash = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    assert checkpoint_hash == CHECKPOINT_EXPECTED_SHA256, (
        f"checkpoint-002.json SHA-256 mismatch: got {checkpoint_hash}, "
        f"expected {CHECKPOINT_EXPECTED_SHA256}"
    )
