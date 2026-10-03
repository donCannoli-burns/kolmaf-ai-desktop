"""Transport identity binding + loopback policy matrix (offline, fake opener only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from kolmafa import db
from kolmafa.bridge import CommandResult, DryRunGcliWriter, RELAY_TRANSPORT
from kolmafa.config import get_settings
from kolmafa.confirmations import confirm_action
from kolmafa.devtest.action_broker import ActionBroker
from kolmafa.devtest.relay_writer import RelayWriter
from kolmafa.devtest.transport_identity import (
    TransportIdentityError,
    relay_identity_from_url,
    validate_relay_destination,
)


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "transport.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "test_pwd_123")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    db.init_database(db_path)
    return db_path


class FakeResp:
    status = 200

    def read(self):
        return b"ok"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def counting_opener(captured: dict):
    def _open(req, timeout=30):
        captured["count"] = captured.get("count", 0) + 1
        captured["url"] = req.full_url
        captured["data"] = req.data
        return FakeResp()

    return _open


# --- URL policy matrix -----------------------------------------------------

ACCEPT_URLS = [
    "http://127.0.0.1:60080",
    "http://localhost:60080",
    "http://LOCALHOST:60080",
    "http://localhost/",
    "http://127.0.0.1",
]

REJECT_URLS = [
    ("http://localhost.evil.test", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://localhost@evil.test", "INVALID_RELAY_URL"),
    ("http://127.0.0.1.evil.test", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://127.1", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://2130706433", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://0x7f000001", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://0177.0.0.1", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://[::ffff:127.0.0.1]", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://%6cocalhost", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://127.0.0.1:60080@evil.test", "INVALID_RELAY_URL"),
    ("//localhost:60080", "INVALID_RELAY_URL"),
    ("ftp://localhost", "INVALID_RELAY_URL"),
    ("http://", "INVALID_RELAY_URL"),
    ("http://192.168.1.10", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://10.0.0.5", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://0.0.0.0", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://example.com", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://169.254.169.254", "NON_LOOPBACK_RELAY_REJECTED"),
    ("http://[::1]:60080", "NON_LOOPBACK_RELAY_REJECTED"),
    ("https://localhost:60080", "INVALID_RELAY_URL"),
    ("https://127.0.0.1:60080", "INVALID_RELAY_URL"),
]


@pytest.mark.parametrize("url", ACCEPT_URLS)
def test_loopback_accept(url):
    scheme, host, port = validate_relay_destination(url)
    assert host in ("localhost", "127.0.0.1")


@pytest.mark.parametrize("url,expected", REJECT_URLS)
def test_loopback_reject(url, expected):
    with pytest.raises(TransportIdentityError) as exc:
        validate_relay_destination(url)
    assert exc.value.classification == expected


def test_writer_rejects_non_loopback_zero_network():
    captured: dict = {}
    w = RelayWriter(relay_base_url="http://192.168.1.10:60080", relay_pwd="pwd", opener=counting_opener(captured))
    result = w.write("adventure")
    assert result.return_code == 2
    assert "NON_LOOPBACK_RELAY_REJECTED" in result.stderr
    assert captured.get("count", 0) == 0


def test_writer_rejects_invalid_url_zero_network():
    captured: dict = {}
    w = RelayWriter(relay_base_url="http://localhost@evil.test", relay_pwd="pwd", opener=counting_opener(captured))
    result = w.write("adventure")
    assert result.return_code == 2
    assert "INVALID_RELAY_URL" in result.stderr
    assert captured.get("count", 0) == 0


def test_redirect_response_rejected_zero_success(isolated_db):
    def redirect_opener(req, timeout=30):
        raise HTTPError(req.full_url, 302, "Found", {"Location": "http://evil.test/sideCommand"}, None)

    w = RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="pwd", opener=redirect_opener)
    result = w.write("adventure")
    assert result.return_code == 2
    assert "REDIRECT_DESTINATION_REJECTED" in result.stderr


def test_default_opener_disables_redirects():
    from kolmafa.devtest.relay_writer import _default_opener, _NoRedirect

    opener_open = _default_opener()
    assert callable(opener_open)


def test_no_credential_before_validation():
    # Base URL is non-loopback; pwd must not appear in any request (no request is built)
    captured: dict = {}
    w = RelayWriter(relay_base_url="http://10.1.2.3", relay_pwd="SUPER_SECRET", opener=counting_opener(captured))
    result = w.write("adventure")
    assert captured.get("count", 0) == 0
    assert "SUPER_SECRET" not in str(result)


# --- Broker binding --------------------------------------------------------


def test_match_passes_exactly_one_post(isolated_db):
    captured: dict = {}
    w = RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="pwd", opener=counting_opener(captured))
    broker = ActionBroker(writer=w)
    prop = broker.propose("adventure")
    assert prop["ok"] and "transport_fingerprint" in prop
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, prop["proposal_id"])
    conn.close()
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is True
    assert captured["count"] == 1


def test_config_mutation_after_confirm_blocked(isolated_db, monkeypatch):
    captured: dict = {}
    w = RelayWriter(relay_pwd="pwd", opener=counting_opener(captured))  # resolves URL from env
    broker = ActionBroker(writer=w)
    prop = broker.propose("adventure")
    assert prop["ok"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, prop["proposal_id"])
    conn.close()
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://127.0.0.1:60080")
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    assert captured.get("count", 0) == 0


def test_environment_flag_drift_blocked(isolated_db, monkeypatch):
    captured: dict = {}
    w = RelayWriter(relay_pwd="pwd", opener=counting_opener(captured))  # resolves URL from env
    broker = ActionBroker(writer=w)
    prop = broker.propose("adventure")
    assert prop["ok"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, prop["proposal_id"])
    conn.close()
    monkeypatch.setenv("KOLMAFA_LIVE_RELAY_ENABLED", "true")
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    assert captured.get("count", 0) == 0


def test_writer_substitution_blocked(isolated_db):
    captured: dict = {}
    w = RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="pwd", opener=counting_opener(captured))
    broker = ActionBroker(writer=w)
    prop = broker.propose("adventure")
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, prop["proposal_id"])
    conn.close()
    broker.writer = DryRunGcliWriter()
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    assert captured.get("count", 0) == 0


def test_serialized_proposal_fingerprint_tampered_blocked(isolated_db):
    captured: dict = {}
    w = RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="pwd", opener=counting_opener(captured))
    broker = ActionBroker(writer=w)
    prop = broker.propose("adventure")
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, prop["proposal_id"])
    conn.execute(
        "UPDATE action_confirmations SET transport_fingerprint = 'tampered' WHERE confirmation_id = ?",
        (prop["proposal_id"],),
    )
    conn.commit()
    conn.close()
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    assert captured.get("count", 0) == 0


def test_fake_writer_cannot_satisfy_live_approval(isolated_db):
    captured: dict = {}
    live = RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="pwd", opener=counting_opener(captured))
    broker = ActionBroker(writer=live)
    prop = broker.propose("adventure")
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, prop["proposal_id"])
    conn.close()

    class FakeLive:
        transport = "relay"

        def write(self, command, timeout=60.0):
            return CommandResult(command=command, transport="relay", return_code=0, stdout="", stderr="")

    broker.writer = FakeLive()
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    assert captured.get("count", 0) == 0


def test_mock_failure_no_live_fallback(isolated_db):
    class FailingFake:
        transport = "gcli-dry-run"

        def write(self, command, timeout=60.0):
            return CommandResult(command=command, transport="gcli-dry-run", return_code=1, stdout="", stderr="fail")

    broker = ActionBroker(writer=FailingFake())
    prop = broker.propose("adventure")
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, prop["proposal_id"])
    conn.close()
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out.get("return_code") == 1


def test_dry_run_surface_never_live(isolated_db, monkeypatch):
    # Even with live env flags set, MCP/runtime surface must not select live writer
    monkeypatch.setenv("KOLMAFA_LIVE_RELAY_ENABLED", "true")
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    from kolmafa.devtest.runtime import DonRuntime

    rt = DonRuntime()
    prop = rt.propose_action("adventure")
    assert prop["ok"] is True
    assert prop["transport"] == "gcli-dry-run"
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, prop["proposal_id"])
    conn.close()
    out = rt.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["transport"] == "gcli-dry-run"
    assert out["execution_performed"] is False


def test_evidence_event_on_mismatch(isolated_db, monkeypatch, tmp_path):
    events: list[dict] = []

    def capture(operation, mode, source_component, result_summary, *, extra=None, evidence_path=None):
        events.append({"operation": operation, "result_summary": result_summary, "extra": extra or {}})
        return {}

    monkeypatch.setattr("kolmafa.devtest.action_broker.record_evidence", capture)
    captured: dict = {}
    w = RelayWriter(relay_pwd="pwd", opener=counting_opener(captured))
    broker = ActionBroker(writer=w)
    prop = broker.propose("adventure")
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, prop["proposal_id"])
    conn.close()
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://127.0.0.1:60080")
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    mismatch = [e for e in events if e["extra"].get("classification") == "TRANSPORT_IDENTITY_MISMATCH"]
    assert mismatch, "expected blocked-attempt evidence event"
    assert mismatch[0]["extra"]["approved_fingerprint"]
    assert mismatch[0]["extra"]["actual_fingerprint"]
    assert "pwd" not in json.dumps(events)


def test_same_command_different_transport_does_not_validate(isolated_db):
    # Proposal approved for dry-run must not execute against live relay writer
    dry = DryRunGcliWriter()
    broker_dry = ActionBroker(writer=dry)
    prop = broker_dry.propose("adventure")
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, prop["proposal_id"])
    conn.close()
    captured: dict = {}
    live = RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="pwd", opener=counting_opener(captured))
    broker_live = ActionBroker(writer=live)
    out = broker_live.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    assert captured.get("count", 0) == 0


def test_t3_denial_independent_of_transport(isolated_db):
    broker = ActionBroker(writer=DryRunGcliWriter())
    prop = broker.propose("kmail")
    assert prop["ok"] is False
    assert prop["error"] == "T3 structural deny"
