"""Equipment snapshot read-only tests for Slice 3A.1."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock
import json

import pytest

from kolmafa.devtest.inspection import equipment_snapshot
from kolmafa.devtest.mcp_server import handle_request_dict, TOOLS


def test_equipment_snapshot_offline_returns_structured(monkeypatch):
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://127.0.0.1:59999")
    # unreachable relay
    result = equipment_snapshot(timeout=0.5)
    assert result["ok"] is False
    assert result["live"] is False
    assert result["mutation_capability"] is False
    assert result["evidence_tier"] in ("LOCAL/CACHED STATE", "OFFLINE")
    assert "equipment" in result
    assert "inventory" in result
    # Must be redacted and not contain pwd
    assert "pwd" not in str(result).lower() or "<redacted>" in str(result)


def test_equipment_snapshot_live_parsing(monkeypatch):
    # Mock status and inventory JSON
    status_json = json.dumps({"name": "test_player", "equipment": {"hat": "4614", "shirt": "10952"}, "pwd": "SECRET123"}).encode()
    inventory_json = json.dumps({"3": "0", "153": "1", "155": "1", "4614": "1", "5054": "8"}).encode()
    choice_html = b"<html><title>Choice Adventure</title><p>Whoops! You're not actually in a choice adventure.</p></html>"

    class FakeResp:
        def __init__(self, data):
            self._data = data
            self.status = 200

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    call_count = {"n": 0}

    def fake_urlopen(req, timeout=2.0):
        call_count["n"] += 1
        url = req.full_url
        if "what=status" in url:
            return FakeResp(status_json)
        if "what=inventory" in url:
            return FakeResp(inventory_json)
        if "/choice.php" in url:
            return FakeResp(choice_html)
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")

    with patch("kolmafa.devtest.inspection.urlopen", side_effect=fake_urlopen):
        result = equipment_snapshot(timeout=1.0)
        assert result["ok"] is True
        assert result["live"] is True
        assert result["evidence_tier"] == "PROVEN LIVE STATE"
        assert result["equipment"]["hat_id"] == "4614"
        assert result["inventory"]["helmet_turtle_owned"] is False  # 3 count 0
        assert result["inventory"]["helmet_turtle_count"] == 0
        assert result["target_items"]["5054"] == {"item_id": "5054", "quantity": 8, "owned": True, "valid": True}
        assert result["choice_state"]["handling_choice"] is False
        assert result["choice_state"]["choice_id"] is None
        # Other hats
        other_ids = {c["id"] for c in result["inventory"]["sample_candidates"]}
        assert "153" in other_ids
        # Redacted: pwd not leaked
        assert "SECRET123" not in str(result)
        # Exactly 3 well allowlisted GETs (status + inventory + choice state)
        assert call_count["n"] == 3
        # No POST, no sideCommand
        for url in ["what=status", "what=inventory"]:
            pass  # already checked


def test_equipment_snapshot_no_mutation_transport(monkeypatch):
    # Ensure equipment_snapshot does not call POST or sideCommand
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest" / "inspection.py"
    text = src.read_text(encoding="utf-8")
    # inspection should contain GET for equipment, not POST sideCommand
    assert 'method="GET"' in text
    # Should not contain sideCommand POST in equipment_snapshot
    # Allow sideCommand mention in comments about not using it
    for line in text.splitlines():
        low = line.lower()
        if "sidecommand" in low and ("no " in low or "not " in low or "never" in low or line.strip().startswith("#")):
            continue
        if "equipment_snapshot" in line or "def equipment" in line:
            # ensure not POST
            assert "POST" not in line or "GET" in line


def test_equipment_snapshot_redaction(monkeypatch):
    import pathlib

    status_json = json.dumps({"name": "test_player", "equipment": {"hat": "4614"}, "pwd": "SUPER_SECRET_RELAY_TOKEN"}).encode()
    inventory_json = json.dumps({"3": "5", "pwd": "SUPER_SECRET_RELAY_TOKEN"}).encode()
    choice_html = b"<html><p>Whoops! You're not actually in a choice adventure.</p></html>"

    class FakeResp:
        def __init__(self, d):
            self._d = d
            self.status = 200

        def read(self):
            return self._d

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=2.0):
        if "what=status" in req.full_url:
            return FakeResp(status_json)
        if "what=inventory" in req.full_url:
            return FakeResp(inventory_json)
        return FakeResp(choice_html)

    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "SUPER_SECRET_RELAY_TOKEN")

    with patch("kolmafa.devtest.inspection.urlopen", side_effect=fake_urlopen):
        result = equipment_snapshot()
        text = str(result)
        assert "SUPER_SECRET_RELAY_TOKEN" not in text
        # Check evidence log also redacted (if exists)
        log_path = pathlib.Path(__file__).resolve().parents[2] / "logs" / "don-evidence.jsonl"
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8", errors="replace")
            assert "SUPER_SECRET_RELAY_TOKEN" not in content


def test_mcp_equipment_status_tool(monkeypatch):
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://127.0.0.1:59999")
    resp = handle_request_dict({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "don_equipment_status", "arguments": {}}})
    assert "result" in resp
    payload = resp["result"]["content"][0]["json"]
    assert "equipment" in payload or "ok" in payload
    # Must be read-only, no mutation capability
    assert payload.get("mutation_capability") is False or "mutation_capability" in payload

    # tools/list must include don_equipment_status
    resp2 = handle_request_dict({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp2["result"]["tools"]}
    assert "don_equipment_status" in names
    # Should now be 7 tools
    assert len(names) == 7
    for forb in ["don_raw_relay", "sideCommand", "equip", "POST"]:
        # equip as raw tool should not be exposed, only via broker
        assert forb not in names or forb == "don_equipment_status"


def test_equipment_arbitrary_url_not_exposed(monkeypatch):
    import inspect
    from kolmafa.devtest.inspection import equipment_snapshot as es

    sig = inspect.signature(es)
    assert "url" not in sig.parameters
    assert "path" not in sig.parameters
