"""Allowlisted command-result marker tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from kolmafa import db
from kolmafa.bridge import CommandResult
from kolmafa.confirmations import confirm_action
from kolmafa.devtest.action_broker import ActionBroker
from kolmafa.devtest.mcp_server import handle_request_dict
from kolmafa.devtest.relay_writer import RelayWriter, command_result_marker
from kolmafa.devtest.runtime import DonRuntime
from kolmafa.config import get_settings


class FakeResponse:
    status = 200

    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def test_marker_parser_known_categories_fail_closed() -> None:
    assert command_result_marker("redirect to choice.php?whichchoice=525") == {
        "result_kind": "choice",
        "choice_id": 525,
    }
    assert command_result_marker("redirect: choice.php") == {
        "result_kind": "redirect",
        "redirect_path": "choice.php",
    }
    assert command_result_marker("Insufficient items to use.") == {
        "result_kind": "error",
        "error_class": "insufficient_items",
    }
    assert command_result_marker("You can't equip a Ancient Saucehelm.") == {
        "result_kind": "error",
        "error_class": "equip_restriction",
    }
    assert command_result_marker("\n") == {"result_kind": "unknown"}
    assert command_result_marker("<html>arbitrary body whichchoice=525&pwd=FAKE</html>") == {
        "result_kind": "choice",
        "choice_id": 525,
    }


def test_relay_writer_discards_raw_body_and_returns_marker() -> None:
    calls = []

    def opener(request, timeout=30):
        calls.append(request)
        return FakeResponse(
            b"<html>redirect to choice.php?whichchoice=525&pwd=FAKE_PASSWORD_DO_NOT_PRINT</html>"
        )

    writer = RelayWriter(
        relay_base_url="http://localhost:60080",
        relay_pwd="test-credential",
        opener=opener,
    )
    result = writer.write("use 1 intriguing puzzle box")
    assert len(calls) == 1
    assert result.result_marker == {"result_kind": "choice", "choice_id": 525}
    assert result.stdout == ""
    assert "FAKE_PASSWORD_DO_NOT_PRINT" not in str(result)


def test_action_broker_persists_marker_without_raw_output(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "marker.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "test-credential")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "test_player")
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    db.init_database(db_path)
    captured_evidence = []

    def fake_opener(request, timeout=30):
        return FakeResponse(b"redirect to choice.php?whichchoice=525")

    def capture_evidence(operation, mode, source, summary, **kwargs):
        captured_evidence.append(kwargs.get("extra", {}))

    monkeypatch.setattr("kolmafa.devtest.action_broker.record_evidence", capture_evidence)
    broker = ActionBroker(
        writer=RelayWriter(
            relay_base_url="http://localhost:60080",
            relay_pwd="test-credential",
            opener=fake_opener,
        )
    )
    args = {"item": "intriguing puzzle box", "id": "5054"}
    proposal = broker.propose("use", args)
    assert proposal["ok"] is True
    conn = db.connect(db_path)
    confirm_action(conn, proposal["proposal_id"])
    conn.close()
    result = broker.execute_approved(proposal["proposal_id"], expected_action="use", expected_arguments=args)
    assert result["ok"] is True
    assert result["command_result_marker"] == {"result_kind": "choice", "choice_id": 525}
    assert "stdout_preview" not in result
    conn = db.connect(db_path)
    row = conn.execute(
        "SELECT result_marker_json, stdout_redacted FROM command_log WHERE confirmation_id=?",
        (proposal["proposal_id"],),
    ).fetchone()
    conn.close()
    assert json.loads(row["result_marker_json"]) == {"result_kind": "choice", "choice_id": 525}
    assert row["stdout_redacted"] == ""
    assert captured_evidence
    assert any(item.get("command_result_marker", {}).get("choice_id") == 525 for item in captured_evidence)


def test_runtime_and_mcp_preserve_marker_shape(monkeypatch) -> None:
    marker = {"result_kind": "choice", "choice_id": 525}

    class StubBroker:
        def __init__(self, *args, **kwargs):
            pass

        def execute_approved(self, proposal_id, expected_action=None, expected_arguments=None):
            return {"ok": True, "command_result_marker": marker}

    monkeypatch.setattr("kolmafa.devtest.runtime.ActionBroker", StubBroker)
    assert DonRuntime().execute_approved("p")["command_result_marker"] == marker

    class StubRuntime:
        def execute_approved(self, proposal_id, expected_action=None, expected_arguments=None):
            return {"ok": True, "command_result_marker": marker}

    monkeypatch.setattr("kolmafa.devtest.mcp_server.DonRuntime", StubRuntime)
    response = handle_request_dict(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "don_execute_approved", "arguments": {"proposal_id": "p"}},
        }
    )
    assert response["result"]["content"][0]["json"]["command_result_marker"] == marker


def test_marker_is_observational_only(monkeypatch, tmp_path: Path) -> None:
    """A marker never creates a retry or second writer call."""
    db_path = tmp_path / "marker-replay.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "test-credential")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "test_player")
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    db.init_database(db_path)
    calls = []

    def fake_opener(request, timeout=30):
        calls.append(request)
        return FakeResponse(b"redirect to choice.php?whichchoice=525")

    broker = ActionBroker(writer=RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="test-credential", opener=fake_opener))
    args = {"item": "intriguing puzzle box", "id": "5054"}
    proposal = broker.propose("use", args)
    conn = db.connect(db_path)
    confirm_action(conn, proposal["proposal_id"])
    conn.close()
    first = broker.execute_approved(proposal["proposal_id"], expected_action="use", expected_arguments=args)
    second = broker.execute_approved(proposal["proposal_id"], expected_action="use", expected_arguments=args)
    assert first["command_result_marker"]["choice_id"] == 525
    assert second["ok"] is False
    assert len(calls) == 1
