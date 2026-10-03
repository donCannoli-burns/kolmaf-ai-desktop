"""RelayWriter tests — fake-network, secrets, ambiguous outcome, single-writer."""

from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kolmafa import db
from kolmafa.config import get_settings
from kolmafa.bridge import CommandResult, RELAY_TRANSPORT
from kolmafa.confirmations import confirm_action
from kolmafa.devtest.action_broker import ActionBroker
from kolmafa.devtest.relay_writer import RelayWriter, OUTCOME_UNKNOWN_TOKEN


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "relaywriter.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "test_pwd_123")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    db.init_database(db_path)
    return db_path


def test_relay_writer_correct_request_construction(isolated_db, monkeypatch, tmp_path):
    captured = {}

    class FakeResp:
        status = 200

        def read(self):
            return b"ok response"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_opener(req, timeout=30):
        captured["url"] = req.full_url
        captured["method"] = req.method
        captured["data"] = req.data
        captured["headers"] = dict(req.headers)
        return FakeResp()

    broker = ActionBroker(writer=RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener))
    prop = broker.propose("adventure")
    assert prop["ok"]
    pid = prop["proposal_id"]
    from kolmafa import db as dbmod

    conn = dbmod.connect(get_settings().database_path)
    confirm_action(conn, pid)
    conn.close()
    out = broker.execute_approved(pid, expected_action="adventure")
    assert out["ok"] is True
    assert captured["url"].endswith("/sideCommand")
    assert captured["method"] == "POST"
    assert b"cmd=adventure" in captured["data"]
    assert b"SUPER_SECRET_RELAY_TOKEN" in captured["data"]
    assert "SUPER_SECRET_RELAY_TOKEN" not in str(out)
    assert out["transport"] == RELAY_TRANSPORT


def test_equip_payload_contains_complete_serialized_cmd(isolated_db):
    captured = {}

    class FakeResp:
        status = 200

        def read(self):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_opener(req, timeout=30):
        captured["data"] = req.data
        return FakeResp()

    args = {"item": "Ancient Saucehelm", "id": "153", "slot": "hat"}
    with patch("kolmafa.devtest.action_broker._get_current_hat_id", return_value="7783"):
        broker = ActionBroker(
            writer=RelayWriter(
                relay_base_url="http://localhost:60080",
                relay_pwd="test_pwd_123",
                opener=fake_opener,
            )
        )
        proposal = broker.propose("equip", args)
        assert proposal["ok"]
        conn = db.connect(get_settings().database_path)
        confirm_action(conn, proposal["proposal_id"])
        conn.close()
        result = broker.execute_approved(
            proposal["proposal_id"], expected_action="equip", expected_arguments=args
        )

    assert result["ok"] is True
    assert b"cmd=equip+hat+Ancient+Saucehelm" in captured["data"]
    assert b"cmd=equip&" not in captured["data"]


def test_use_payload_contains_complete_serialized_cmd(isolated_db):
    captured = {}

    class FakeResp:
        status = 200

        def read(self):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_opener(req, timeout=30):
        captured["data"] = req.data
        return FakeResp()

    args = {"item": "intriguing puzzle box", "id": "5054"}
    broker = ActionBroker(
        writer=RelayWriter(
            relay_base_url="http://localhost:60080",
            relay_pwd="test_pwd_123",
            opener=fake_opener,
        )
    )
    proposal = broker.propose("use", args)
    assert proposal["ok"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, proposal["proposal_id"])
    conn.close()
    result = broker.execute_approved(
        proposal["proposal_id"], expected_action="use", expected_arguments=args
    )

    assert result["ok"] is True
    assert b"cmd=use+1+intriguing+puzzle+box" in captured["data"]
    assert b"cmd=use&" not in captured["data"]


def test_relay_writer_t3_no_network_call(isolated_db, monkeypatch):
    calls = []

    def fake_opener(req, timeout=30):
        calls.append(req)
        raise AssertionError("should not be called for T3")

    broker = ActionBroker(writer=RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener))
    prop = broker.propose("kmail bob hello")
    assert prop["ok"] is False
    assert len(calls) == 0
    out = broker.execute_approved("nonexistent", expected_action="kmail bob hello")
    assert out["ok"] is False
    assert len(calls) == 0


def test_missing_confirmation_no_network(isolated_db, monkeypatch):
    calls = []

    def fake_opener(req, timeout=30):
        calls.append(req)
        return MagicMock()

    broker = ActionBroker(writer=RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener))
    prop = broker.propose("adventure")
    pid = prop["proposal_id"]
    out = broker.execute_approved(pid, expected_action="adventure")
    assert out["ok"] is False
    assert len(calls) == 0


def test_wrong_confirmation_no_network(isolated_db, monkeypatch):
    calls = []

    def fake_opener(req, timeout=30):
        calls.append(req)
        return MagicMock()

    broker = ActionBroker(writer=RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener))
    prop = broker.propose("adventure")
    pid = prop["proposal_id"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, pid)
    conn.close()
    out = broker.execute_approved(pid, expected_action="use")
    assert out["ok"] is False
    assert len(calls) == 0


def test_replayed_confirmation_only_one_network_call(isolated_db, monkeypatch):
    calls = []

    class FakeResp:
        status = 200

        def read(self):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_opener(req, timeout=30):
        calls.append(req)
        return FakeResp()

    broker = ActionBroker(writer=RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener))
    prop = broker.propose("adventure")
    pid = prop["proposal_id"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, pid)
    conn.close()
    out1 = broker.execute_approved(pid, expected_action="adventure")
    assert out1["ok"] is True
    out2 = broker.execute_approved(pid, expected_action="adventure")
    assert out2["ok"] is False
    assert len(calls) == 1


def test_network_failure_structured_no_retry(isolated_db, monkeypatch):
    def fake_opener(req, timeout=30):
        raise OSError("connection refused")

    broker = ActionBroker(writer=RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener))
    prop = broker.propose("adventure")
    pid = prop["proposal_id"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, pid)
    conn.close()
    out = broker.execute_approved(pid, expected_action="adventure")
    assert out["ok"] is False
    assert out["outcome"] == "failure" or "failed" in str(out).lower()
    out2 = broker.execute_approved(pid, expected_action="adventure")
    assert out2["ok"] is False


def test_ambiguous_result_outcome_unknown_no_retry(isolated_db, monkeypatch):
    def fake_opener(req, timeout=30):
        raise socket.timeout("timed out")

    broker = ActionBroker(writer=RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener))
    prop = broker.propose("adventure")
    pid = prop["proposal_id"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, pid)
    conn.close()
    out = broker.execute_approved(pid, expected_action="adventure")
    assert out["outcome"] == "OUTCOME_UNKNOWN"
    assert OUTCOME_UNKNOWN_TOKEN in out.get("stderr_preview", "") or OUTCOME_UNKNOWN_TOKEN in str(out)
    assert out["ok"] is False
    out2 = broker.execute_approved(pid, expected_action="adventure")
    assert out2["ok"] is False


def test_secret_redaction_in_writer_and_broker(monkeypatch, tmp_path):
    db_path = tmp_path / "secret.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "SUPER_SECRET_RELAY_TOKEN")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    db.init_database(db_path)

    class FakeResp:
        status = 200

        def read(self):
            return b"response with SUPER_SECRET_RELAY_TOKEN should be redacted"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_opener(req, timeout=30):
        return FakeResp()

    broker = ActionBroker(writer=RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener))
    prop = broker.propose("adventure")
    pid = prop["proposal_id"]
    conn = db.connect(db_path)
    confirm_action(conn, pid)
    conn.close()
    out = broker.execute_approved(pid, expected_action="adventure")
    assert "SUPER_SECRET_RELAY_TOKEN" not in str(out)
    assert "SUPER_SECRET_RELAY_TOKEN" not in out.get("stdout_preview", "")
    from pathlib import Path

    log_path = Path(__file__).resolve().parents[2] / "logs" / "don-evidence.jsonl"
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8", errors="replace")
        assert "SUPER_SECRET_RELAY_TOKEN" not in content
    assert "SUPER_SECRET_RELAY_TOKEN" not in prop.get("proposal_id", "")


def test_relay_writer_no_password_literal_in_source():
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest" / "relay_writer.py"
    text = src.read_text(encoding="utf-8")
    assert "SUPER_SECRET_RELAY_TOKEN" not in text
    assert "get_settings" in text
    assert "relay_pwd" in text


def test_single_writer_expanded():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest"
    for f in ["runtime.py", "mcp_server.py", "inspection.py"]:
        content = (root / f).read_text(encoding="utf-8")
        for line in content.splitlines():
            lower = line.lower()
            if "sidecommand" in lower and ("no " in lower or "not " in lower or "never" in lower or line.strip().startswith("#") or line.strip().startswith('"""') or line.strip().startswith("'''")):
                continue
            assert "sideCommand" not in line, f"{f} must not directly use sideCommand: {line}"
            assert "_execute_relay_side_command" not in line
        if f == "inspection.py":
            assert 'method="GET"' in content
    assert "sideCommand" in (root / "relay_writer.py").read_text()
    assert "writer.write" in (root / "action_broker.py").read_text()
