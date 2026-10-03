"""Fixed live-transport tests for native.can-equip (offline, fake network)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kolmafa.devtest import native_relay
from kolmafa.devtest.inspection import equipability_preflight
from kolmafa.devtest.native_query import NativeQueryError, execute_native_can_equip
from kolmafa.devtest.native_relay import (
    HELPER_FILENAME,
    HELPER_PATH,
    KoLmafiaCanEquipTransport,
    helper_sha256,
    install_helper,
)


HELPER_PATH_LOCAL = Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest" / "relay" / HELPER_FILENAME

ALLOWED_HELPER_CALLS = frozenset(
    {"main", "if", "form_field", "length", "is_integer", "to_int", "to_item", "can_equip", "to_string", "write"}
)


@pytest.fixture(autouse=True)
def block_real_native_network(monkeypatch):
    def blocked(request, timeout=10.0):
        raise AssertionError("real native-query network is blocked under pytest; inject a fake opener")

    monkeypatch.setattr(native_relay, "urlopen", blocked)
    yield


class FakeResponse:
    status = 200

    def __init__(self, body: bytes):
        self._body = body

    def read(self, limit: int = -1) -> bytes:
        return self._body if limit is None or limit < 0 else self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _success_body(item_id: int = 153, name: str = "Ancient Saucehelm", value: bool = True) -> bytes:
    return json.dumps(
        {
            "schema": "kolmaf-native-can-equip-v1",
            "ok": True,
            "item_id": item_id,
            "item_name": name,
            "can_equip": value,
        }
    ).encode()


def _grounded() -> dict:
    return {
        "ok": True,
        "equipment": {"hat": "11565"},
        "legacy_inventory": {"sample_candidates": [{"id": "153", "name": "Ancient Saucehelm", "count": 1}]},
    }


def test_helper_source_is_single_operation_allowlist() -> None:
    text = HELPER_PATH_LOCAL.read_text(encoding="utf-8")
    assert text.count("void main") == 1
    assert len(re.findall(r"\bvoid\s+[A-Za-z_][A-Za-z0-9_]*\s*\(", text)) == 1
    calls = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", text))
    assert calls <= ALLOWED_HELPER_CALLS, f"unexpected helper calls: {sorted(calls - ALLOWED_HELPER_CALLS)}"
    assert "kolmaf-native-can-equip-v1" in text
    assert "INVALID_ITEM_ID" in text and "UNKNOWN_ITEM" in text


def test_helper_source_denies_mutation_and_evaluation() -> None:
    text = HELPER_PATH_LOCAL.read_text(encoding="utf-8")
    lowered = text.casefold()
    for pattern in (
        r"(?<![a-z_])equip\s*\(",
        r"(?<![a-z_])use\s*\(",
        r"cli_execute",
        r"visit_url",
        r"run_choice",
        r"retrieve_item",
        r"\bbuy\s*\(",
        r"adventure",
        r"attack",
        r"\bchat\s*\(",
        r"kmail",
        r"\bsend\s*\(",
        r"stash",
        r"put_closet",
        r"take_closet",
        r"create_matcher",
        r"\beval\b",
        r"\bimport\b",
    ):
        assert re.search(pattern, lowered) is None, f"helper must not contain: {pattern}"
    # can_equip itself must remain present and is the only equip-adjacent call.
    assert "can_equip(" in text


def test_transport_url_method_fixed_and_typed_only(monkeypatch) -> None:
    captured: dict = {}

    def opener(request, timeout=10.0):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        return FakeResponse(_success_body())

    transport = KoLmafiaCanEquipTransport(opener=opener)
    result = execute_native_can_equip(153, transport=transport)
    assert captured["method"] == "GET"
    assert captured["url"].endswith(HELPER_PATH + "?relay=true&item_id=153")
    assert ".." not in captured["url"] and "function" not in captured["url"]
    assert result["status"] == "SUCCESS"
    assert result["result"] is True
    assert result["transport"] == "live"
    assert result["freshness"] == "LIVE"
    assert len(transport.calls) == 1


def test_transport_rejects_untyped_request_before_network() -> None:
    opener_calls: list = []

    def opener(request, timeout=10.0):
        opener_calls.append(request)
        raise AssertionError("must not reach network")

    transport = KoLmafiaCanEquipTransport(opener=opener)
    with pytest.raises(NativeQueryError):
        transport.query("native.can-equip")  # type: ignore[arg-type]
    with pytest.raises(NativeQueryError):
        transport.query({"capability": "native.can-equip"})  # type: ignore[arg-type]
    assert opener_calls == []


def test_transport_default_opener_blocked_under_pytest() -> None:
    transport = KoLmafiaCanEquipTransport()
    result = execute_native_can_equip(153, transport=transport)
    assert result["status"] == "NATIVE_QUERY_UNAVAILABLE"
    assert result["result"] is None


@pytest.mark.parametrize(
    "body, expected",
    [
        (_success_body(value=False), (True, False)),
        (
            json.dumps({"schema": "kolmaf-native-can-equip-v1", "ok": False, "item_id": 999999, "error": "UNKNOWN_ITEM"}).encode(),
            (False, "UNKNOWN_ITEM"),
        ),
        (
            json.dumps({"schema": "kolmaf-native-can-equip-v1", "ok": False, "item_id": 0, "error": "INVALID_ITEM_ID"}).encode(),
            (False, "INVALID_ITEM_ID"),
        ),
    ],
)
def test_helper_response_contracts(body: bytes, expected: tuple) -> None:
    transport = KoLmafiaCanEquipTransport(opener=lambda request, timeout=10.0: FakeResponse(body))
    result = execute_native_can_equip(999999 if expected[1] == "UNKNOWN_ITEM" else 153, transport=transport)
    if expected[0]:
        assert result["status"] == "SUCCESS"
        assert result["result"] is expected[1]
    else:
        assert result["status"] == "NATIVE_QUERY_UNAVAILABLE"


@pytest.mark.parametrize(
    "body",
    [
        b"<html>not json</html>",
        b"\xff\xfe invalid",
        json.dumps([1, 2, 3]).encode(),
        json.dumps({"schema": "wrong", "ok": True, "item_id": 153, "item_name": "x", "can_equip": True}).encode(),
        json.dumps({"schema": "kolmaf-native-can-equip-v1", "ok": True, "item_id": 154, "item_name": "x", "can_equip": True}).encode(),
        json.dumps({"schema": "kolmaf-native-can-equip-v1", "ok": True, "item_id": 153, "item_name": "x", "can_equip": "yes"}).encode(),
        json.dumps({"schema": "kolmaf-native-can-equip-v1", "ok": True, "item_id": 153, "item_name": "x", "can_equip": True, "extra": 1}).encode(),
        json.dumps({"schema": "kolmaf-native-can-equip-v1", "ok": False, "item_id": 153, "error": "SOMETHING_ELSE"}).encode(),
        b"x" * 9000,
    ],
)
def test_helper_malformed_responses_fail_closed(body: bytes) -> None:
    transport = KoLmafiaCanEquipTransport(opener=lambda request, timeout=10.0: FakeResponse(body))
    result = execute_native_can_equip(153, transport=transport)
    assert result["status"] == "NATIVE_QUERY_UNAVAILABLE"
    assert result["result"] is None


def test_live_preflight_integration_reports_native_answer() -> None:
    live_true = execute_native_can_equip(
        153, transport=KoLmafiaCanEquipTransport(opener=lambda request, timeout=10.0: FakeResponse(_success_body(value=True)))
    )
    assert equipability_preflight(_grounded(), item_id=153, slot="hat", native_query=live_true)["result"] == "EQUIPPABLE"

    live_false = execute_native_can_equip(
        153, transport=KoLmafiaCanEquipTransport(opener=lambda request, timeout=10.0: FakeResponse(_success_body(value=False)))
    )
    blocked = equipability_preflight(_grounded(), item_id=153, slot="hat", native_query=live_false)
    assert blocked["result"] == "BLOCKED"
    assert blocked["restriction_class"] == "NATIVE_CAN_EQUIP_FALSE"

    renamed = execute_native_can_equip(
        153, transport=KoLmafiaCanEquipTransport(opener=lambda request, timeout=10.0: FakeResponse(_success_body(name="Something Else")))
    )
    assert equipability_preflight(_grounded(), item_id=153, slot="hat", native_query=renamed)["result"] == "UNKNOWN"


def test_installer_projects_canonical_bytes_verbatim(monkeypatch, tmp_path: Path) -> None:
    relay_dir = tmp_path / "relay"
    relay_dir.mkdir()
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path))
    before = sorted(path.name for path in relay_dir.iterdir())
    record = install_helper()
    after = sorted(path.name for path in relay_dir.iterdir())
    assert after == before + [HELPER_FILENAME]
    assert record["sha256"] == helper_sha256()
    assert Path(record["installed_projection"]).read_bytes() == HELPER_PATH_LOCAL.read_bytes()


def test_installer_fails_closed_without_relay_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "missing-home"))
    with pytest.raises(NativeQueryError):
        install_helper()


def test_transport_module_has_no_mutation_surface() -> None:
    text = (Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest" / "native_relay.py").read_text(encoding="utf-8")
    assert 'method="GET"' in text
    for forbidden in ("POST", "sideCommand", "ActionBroker", "RelayWriter", "confirm_action", "cli_execute", "visit_url"):
        assert forbidden not in text


def test_live_transport_cannot_touch_mutation_path(monkeypatch) -> None:
    import kolmafa.devtest.action_broker as broker_module
    import kolmafa.devtest.relay_writer as writer_module

    monkeypatch.setattr(broker_module.ActionBroker, "execute_approved", staticmethod(lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("broker touched"))))
    monkeypatch.setattr(writer_module.RelayWriter, "write", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("writer touched")))
    transport = KoLmafiaCanEquipTransport(opener=lambda request, timeout=10.0: FakeResponse(_success_body()))
    assert execute_native_can_equip(153, transport=transport)["result"] is True
