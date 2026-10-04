"""Phase 4 lifecycle contracts LC01-LC38 (portable, repository-contained).

Active green contract: all 38 LC rows execute against the current
adversarial_envelope implementation modules with exact-equality semantics.
Missing modules/symbols and stub/default returns fail closed.

Historical binding verification (dataset artifact metadata) is isolated in
the ``local_artifact`` section below and runs only when the operator supplies
the private evaluation artifacts via ``KOLMAF_PRIVATE_EVAL_ROOT``.
"""

from __future__ import annotations

import json

import pytest

from fixtures.private_eval import require_private_eval_artifact
from phase4_contract_helpers import (
    SCHEMA_COMMIT,
    SCHEMA_VERSION,
    ContractCase,
    assert_phase4_contract_behavior,
    load_contracts,
    verify_meta_contract_facts,
)

CONTRACTS = load_contracts()


@pytest.mark.parametrize(
    "contract",
    [pytest.param(contract, id=contract.pytest_id) for contract in CONTRACTS],
)
def test_phase4_lifecycle_contract(contract: ContractCase) -> None:
    """Frozen LC behavior: exact equality with expected_result."""

    assert_phase4_contract_behavior(contract)


def test_phase4_meta_contract_facts() -> None:
    """Deep source-level verification for producer/schema meta-contracts."""

    verify_meta_contract_facts()


@pytest.mark.local_artifact
class TestPhase4HistoricalBindings:
    """Historical Phase 4 binding verification against private eval artifacts.

    At the original Phase 4 TDD checkpoint, all 38 LC contracts were expected
    red (EXPECTED_IMPLEMENTATION_MISSING) because the implementation modules
    did not yet exist. This section preserves the historical binding evidence:
    when the operator supplies the private evaluation artifacts via
    KOLMAF_PRIVATE_EVAL_ROOT, it verifies the dataset metadata still matches
    the frozen schema/dataset bindings. Skipped when the root is unset.

    The historical git commit hashes (schema_commit, dataset_commit) are
    provenance identity recorded in phase4_public_bindings.json; they are not
    resolvable in this repository's Git history and are not verified here.
    """

    def test_aligned_dataset_metadata_matches_frozen_bindings(self) -> None:
        path = require_private_eval_artifact(
            "adversarial-envelope-aligned-v2.0.0-preprototype.json"
        )
        aligned = json.loads(path.read_text(encoding="utf-8"))
        cases = aligned.get("cases", [])
        assert cases, "aligned dataset contains no cases"
        for case in cases:
            evidence = case.get("adjudication_evidence", {})
            assert evidence.get("schema_commit") == SCHEMA_COMMIT, (
                f"case {case.get('id')} schema_commit drift"
            )
            assert evidence.get("schema_version") == SCHEMA_VERSION, (
                f"case {case.get('id')} schema_version drift"
            )

    def test_expected_packets_metadata_matches_frozen_bindings(self) -> None:
        path = require_private_eval_artifact(
            "adversarial-envelope-expected-packets-v2.0.0-preprototype.json"
        )
        packets = json.loads(path.read_text(encoding="utf-8")).get("expected_packets", {})
        assert packets, "expected packet fixture contains no packets"
        for case_id, packet in packets.items():
            assert packet.get("schema_version") == SCHEMA_VERSION, (
                f"packet {case_id} schema_version drift"
            )
