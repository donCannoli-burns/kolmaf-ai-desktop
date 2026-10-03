"""T1 live-read receipt tests (offline, fake network, temp journals)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from kolmafa.devtest.inspection import equipability_preflight
from kolmafa.devtest.native_query import FakeNativeQueryTransport, execute_native_can_equip
from kolmafa.devtest.native_relay import KoLmafiaCanEquipTransport


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


def _success_body(value: bool = True) -> bytes:
    return json.dumps(
        {
            "schema": "kolmaf-native-can-equip-v1",
            "ok": True,
            "item_id": 153,
            "item_name": "Ancient Saucehelm",
            "can_equip": value,
        }
    ).encode()


def _read_journal(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_success_appends_one_allowlisted_receipt(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    calls: list = []

    def opener(request, timeout=10.0):
        calls.append(request)
        return FakeResponse(_success_body())

    result = execute_native_can_equip(
        153, transport=KoLmafiaCanEquipTransport(opener=opener, evidence_path=journal)
    )
    assert result["status"] == "SUCCESS"
    assert result["result"] is True
    events = _read_journal(journal)
    assert len(events) == 1
    event = events[0]
    assert event["operation"] == "native.can-equip"
    assert event["extra"] == {
        "capability": "native.can-equip",
        "item_id": 153,
        "result": True,
        "result_status": "SUCCESS",
        "transport": "fixed-relay-get",
    }
    assert len(calls) == 1
    evidence = result["evidence"]
    assert evidence["event_id"] == event["event_id"]
    assert evidence["timestamp"] == event["timestamp"]
    assert evidence["status"] == "RECORDED"
    datetime.fromisoformat(event["timestamp"])


def test_false_result_receipt_appended(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    result = execute_native_can_equip(
        153,
        transport=KoLmafiaCanEquipTransport(
            opener=lambda request, timeout=10.0: FakeResponse(_success_body(value=False)),
            evidence_path=journal,
        ),
    )
    assert result["result"] is False
    events = _read_journal(journal)
    assert len(events) == 1
    assert events[0]["extra"]["result"] is False
    assert result["evidence"]["status"] == "RECORDED"


def test_transport_error_receipt_without_retry(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    calls: list = []

    def opener(request, timeout=10.0):
        calls.append(request)
        raise TimeoutError("fake outage")

    result = execute_native_can_equip(
        153, transport=KoLmafiaCanEquipTransport(opener=opener, evidence_path=journal)
    )
    assert result["status"] == "NATIVE_QUERY_UNAVAILABLE"
    assert len(calls) == 1
    events = _read_journal(journal)
    assert len(events) == 1
    assert events[0]["extra"]["result_status"] == "TRANSPORT_ERROR"
    assert result["evidence"]["status"] == "RECORDED"


def test_schema_error_receipt(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    result = execute_native_can_equip(
        153,
        transport=KoLmafiaCanEquipTransport(
            opener=lambda request, timeout=10.0: FakeResponse(b"<html>nope</html>"),
            evidence_path=journal,
        ),
    )
    events = _read_journal(journal)
    assert len(events) == 1
    assert events[0]["extra"]["result_status"] == "SCHEMA_ERROR"
    assert result["evidence"]["status"] == "RECORDED"


def test_journal_write_failure_is_explicit_and_never_retries(tmp_path: Path) -> None:
    calls: list = []

    def opener(request, timeout=10.0):
        calls.append(request)
        return FakeResponse(_success_body())

    result = execute_native_can_equip(
        153, transport=KoLmafiaCanEquipTransport(opener=opener, evidence_path=tmp_path)
    )
    assert result["status"] == "SUCCESS"
    assert result["result"] is True
    assert len(calls) == 1
    assert result["evidence"]["status"] == "WRITE_FAILED"
    assert "error_class" in result["evidence"]


def test_receipt_carries_no_secret_or_raw_body(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    secret = "SUPER_SECRET_RELAY_TOKEN"
    body = (
        b'{"schema":"kolmaf-native-can-equip-v1","ok":true,"item_id":153,'
        b'"item_name":"Ancient Saucehelm","can_equip":true,' + secret.encode() + b"}"
    )
    # Trailing secret bytes make the body malformed; the receipt must still be clean.
    result = execute_native_can_equip(
        153,
        transport=KoLmafiaCanEquipTransport(
            opener=lambda request, timeout=10.0: FakeResponse(body), evidence_path=journal
        ),
    )
    text = journal.read_text(encoding="utf-8") + json.dumps(result)
    assert secret not in text
    assert "Ancient Saucehelm" not in journal.read_text(encoding="utf-8")


def test_event_ids_unique_and_timestamps_parse(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"

    def opener(request, timeout=10.0):
        return FakeResponse(_success_body())

    first = execute_native_can_equip(153, transport=KoLmafiaCanEquipTransport(opener=opener, evidence_path=journal))
    second = execute_native_can_equip(153, transport=KoLmafiaCanEquipTransport(opener=opener, evidence_path=journal))
    assert first["evidence"]["event_id"] != second["evidence"]["event_id"]
    for event in _read_journal(journal):
        assert len(event["event_id"]) == 32
        datetime.fromisoformat(event["timestamp"])


def test_fake_transport_writes_no_receipt() -> None:
    result = execute_native_can_equip(153, transport=FakeNativeQueryTransport({153: True}))
    assert result["evidence"] is None


def test_preflight_surfaces_receipt_pointer(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    grounded = {
        "ok": True,
        "equipment": {"hat": "11565"},
        "legacy_inventory": {"sample_candidates": [{"id": "153", "name": "Ancient Saucehelm", "count": 1}]},
    }
    native = execute_native_can_equip(
        153, transport=KoLmafiaCanEquipTransport(
            opener=lambda request, timeout=10.0: FakeResponse(_success_body()), evidence_path=journal
        ),
    )
    preflight = equipability_preflight(grounded, item_id=153, slot="hat", native_query=native)
    assert preflight["result"] == "EQUIPPABLE"
    assert preflight["evidence"]["event_id"] == native["evidence"]["event_id"]
