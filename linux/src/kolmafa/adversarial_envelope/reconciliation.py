"""Offline source reconciliation contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def reconcile_sources(input_fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Reconcile sources without treating derivative counts as authority."""

    canonical_count = input_fixture.get("canonical_count", 0)
    if not isinstance(canonical_count, int):
        canonical_count = 0

    if canonical_count <= 0:
        return {"reconciliation_result": "insufficient_provenance", "canonical_authority": False}

    return {"reconciliation_result": "no_conflict", "canonical_authority": True}


__all__ = ["reconcile_sources"]
