"""Tests for Phase 6 offline evaluation utilities."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PHASE6_SCRIPT = (
    REPOSITORY_ROOT
    / "kolmaf-AI/docs/plan/20260715-adversarial-layer-preprototype-repair-phase6-offline-evaluation/phase6_eval.py"
)


@pytest.fixture(scope="module")
def phase6_module() -> Any:
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
