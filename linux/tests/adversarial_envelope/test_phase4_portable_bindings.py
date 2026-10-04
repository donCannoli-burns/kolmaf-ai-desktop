"""Portable Phase 4 binding attestation tests (repository-contained facts).

Verifies the Phase 4 contract manifest, the historical failure inventory, and
the public binding attestation are internally consistent and match the current
repository source. No parent workspace, no historical Git objects, and no
private dataset files are required.
"""

from __future__ import annotations

import hashlib
import importlib

from phase4_contract_helpers import (
    ALLOWED_FAILURE_CATEGORIES,
    CONTRACT_COUNT,
    DATASET_COMMIT,
    EXPECTED_CONTRACT_IDS,
    INVENTORY_PATH,
    MANIFEST_PATH,
    SCHEMA_COMMIT,
    SCHEMA_VERSION,
    load_contracts,
    load_public_bindings,
    verify_public_attestation,
)


def test_manifest_parses_and_binds_38_contracts() -> None:
    contracts = load_contracts()

    assert len(contracts) == CONTRACT_COUNT
    assert [contract.contract_id for contract in contracts] == list(EXPECTED_CONTRACT_IDS)


def test_manifest_and_inventory_hashes_match_public_attestation() -> None:
    attestation = load_public_bindings()

    manifest_hash = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    inventory_hash = hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest()

    assert attestation["phase4_contract_manifest_sha256"] == manifest_hash
    assert attestation["historical_failure_inventory_sha256"] == inventory_hash


def test_public_attestation_is_consistent() -> None:
    verify_public_attestation()


def test_target_modules_and_symbols_resolve() -> None:
    for contract in load_contracts():
        spec = importlib.util.find_spec(contract.target_module)
        assert spec is not None, (
            f"{contract.contract_id}: module {contract.target_module!r} does not resolve"
        )
        module = importlib.import_module(contract.target_module)
        assert hasattr(module, contract.target_symbol), (
            f"{contract.contract_id}: symbol {contract.target_symbol!r} missing from "
            f"{contract.target_module!r}"
        )


def test_historical_inventory_structure() -> None:
    """The failure inventory is preserved as historical evidence.

    At the original Phase 4 TDD checkpoint, all 38 LC contracts were expected
    red (EXPECTED_IMPLEMENTATION_MISSING). The inventory keeps that record; the
    public attestation and the active suite reflect the current green status.
    """

    from phase4_contract_helpers import load_json

    inventory = load_json(INVENTORY_PATH)

    assert inventory["bindings"]["schema_version"] == SCHEMA_VERSION
    assert inventory["bindings"]["schema_commit"] == SCHEMA_COMMIT
    assert inventory["bindings"]["dataset_commit"] == DATASET_COMMIT
    assert tuple(inventory["categories"]) == ALLOWED_FAILURE_CATEGORIES

    entries = inventory["entries"]
    assert len(entries) == CONTRACT_COUNT
    assert [entry["contract_id"] for entry in entries] == list(EXPECTED_CONTRACT_IDS)
    assert all(
        entry["expected_category"] == "EXPECTED_IMPLEMENTATION_MISSING" for entry in entries
    ), "historical inventory no longer records the original all-red expectation"
