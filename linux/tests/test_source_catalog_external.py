"""External integration: real KOL_Master source catalog artifact.

This test asserts properties of the real sibling-workspace artifact
(KOL_Master/kol_master_additions). It is deselected from the portable CI
gate by the `external_integration` marker. When the artifact is absent it
skips with a precise, narrowly-scoped reason; it never borrows, copies, or
vendors external content into this repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kolmafa import source_catalog


REAL_ARTIFACT = Path(__file__).parents[2] / "KOL_Master" / "kol_master_additions"

pytestmark = pytest.mark.external_integration


def test_real_artifact_summary_is_deterministic_and_offline() -> None:
    if not REAL_ARTIFACT.is_file():
        pytest.skip(f"real KOL_Master artifact absent at {REAL_ARTIFACT}")

    records = source_catalog.parse_source_dump_file(REAL_ARTIFACT)
    first = source_catalog.validate_source_dump_file(REAL_ARTIFACT)
    second = source_catalog.validate_source_dump_file(REAL_ARTIFACT)

    assert records
    assert first.to_public_dict() == second.to_public_dict()
    assert first.summary.path.endswith("KOL_Master/kol_master_additions")
    assert first.summary.line_count == 345
    assert first.summary.row_count > 90
    assert first.summary.category_counts["PY/KOL"] >= 10
    assert first.summary.local_only_count >= 6
    assert first.to_public_dict()["offline"] is True
    assert first.to_public_dict()["live_kol_mutation"] is False
    assert "$HOME/AI-Dashboard" not in json.dumps(first.to_public_dict(), sort_keys=True)
