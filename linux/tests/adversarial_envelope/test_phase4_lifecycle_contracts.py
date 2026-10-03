"""Phase 4 failing TDD contracts for lifecycle and binding rows LC01-LC38."""

from __future__ import annotations

import pytest

from phase4_contract_helpers import (
    ContractCase,
    assert_phase4_contract_behavior,
    load_contracts,
    verify_frozen_bindings,
)


CONTRACTS = load_contracts()


@pytest.mark.parametrize(
    "contract",
    [pytest.param(contract, id=contract.pytest_id) for contract in CONTRACTS],
)
def test_phase4_lifecycle_contract(contract: ContractCase) -> None:
    """Failing contract: frozen bindings first, then frozen LC behavior."""

    verify_frozen_bindings()
    assert_phase4_contract_behavior(contract)
