"""Test-only helpers for Phase 4 adversarial-envelope TDD contracts.

This module is intentionally limited to artifact loading, frozen binding checks,
and manifest/inventory validation. It does not implement classifier, resolver,
packet validation, eligibility, runtime, bridge, GCLI, ASH, or KoLmafia logic.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "adversarial-envelope-schema-v2.0.0-preprototype"
SCHEMA_COMMIT = "e0e700dd76e385ca41c0a79bbbc908c91f325151"
DATASET_COMMIT = "21b3c714a8c2b05ec1518fb480716b109aa7fac2"

ALLOWED_FAILURE_CATEGORIES = (
    "EXPECTED_IMPLEMENTATION_MISSING",
    "TEST_OR_FIXTURE_DEFECT",
    "SCHEMA_BINDING_FAILURE",
    "DATASET_BINDING_FAILURE",
    "UNEXPECTED_PASS",
    "UNEXPECTED_EXCEPTION",
)

TEST_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_ROOT.parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
GIT_ROOT = REPOSITORY_ROOT.parent
MANIFEST_PATH = TEST_ROOT / "phase4_contract_manifest.json"
INVENTORY_PATH = TEST_ROOT / "phase4_failure_inventory.expected.json"

DATASET_ARTIFACTS = (
    "kolmaf-AI/kolmaf-ai/data/eval/adversarial-envelope-aligned-v2.0.0-preprototype.json",
    "kolmaf-AI/kolmaf-ai/data/eval/adversarial-envelope-expected-packets-v2.0.0-preprototype.json",
)


class BindingFailure(AssertionError):
    """Raised when frozen Phase 4 bindings fail closed before contract checks."""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        super().__init__(f"{category}: {message}")


@dataclass(frozen=True, slots=True)
class ContractCase:
    """Manifest-backed lifecycle contract metadata."""

    contract_id: str
    source_row: int
    source_line: int
    title: str
    tests: str
    expected_category: str
    target_module: str
    target_symbol: str
    input_fixture: dict[str, Any]
    expected_result: Any

    @property
    def pytest_id(self) -> str:
        slug = "_".join(
            "".join(ch.lower() if ch.isalnum() else " " for ch in self.title).split()[:8]
        )
        return f"{self.contract_id}_{slug}"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_contracts() -> list[ContractCase]:
    manifest = load_json(MANIFEST_PATH)
    _assert_manifest_bindings(manifest)
    contracts = [ContractCase(**entry) for entry in manifest["contracts"]]
    ids = [contract.contract_id for contract in contracts]
    expected_ids = [f"LC{index:02d}" for index in range(1, 39)]
    if ids != expected_ids:
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", f"contract IDs are not LC01-LC38: {ids}")
    return contracts


def verify_frozen_bindings() -> None:
    """Fail closed on schema/dataset drift before any lifecycle assertion."""

    _assert_git_commit_exists(SCHEMA_COMMIT, "SCHEMA_BINDING_FAILURE")
    _assert_git_commit_exists(DATASET_COMMIT, "DATASET_BINDING_FAILURE")
    _assert_dataset_artifacts_match_commit_tree()
    _assert_dataset_metadata_matches_bindings()
    _assert_inventory_bindings()


def assert_phase4_contract_behavior(contract: ContractCase) -> None:
    """Call the future entrypoint and compare against frozen LC expected data.

    Current Phase 4 is failing TDD. Missing modules/symbols remain categorized
    as EXPECTED_IMPLEMENTATION_MISSING, while empty/stub implementations that
    return ``None`` or defaults fail on the frozen result comparison below.
    """

    try:
        spec = importlib.util.find_spec(contract.target_module)
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, (
        "EXPECTED_IMPLEMENTATION_MISSING: "
        f"{contract.contract_id} requires missing implementation module "
        f"{contract.target_module!r}: {contract.title}"
    )
    module = importlib.import_module(contract.target_module)
    assert hasattr(module, contract.target_symbol), (
        "EXPECTED_IMPLEMENTATION_MISSING: "
        f"{contract.contract_id} requires missing implementation symbol "
        f"{contract.target_module}.{contract.target_symbol}: {contract.title}"
    )

    entrypoint = getattr(module, contract.target_symbol)
    if contract.target_symbol == "ProposalSupport":
        actual = _evaluate_proposal_support_enum(entrypoint, contract.input_fixture)
    else:
        actual = entrypoint(contract.input_fixture)
    assert actual == contract.expected_result, (
        f"{contract.contract_id} frozen behavior mismatch for "
        f"{contract.target_module}.{contract.target_symbol}; "
        f"input_fixture={contract.input_fixture!r}"
    )


def _evaluate_proposal_support_enum(enum_type: Any, input_fixture: dict[str, Any]) -> dict[str, Any]:
    """Exercise the future ProposalSupport enum without implementing it."""

    if "serialized_value" in input_fixture:
        member = getattr(enum_type, input_fixture["enum_member"])
        round_trip = enum_type(input_fixture["serialized_value"]).value
        return {"round_trip": round_trip if member.value == round_trip else member.value}

    observed_values = [enum_type(value).value for value in input_fixture["field_values"]]
    return {
        "enum_values": observed_values,
        "field_enum_match": observed_values == input_fixture["field_values"],
    }


def _assert_manifest_bindings(manifest: dict[str, Any]) -> None:
    bindings = manifest.get("bindings", {})
    expected = {
        "schema_version": SCHEMA_VERSION,
        "schema_commit": SCHEMA_COMMIT,
        "dataset_commit": DATASET_COMMIT,
    }
    if bindings != expected:
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", f"manifest bindings mismatch: {bindings}")


def _assert_inventory_bindings() -> None:
    inventory = load_json(INVENTORY_PATH)
    bindings = inventory.get("bindings", {})
    expected = {
        "schema_version": SCHEMA_VERSION,
        "schema_commit": SCHEMA_COMMIT,
        "dataset_commit": DATASET_COMMIT,
    }
    if bindings != expected:
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", f"inventory bindings mismatch: {bindings}")
    categories = inventory.get("categories", {})
    if tuple(categories) != ALLOWED_FAILURE_CATEGORIES:
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", "inventory category vocabulary drifted")


def _assert_git_commit_exists(commit: str, category: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-t", commit],
        cwd=GIT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "commit":
        raise BindingFailure(category, f"cannot verify git commit {commit}")


def _git_show_bytes(commit: str, artifact: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{artifact}"],
        cwd=GIT_ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise BindingFailure("DATASET_BINDING_FAILURE", f"missing commit-tree artifact {artifact}")
    return result.stdout


def _assert_dataset_artifacts_match_commit_tree() -> None:
    for artifact in DATASET_ARTIFACTS:
        authoritative_bytes = _git_show_bytes(DATASET_COMMIT, artifact)
        local_path = GIT_ROOT / artifact
        local_bytes = local_path.read_bytes()
        if hashlib.sha256(local_bytes).hexdigest() != hashlib.sha256(authoritative_bytes).hexdigest():
            raise BindingFailure(
                "DATASET_BINDING_FAILURE",
                f"local fixture drift from dataset_commit for {artifact}",
            )


def _assert_dataset_metadata_matches_bindings() -> None:
    aligned = load_json(PROJECT_ROOT / "data/eval/adversarial-envelope-aligned-v2.0.0-preprototype.json")
    cases = aligned.get("cases", [])
    if not cases:
        raise BindingFailure("DATASET_BINDING_FAILURE", "aligned dataset contains no cases")
    for case in cases:
        evidence = case.get("adjudication_evidence", {})
        if evidence.get("schema_commit") != SCHEMA_COMMIT:
            raise BindingFailure("SCHEMA_BINDING_FAILURE", f"case {case.get('id')} schema_commit drift")
        if evidence.get("schema_version") != SCHEMA_VERSION:
            raise BindingFailure("SCHEMA_BINDING_FAILURE", f"case {case.get('id')} schema_version drift")

    packets = load_json(
        PROJECT_ROOT / "data/eval/adversarial-envelope-expected-packets-v2.0.0-preprototype.json"
    ).get("expected_packets", {})
    if not packets:
        raise BindingFailure("DATASET_BINDING_FAILURE", "expected packet fixture contains no packets")
    for case_id, packet in packets.items():
        if packet.get("schema_version") != SCHEMA_VERSION:
            raise BindingFailure("SCHEMA_BINDING_FAILURE", f"packet {case_id} schema_version drift")
