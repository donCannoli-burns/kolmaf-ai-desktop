"""Test-only helpers for Phase 4 adversarial-envelope lifecycle contracts.

Portable layer (repository-contained facts only):
  - manifest loading and structure validation
  - public binding attestation (``phase4_public_bindings.json``)
  - behavioral contract execution with exact-equality semantics and
    stub/default protection
  - deep source-level meta-contract verification (function signature
    boundaries, producer exclusivity, field-path normalization, enum
    values, authoritative producer tables)

Historical layer (``local_artifact``, ``KOLMAF_PRIVATE_EVAL_ROOT``):
  - dataset artifact metadata verification against the frozen bindings,
    isolated in the test module.

This module does not implement classifier, resolver, packet validation,
eligibility, runtime, bridge, GCLI, ASH, or KoLmafia logic.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "adversarial-envelope-schema-v2.0.0-preprototype"
SCHEMA_COMMIT = "e0e700dd76e385ca41c0a79bbbc908c91f325151"
DATASET_COMMIT = "21b3c714a8c2b05ec1518fb480716b109aa7fac2"

TEST_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = TEST_ROOT / "phase4_contract_manifest.json"
INVENTORY_PATH = TEST_ROOT / "phase4_failure_inventory.historical.json"
PUBLIC_BINDINGS_PATH = TEST_ROOT / "phase4_public_bindings.json"

ALLOWED_FAILURE_CATEGORIES = (
    "EXPECTED_IMPLEMENTATION_MISSING",
    "TEST_OR_FIXTURE_DEFECT",
    "SCHEMA_BINDING_FAILURE",
    "DATASET_BINDING_FAILURE",
    "UNEXPECTED_PASS",
    "UNEXPECTED_EXCEPTION",
)

EXPECTED_CONTRACT_IDS: tuple[str, ...] = tuple(f"LC{index:02d}" for index in range(1, 39))
CONTRACT_COUNT = 38


class BindingFailure(AssertionError):
    """Raised when Phase 4 binding or attestation checks fail closed."""

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
    """Load and validate the Phase 4 contract manifest."""

    manifest = load_json(MANIFEST_PATH)
    validate_manifest_structure(manifest)
    contracts = [ContractCase(**entry) for entry in manifest["contracts"]]
    ids = [contract.contract_id for contract in contracts]
    if ids != list(EXPECTED_CONTRACT_IDS):
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", f"contract IDs are not LC01-LC38: {ids}")
    return contracts


def validate_manifest_structure(manifest: dict[str, Any]) -> None:
    """Validate manifest bindings, contract count, ordering, and field shape."""

    bindings = manifest.get("bindings", {})
    expected_bindings = {
        "schema_version": SCHEMA_VERSION,
        "schema_commit": SCHEMA_COMMIT,
        "dataset_commit": DATASET_COMMIT,
    }
    if bindings != expected_bindings:
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", f"manifest bindings mismatch: {bindings}")

    contracts = manifest.get("contracts", [])
    if len(contracts) != CONTRACT_COUNT:
        raise BindingFailure(
            "TEST_OR_FIXTURE_DEFECT",
            f"manifest contract count != {CONTRACT_COUNT}: {len(contracts)}",
        )
    ids = [contract.get("contract_id") for contract in contracts]
    if ids != list(EXPECTED_CONTRACT_IDS):
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", f"contract IDs not ordered LC01-LC38: {ids}")
    if len(set(ids)) != len(ids):
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", "contract IDs are not unique")

    for contract in contracts:
        contract_id = contract.get("contract_id")
        if not contract.get("target_module"):
            raise BindingFailure("TEST_OR_FIXTURE_DEFECT", f"{contract_id} has empty target_module")
        if not contract.get("target_symbol"):
            raise BindingFailure("TEST_OR_FIXTURE_DEFECT", f"{contract_id} has empty target_symbol")
        if not isinstance(contract.get("input_fixture"), dict):
            raise BindingFailure("TEST_OR_FIXTURE_DEFECT", f"{contract_id} input_fixture not structured")
        if "expected_result" not in contract:
            raise BindingFailure("TEST_OR_FIXTURE_DEFECT", f"{contract_id} missing expected_result")


def assert_phase4_contract_behavior(contract: ContractCase) -> None:
    """Call the target entrypoint and compare against frozen LC expected data.

    Exact equality is the behavioral rule: empty/stub implementations that
    return ``None`` or defaults fail on the frozen result comparison below.
    Missing modules/symbols fail closed.
    """

    try:
        spec = importlib.util.find_spec(contract.target_module)
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, (
        f"{contract.contract_id} requires missing implementation module "
        f"{contract.target_module!r}: {contract.title}"
    )
    module = importlib.import_module(contract.target_module)
    assert hasattr(module, contract.target_symbol), (
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


def load_public_bindings() -> dict[str, Any]:
    """Load the public-safe Phase 4 binding attestation."""

    return load_json(PUBLIC_BINDINGS_PATH)


def verify_public_attestation() -> None:
    """Verify manifest/inventory hashes and bindings against the public attestation."""

    attestation = load_public_bindings()

    manifest_hash = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    if attestation["phase4_contract_manifest_sha256"] != manifest_hash:
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", "manifest hash mismatch vs public attestation")

    inventory_hash = hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest()
    if attestation["historical_failure_inventory_sha256"] != inventory_hash:
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", "inventory hash mismatch vs public attestation")

    if attestation["schema_version"] != SCHEMA_VERSION:
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", "attestation schema_version drift")
    if attestation["contract_count"] != CONTRACT_COUNT:
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", "attestation contract_count != 38")
    if tuple(attestation["contract_ids"]) != EXPECTED_CONTRACT_IDS:
        raise BindingFailure("TEST_OR_FIXTURE_DEFECT", "attestation contract_ids != LC01-LC38")


def verify_meta_contract_facts() -> None:
    """Deep source-level verification for producer/schema meta-contracts.

    LC12/LC13/LC23/LC25: function signature boundaries and forbidden-input tables.
    LC14: producer exclusivity for ``execution_eligibility``.
    LC26: field-path normalization (``policy_status.state`` unused).
    LC27/LC33: ``ProposalSupport`` enum values and round-trip.
    LC38: authoritative producer table completeness.
    """

    from kolmafa.adversarial_envelope import eligibility, proposal_support, resolver, schema

    # LC12: derive_proposal_support signature excludes proposal_supported and
    # execution_eligibility; the authoritative input table also excludes them.
    params = set(inspect.signature(proposal_support.derive_proposal_support).parameters)
    assert not {"proposal_supported", "execution_eligibility"} & params, (
        f"LC12: derive_proposal_support signature accepts forbidden inputs: {sorted(params)}"
    )
    assert not {"proposal_supported", "execution_eligibility"} & set(
        proposal_support.AUTHORITATIVE_PROPOSAL_SUPPORT_INPUTS
    ), "LC12: authoritative input table contains forbidden inputs"

    # LC13: resolve_response signature excludes proposal_supported.
    params = set(inspect.signature(resolver.resolve_response).parameters)
    assert "proposal_supported" not in params, (
        f"LC13: resolve_response signature accepts proposal_supported: {sorted(params)}"
    )

    # LC23: forbidden downstream inputs are recorded in the forbidden-input table.
    forbidden = proposal_support._DOWNSTREAM_OR_FORBIDDEN_INPUTS
    assert {
        "semantic_labels",
        "evidence_sufficiency",
        "execution_eligibility",
        "withholding_class_active",
    } <= forbidden, "LC23: forbidden-input table missing downstream fields"

    # LC25: resolve_response has no execution_eligibility output.
    resolver_source = Path(resolver.__file__).read_text(encoding="utf-8")
    assert not re.search(r'["\']execution_eligibility["\']\s*:', resolver_source), (
        "LC25: resolver.py writes execution_eligibility"
    )

    # LC14: compute_execution_eligibility is the only flat eligibility producer.
    _verify_eligibility_producer_exclusivity()

    # LC26: policy_status.state is not used anywhere; policy.status is canonical.
    _verify_canonical_field_paths()

    # LC27: ProposalSupport.NOT_CHECKED exists, maps to not_checked, round-trips.
    assert schema.ProposalSupport.NOT_CHECKED.value == "not_checked"
    assert schema.ProposalSupport("not_checked") is schema.ProposalSupport.NOT_CHECKED

    # LC33: enum values and field definition are identical.
    assert [member.value for member in schema.ProposalSupport] == list(
        schema.PROPOSAL_SUPPORT_FIELD_VALUES
    ), "LC33: ProposalSupport enum/field values diverged"

    # LC38: authoritative producer table binds all 9 derive_proposal_support inputs.
    assert len(proposal_support.AUTHORITATIVE_PROPOSAL_SUPPORT_INPUTS) == 9, (
        "LC38: authoritative producer table does not have 9 entries"
    )


def _verify_eligibility_producer_exclusivity() -> None:
    """LC14: compute_execution_eligibility is the only flat eligibility producer.

    Scans all modules in the adversarial_envelope package for flat
    ``"execution_eligibility": <scalar>`` decision writes. The only permitted
    producer is ``eligibility.compute_execution_eligibility``. The
    dataset_projection module materializes frozen dataset adjudication values
    under a nested ``resolution.execution_eligibility`` structure (Phase 3 data
    projection layer), which is not a gate-derived runtime producer.
    """

    from kolmafa.adversarial_envelope import eligibility

    package_dir = Path(eligibility.__file__).resolve().parent
    flat_write = re.compile(r"^\s*[\"']execution_eligibility[\"']\s*:(?!\s*\{)")

    producers: dict[str, list[int]] = {}
    for module_file in sorted(package_dir.glob("*.py")):
        if module_file.name == "__init__.py":
            continue
        for line_no, line in enumerate(
            module_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if flat_write.match(line):
                producers.setdefault(module_file.name, []).append(line_no)

    assert set(producers) <= {"eligibility.py"}, (
        f"LC14: execution_eligibility flat decision writes outside eligibility.py: {producers}"
    )

    eligibility_source = (package_dir / "eligibility.py").read_text(encoding="utf-8")
    top_level_functions = re.findall(r"^def (\w+)", eligibility_source, re.MULTILINE)
    assert top_level_functions == ["compute_execution_eligibility"], (
        f"LC14: eligibility.py top-level functions changed: {top_level_functions}"
    )


def _verify_canonical_field_paths() -> None:
    """LC26: policy_status.state is not used anywhere; policy.status is canonical."""

    from kolmafa.adversarial_envelope import schema

    package_dir = Path(schema.__file__).resolve().parent
    for module_file in sorted(package_dir.glob("*.py")):
        source = module_file.read_text(encoding="utf-8")
        assert "policy_status.state" not in source, (
            f"LC26: forbidden path policy_status.state used in {module_file.name}"
        )
    assert "policy.status" in schema.CANONICAL_FIELD_PATHS, (
        "LC26: policy.status missing from canonical field paths"
    )


def _evaluate_proposal_support_enum(enum_type: Any, input_fixture: dict[str, Any]) -> dict[str, Any]:
    """Exercise the ProposalSupport enum for LC27/LC33 round-trip contracts."""

    if "serialized_value" in input_fixture:
        member = getattr(enum_type, input_fixture["enum_member"])
        round_trip = enum_type(input_fixture["serialized_value"]).value
        return {"round_trip": round_trip if member.value == round_trip else member.value}

    observed_values = [enum_type(value).value for value in input_fixture["field_values"]]
    return {
        "enum_values": observed_values,
        "field_enum_match": observed_values == input_fixture["field_values"],
    }
