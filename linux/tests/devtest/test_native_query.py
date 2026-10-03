"""Fixed native observation-query tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from kolmafa.devtest import native_query
from kolmafa.devtest.inspection import equipability_preflight
from kolmafa.devtest.native_query import (
    FakeNativeQueryTransport,
    NativeCanEquipRequest,
    NativeQueryError,
    NativeQueryRawResult,
    NativeQuerySpec,
    SideEffect,
    UnavailableNativeQueryTransport,
    capability_directory_entry,
    execute_native_can_equip,
    get_spec,
    normalize_can_equip,
    resolve_request,
)


def _grounded() -> dict:
    return {
        "ok": True,
        "equipment": {"hat": "11565"},
        "legacy_inventory": {"sample_candidates": [{"id": "153", "name": "Ancient Saucehelm", "count": 1}]},
    }


def test_registry_contains_only_reviewed_can_equip() -> None:
    spec = get_spec("native.can-equip")
    assert spec.native_function == "can_equip"
    assert spec.authority == "OBSERVATION_ONLY"
    assert spec.side_effects is SideEffect.OBSERVATION_ONLY
    with pytest.raises(NativeQueryError):
        get_spec("native.equip")
    with pytest.raises(NativeQueryError):
        get_spec("native.cli-execute")


def test_duplicate_and_non_observation_specs_rejected() -> None:
    with pytest.raises(NativeQueryError):
        native_query._register(
            NativeQuerySpec(
                capability_id="native.can-equip",
                native_function="can_equip",
                authority="OBSERVATION_ONLY",
                side_effects=SideEffect.OBSERVATION_ONLY,
                required_argument="item_id",
                result_type="boolean",
            )
        )
    with pytest.raises(NativeQueryError):
        NativeQuerySpec(
            capability_id="native.equip",
            native_function="equip",
            authority="OBSERVATION_ONLY",
            side_effects=SideEffect.GAME_MUTATING,
            required_argument="item_id",
            result_type="boolean",
        )
    with pytest.raises(NativeQueryError):
        NativeQuerySpec(
            capability_id="native.unknown-thing",
            native_function="something",
            authority="OBSERVATION_ONLY",
            side_effects=SideEffect.UNKNOWN,
            required_argument="item_id",
            result_type="boolean",
        )


def test_valid_and_invalid_item_ids() -> None:
    assert NativeCanEquipRequest(item_id=153).item_id == 153
    for bad in (0, -153, "153", 153.0, True, None):
        with pytest.raises(NativeQueryError):
            NativeCanEquipRequest(item_id=bad)


@pytest.mark.parametrize(
    "payload",
    [
        {"function": "can_equip", "args": [153]},
        {"capability": "native.equip", "arguments": {"item_id": 153}},
        {"capability": "native.cli-execute", "arguments": {"item_id": 153}},
        {"capability": "../../something", "arguments": {"item_id": 153}},
        {"capability": "can_equip; equip(...)", "arguments": {"item_id": 153}},
        {"capability": "can_equip(...)", "arguments": {"item_id": 153}},
        {"capability": "native.can-equip", "arguments": {"item_id": "153; equip(...)"}},
        {"capability": "native.can-equip", "arguments": {"item_id": 153, "code": "equip(...)"}},
        {"capability": "native.can-equip", "arguments": {"command": "equip hat Ancient Saucehelm"}},
        {"capability": "native.can-equip"},
        {"capability": "native.can-equip", "arguments": {"item_id": 153}, "extra": True},
    ],
)
def test_adversarial_requests_rejected_before_transport(payload: dict) -> None:
    with pytest.raises(NativeQueryError):
        resolve_request(payload)


def test_valid_mapping_resolves_to_typed_request() -> None:
    request = resolve_request({"capability": "native.can-equip", "arguments": {"item_id": 153}})
    assert request == NativeCanEquipRequest(item_id=153)


def test_fake_true_false_and_unavailable_normalization() -> None:
    fake = FakeNativeQueryTransport({153: True, 11565: False})
    assert execute_native_can_equip(153, transport=fake)["result"] is True
    assert execute_native_can_equip(11565, transport=fake)["result"] is False
    assert len(fake.calls) == 2
    unavailable = execute_native_can_equip(153, transport=UnavailableNativeQueryTransport())
    assert unavailable["ok"] is False
    assert unavailable["status"] == "NATIVE_QUERY_UNAVAILABLE"
    assert execute_native_can_equip(153)["status"] == "NATIVE_QUERY_UNAVAILABLE"


def test_malformed_and_failed_transports_fail_closed() -> None:
    assert normalize_can_equip(NativeQueryRawResult(True, "yes", None, "fake"), item_id=153)["status"] == "NATIVE_QUERY_UNAVAILABLE"
    live = normalize_can_equip(NativeQueryRawResult(True, True, None, "live", "Ancient Saucehelm"), item_id=153)
    assert live["status"] == "SUCCESS"
    assert live["freshness"] == "LIVE"
    assert normalize_can_equip(NativeQueryRawResult(True, True, None, "fake"), item_id=153)["status"] == "SUCCESS"

    class FailingTransport:
        def query(self, request):
            raise TimeoutError("fake native transport unavailable")

    failed = execute_native_can_equip(153, transport=FailingTransport())
    assert failed["ok"] is False
    assert failed["result"] is None
    assert failed["status"] == "NATIVE_QUERY_UNAVAILABLE"


def test_preflight_integration_preserves_fail_closed_default() -> None:
    unavailable = execute_native_can_equip(153, transport=UnavailableNativeQueryTransport())
    preserved = equipability_preflight(_grounded(), item_id=153, slot="hat")
    integrated_unknown = equipability_preflight(_grounded(), item_id=153, slot="hat", native_query=unavailable)
    assert preserved["result"] == "UNKNOWN"
    assert integrated_unknown["result"] == "UNKNOWN"

    fake_true = execute_native_can_equip(153, transport=FakeNativeQueryTransport({153: True}))
    true_result = equipability_preflight(_grounded(), item_id=153, slot="hat", native_query=fake_true)
    assert true_result["result"] == "EQUIPPABLE"
    assert true_result["can_equip"] is True
    assert true_result["restriction_class"] == "NONE"

    fake_false = execute_native_can_equip(153, transport=FakeNativeQueryTransport({153: False}))
    false_result = equipability_preflight(_grounded(), item_id=153, slot="hat", native_query=fake_false)
    assert false_result["result"] == "BLOCKED"
    assert false_result["can_equip"] is False
    assert false_result["restriction_class"] == "NATIVE_CAN_EQUIP_FALSE"

    malformed = {"capability": "native.can-equip", "authority": "OBSERVATION_ONLY", "status": "SUCCESS", "result": "yes"}
    assert equipability_preflight(_grounded(), item_id=153, slot="hat", native_query=malformed)["result"] == "UNKNOWN"


def test_no_mutation_or_network_surface() -> None:
    path = Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest" / "native_query.py"
    text = path.read_text(encoding="utf-8")
    for forbidden in (
        "ActionBroker",
        "RelayWriter",
        "ConfirmationStore",
        "confirm_action",
        "propose",
        "consume",
        "urlopen",
        "sideCommand",
        "POST",
        "socket",
        "subprocess",
    ):
        assert forbidden not in text


def test_capability_directory_metadata_is_observation_only() -> None:
    entry = capability_directory_entry()
    assert entry["id"] == "native.can-equip"
    assert entry["native_owner"] == "KoLmafia"
    assert entry["adapter_owner"] == "Don"
    assert entry["authority"] == "OBSERVATION_ONLY"
    assert entry["availability"] == "REGISTERED_BUT_TRANSPORT_UNAVAILABLE"
    assert entry["transport"] == {
        "type": "fixed-relay-get",
        "method": "GET",
        "caller_controls_destination": False,
        "caller_controls_function": False,
        "caller_controls_code": False,
    }
