"""Offline action capability and parameter validation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def derive_capability_fields(input_fixture: Mapping[str, Any]) -> dict[str, str]:
    """Derive capability fields from request, registry, and schema only."""

    request_text = str(input_fixture.get("request_text", ""))
    registry = input_fixture.get("capability_registry", {})
    parameter_schema = input_fixture.get("parameter_schema", {})
    has_registry_match = isinstance(registry, Mapping) and any(bool(value) for value in registry.values())
    has_schema = isinstance(parameter_schema, Mapping) and bool(parameter_schema)

    capability_status = "pass" if request_text and has_registry_match else "fail"
    return {
        "capability_exists": capability_status,
        "capability_matches_purpose": capability_status,
        "parameters_identified": "pass" if has_schema else "fail",
    }


def derive_parameter_fields(input_fixture: Mapping[str, Any]) -> dict[str, str]:
    """Derive parameter fields from parsed parameters and capability signature."""

    parsed = input_fixture.get("parsed_parameters", {})
    signature = input_fixture.get("capability_signature", {})
    if not isinstance(parsed, Mapping) or not isinstance(signature, Mapping):
        return {"parameters_identified": "fail", "parameters_valid": "fail"}

    required_names = set(signature)
    identified = required_names.issubset(parsed)
    valid = identified and all(parsed.get(name) is not None for name in required_names)
    return {
        "parameters_identified": "pass" if identified else "fail",
        "parameters_valid": "pass" if valid else "fail",
    }


__all__ = ["derive_capability_fields", "derive_parameter_fields"]
