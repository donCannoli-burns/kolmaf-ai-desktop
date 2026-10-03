"""MCP broker tools contract tests."""

from __future__ import annotations

from pathlib import Path

from kolmafa.devtest import runtime as _runtime
from kolmafa.devtest.mcp_server import handle_request_dict, TOOLS
from kolmafa import db
from kolmafa.config import get_settings
from kolmafa.confirmations import confirm_action


def test_mcp_propose_and_execute_flow(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "mcp_broker.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    db.init_database(db_path)

    # Propose via MCP
    resp = handle_request_dict(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "don_propose_action", "arguments": {"action": "adventure"}}}
    )
    assert "result" in resp
    payload = resp["result"]["content"][0]["json"]
    assert payload["ok"] is True
    pid = payload["proposal_id"]

    # Execute without confirm should deny
    resp2 = handle_request_dict(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "don_execute_approved", "arguments": {"proposal_id": pid, "expected_action": "adventure"}}}
    )
    assert "result" in resp2
    assert resp2["result"]["content"][0]["json"]["ok"] is False

    # Confirm via durable store
    conn = db.connect(db_path)
    confirm_action(conn, pid)
    conn.close()

    # Execute after confirm should succeed (DryRun)
    resp3 = handle_request_dict(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "don_execute_approved", "arguments": {"proposal_id": pid, "expected_action": "adventure"}}}
    )
    payload3 = resp3["result"]["content"][0]["json"]
    assert payload3["ok"] is True
    assert payload3["execution_performed"] is False
    assert payload3["transport"] == "gcli-dry-run"


def test_mcp_t3_via_propose_is_denied(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "t3.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    db.init_database(db_path)
    resp = handle_request_dict(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "don_propose_action", "arguments": {"action": "kmail bob hello"}}}
    )
    payload = resp["result"]["content"][0]["json"]
    assert payload["ok"] is False
    assert "T3" in payload.get("error", "") or payload["classification"] == "unsafe_unknown"


def test_mcp_tools_list_now_has_six(monkeypatch):
    resp = handle_request_dict({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    expected = {"don_status", "don_context_search", "don_session_status", "don_relay_snapshot", "don_equipment_status", "don_propose_action", "don_execute_approved"}
    assert expected.issubset(names)
    assert expected == names  # exactly 7 after Slice 3A.1 (was 6 after Slice 2B)
    for forbidden in ["raw_cli", "raw_relay", "arbitrary_ash", "browser_navigate", "gcli_send", "relay_sideCommand"]:
        assert forbidden not in names


def test_mcp_execute_dry_run_never_resolves_live_writer(monkeypatch, tmp_path: Path):
    """Machine check: even with live-relay env flag set, the MCP execute path
    must inject a DryRunGcliWriter, never a RelayWriter."""
    db_path = tmp_path / "mcp_writer_selection.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    monkeypatch.setenv("KOLMAFA_LIVE_RELAY_ENABLED", "true")
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    db.init_database(db_path)

    captured = {}
    original_broker = _runtime.ActionBroker

    class SpyBroker(original_broker):
        def __init__(self, writer=None, **kwargs):
            captured["writer_class"] = type(writer).__name__ if writer is not None else None
            super().__init__(writer=writer, **kwargs)

    monkeypatch.setattr(_runtime, "ActionBroker", SpyBroker)

    resp = handle_request_dict(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "don_propose_action", "arguments": {"action": "adventure"}}}
    )
    pid = resp["result"]["content"][0]["json"]["proposal_id"]
    conn = db.connect(db_path)
    confirm_action(conn, pid)
    conn.close()

    resp2 = handle_request_dict(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "don_execute_approved", "arguments": {"proposal_id": pid, "expected_action": "adventure"}}}
    )
    payload = resp2["result"]["content"][0]["json"]
    assert payload["ok"] is True
    assert payload["transport"] == "gcli-dry-run"
    assert payload["execution_performed"] is False
    assert captured["writer_class"] == "DryRunGcliWriter"
