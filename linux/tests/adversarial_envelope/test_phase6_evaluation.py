"""LEGACY: tests for the historical Phase 6 offline evaluation script.

This module is classified ``legacy`` and is deselected from the portable CI
gate by marker. It verifies a historical evaluation utility script
(``phase6_eval.py``) that is NOT part of the current public runtime: the
script belonged to an obsolete multi-repo workspace layout and is
intentionally not published in this repository.

The script is supplied explicitly via the ``KOLMAF_LEGACY_PHASE6_SCRIPT``
environment variable, which must point directly at the historical
``phase6_eval.py`` file. No parent or sibling workspace is inferred. When
the variable is unset, the ``phase6_module`` fixture skips precisely; when
set, the module is imported and all five historical contracts execute
normally. Assertion failures inside a valid historical module are never
converted to skips.

Historical Phase 6 behavior -> current equivalent coverage (evidence-based,
no overclaiming):

- ``canonical_json_bytes`` (canonical JSON stable across dict ordering):
  HISTORICAL_ONLY as a function. The current tree has no general
  canonical-bytes utility; the same ``sort_keys=True`` canonicalization
  pattern exists under different names and purposes
  (``kolmafa/confirmations.py`` ``canonical_hash``,
  ``kolmafa/devtest/transport_identity.py`` ``TransportIdentity.canonical_json``),
  and canonical-bytes equality is asserted by
  ``tests/test_matrix_overlay.py::test_overlay_deterministic``.
- ``diff_paths`` (nested difference reporting): HISTORICAL_ONLY. No nested
  diff utility exists anywhere in the current tree.
- ``validate_serialization`` (fails closed on missing safety fields):
  HISTORICAL_ONLY. No serialization-report validator exists in the current
  tree; fail-closed behavior for missing required fields is covered
  separately by the adversarial-envelope projection contract tests
  (``tests/adversarial_envelope/test_dataset_projection_contract.py``).
- ``evaluate_once`` (one result per 157-case frozen dataset + serialization
  PASS): HISTORICAL_ONLY. The frozen 157-case dataset is intentionally
  non-public; the current ``kolmafa.eval`` module is a retrieval scoring
  harness, not an adversarial-envelope case evaluator.
- ``build_actual_packet`` (delegates to the package dataset projection):
  CURRENTLY_COVERED_ELSEWHERE. The current production projection
  ``kolmafa.adversarial_envelope.dataset_projection.project_dataset_packet``
  (``linux/src/kolmafa/adversarial_envelope/dataset_projection.py``) is
  exercised portably by
  ``tests/adversarial_envelope/test_dataset_projection_contract.py``.

The five historical contracts below are preserved unchanged for explicit
legacy verification only. They are not a live implementation target.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.legacy

LEGACY_PHASE6_SCRIPT_ENV = "KOLMAF_LEGACY_PHASE6_SCRIPT"

PHASE6_SCRIPT = (
    Path(os.environ[LEGACY_PHASE6_SCRIPT_ENV])
    if os.environ.get(LEGACY_PHASE6_SCRIPT_ENV)
    else None
)


@pytest.fixture(scope="module")
def phase6_module() -> Any:
    if PHASE6_SCRIPT is None:
        pytest.skip("historical Phase 6 evaluator script not configured")
    if not PHASE6_SCRIPT.is_file():
        pytest.skip(f"historical Phase 6 evaluator script not found: {PHASE6_SCRIPT}")
    spec = importlib.util.spec_from_file_location("phase6_eval", PHASE6_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_canonical_json_bytes_is_stable(phase6_module: Any) -> None:
    left = {"b": [2, 1], "a": {"z": True}}
    right = {"a": {"z": True}, "b": [2, 1]}

    assert phase6_module.canonical_json_bytes(left) == phase6_module.canonical_json_bytes(right)


def test_diff_paths_reports_nested_mismatches(phase6_module: Any) -> None:
    expected = {"a": {"b": 1}, "items": [{"x": "old"}]}
    actual = {"a": {"b": 2}, "items": [{"x": "new"}], "extra": True}

    assert phase6_module.diff_paths(expected, actual) == ["a.b", "extra", "items[0].x"]


def test_serialization_fails_closed_on_missing_safety_fields(phase6_module: Any) -> None:
    report = phase6_module.validate_serialization(
        [{"case_id": "X001", "actual_packet_hash": "bad", "actual_packet": {"packet_id": "packet-x001"}}]
    )

    assert report["status"] == "FAIL"
    assert report["failures"][0]["case_id"] == "X001"
    assert "missing safety field" in report["failures"][0]["error"]


def test_evaluate_once_produces_one_record_per_frozen_case(phase6_module: Any) -> None:
    bundle = phase6_module.evaluate_once(validate_bindings=False)

    assert bundle.results["metrics"]["total_cases"] == 157
    assert len(bundle.results["actual_records"]) == 157
    assert bundle.serialization_report["status"] == "PASS"


def test_build_actual_packet_consumes_package_dataset_projection(
    phase6_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = {"id": "A999", "question": "Q", "split": "dev"}
    produced = {
        "packet_id": "packet-a999",
        "runtime": {"external_state_read": False},
        "adversarial_detection": {"semantic_labels": ["patched"]},
        "resolution": {"recommended_response": "answer", "execution_eligibility": {"status": "not_applicable"}},
        "proposal": {"support": "supported"},
        "policy": {"status": "not_applicable"},
        "schema_version": phase6_module.SCHEMA_VERSION,
    }
    calls = []

    def fake_project_dataset_packet(input_case: dict[str, object]) -> dict[str, object]:
        calls.append(input_case)
        return produced

    monkeypatch.setattr(phase6_module, "project_dataset_packet", fake_project_dataset_packet)

    assert phase6_module.build_actual_packet(case) is produced
    assert calls == [case]
