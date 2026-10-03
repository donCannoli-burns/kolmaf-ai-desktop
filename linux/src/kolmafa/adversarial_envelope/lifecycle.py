"""Pure offline proposal lifecycle derivation for adversarial envelopes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def derive_proposal_lifecycle(input_fixture: Mapping[str, Any]) -> dict[str, str]:
    """Derive proposal lifecycle without granting execution permission.

    The lifecycle layer is intentionally separate from confirmation and
    eligibility. It only reflects proposal support, presentation records, and
    invalidating lifecycle signals; it never reads runtime artifacts.
    """

    signals = _mapping(input_fixture.get("validity_signals"))
    confirmation = _mapping(input_fixture.get("confirmation"))
    presentation = _mapping(input_fixture.get("presentation"))

    if signals.get("proposal_expiry") is True:
        result = {"proposal_lifecycle": "expired"}
        if _is_confirmed_valid(confirmation):
            result["confirmation_status"] = "invalidated"
        return result

    if signals.get("superseded") is True or presentation.get("status") == "superseded":
        result = {"proposal_lifecycle": "superseded"}
        if _is_confirmed_valid(confirmation):
            result["confirmation_status"] = "invalidated"
        return result

    if input_fixture.get("proposal_support") != "supported":
        return {"proposal_lifecycle": "not_ready"}

    if presentation.get("status") == "presented":
        if _is_confirmed_valid(confirmation):
            return {"proposal_lifecycle": "confirmed"}
        return {"proposal_lifecycle": "presented"}

    return {"proposal_lifecycle": "ready_for_presentation"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_confirmed_valid(confirmation: Mapping[str, Any]) -> bool:
    return confirmation.get("status") == "confirmed" and confirmation.get("validity") == "valid"
