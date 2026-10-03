"""t7 adversarial transport-binding matrix — offline, fake openers only.

Zero real KoLmafia contact: every positive path injects a counting fake
opener; every deny path asserts zero opener calls and no credential leak.
"""

from __future__ import annotations

from pathlib import Path
from urllib.error import URLError
from unittest.mock import MagicMock

import pytest

from kolmafa import db
from kolmafa.bridge import CommandResult, DryRunGcliWriter
from kolmafa.config import get_settings
from kolmafa.confirmations import confirm_action
from kolmafa.devtest.action_broker import ActionBroker
from kolmafa.devtest.mcp_server import handle_request_dict
from kolmafa.devtest.relay_writer import RelayWriter
from kolmafa.devtest.runtime import DonRuntime
from kolmafa.devtest.transport_identity import (
    TransportIdentityError,
    relay_identity_from_url,
    validate_relay_destination,
)


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "t7.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "t7_fake_pwd_DO_NOT_LOG")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "sessions").mkdir(parents=True)
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


# --- Approved == executed PASS, exactly one simulated POST ------------------


def test_valid_bound_transport_exactly_one_post(isolated_db):
    captured: dict = {}
    w = RelayWriter(
        relay_base_url="http://localhost:60080",
        relay_pwd="t7_fake_pwd_DO_NOT_LOG",
        opener=counting_opener(captured),
    )
    broker = ActionBroker(writer=w)
    prop = broker.propose("adventure")
    assert prop["ok"] is True
    # Real fingerprint equality path: proposal fingerprint must equal the
    # fingerprint derived independently from the same destination.
    expected = relay_identity_from_url(
        "http://localhost:60080", opener_class="injected-opener"
    ).fingerprint()
    assert prop["transport_fingerprint"] == expected
    conn = db.connect(get_settings().database_path)
    try:
        confirm_action(conn, prop["proposal_id"])
    finally:
        conn.close()
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is True
    assert out["execution_performed"] is True
    assert captured["count"] == 1
    assert captured["url"] == "http://localhost:60080/sideCommand"


# --- Mismatch blocks: zero calls -------------------------------------------


def test_config_toctou_localhost_to_loopback_literal_zero_post(isolated_db, monkeypatch):
    captured: dict = {}
    w = RelayWriter(relay_pwd="t7_fake_pwd_DO_NOT_LOG", opener=counting_opener(captured))
    broker = ActionBroker(writer=w)
    prop = broker.propose("adventure")
    assert prop["ok"]
    conn = db.connect(get_settings().database_path)
    try:
        confirm_action(conn, prop["proposal_id"])
    finally:
        conn.close()
    # TOCTOU A -> B: mutate relay URL config between approval and execution
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://127.0.0.1:60080")
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    assert captured.get("count", 0) == 0


def test_fake_approved_to_live_writer_blocked_zero_calls(isolated_db):
    captured: dict = {}
    dry = DryRunGcliWriter()
    broker = ActionBroker(writer=dry)
    prop = broker.propose("adventure")
    assert prop["ok"]
    conn = db.connect(get_settings().database_path)
    try:
        confirm_action(conn, prop["proposal_id"])
    finally:
        conn.close()
    live = RelayWriter(
        relay_base_url="http://localhost:60080",
        relay_pwd="t7_fake_pwd_DO_NOT_LOG",
        opener=counting_opener(captured),
    )
    broker.writer = live
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    assert captured.get("count", 0) == 0


def test_live_approved_to_fake_writer_blocked_zero_calls(isolated_db):
    captured: dict = {}
    live = RelayWriter(
        relay_base_url="http://localhost:60080",
        relay_pwd="t7_fake_pwd_DO_NOT_LOG",
        opener=counting_opener(captured),
    )
    broker = ActionBroker(writer=live)
    prop = broker.propose("adventure")
    conn = db.connect(get_settings().database_path)
    try:
        confirm_action(conn, prop["proposal_id"])
    finally:
        conn.close()
    broker.writer = DryRunGcliWriter()
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    assert captured.get("count", 0) == 0


def test_mock_writer_cannot_execute_relay_approval(isolated_db):
    captured: dict = {}
    live = RelayWriter(
        relay_base_url="http://localhost:60080",
        relay_pwd="t7_fake_pwd_DO_NOT_LOG",
        opener=counting_opener(captured),
    )
    broker = ActionBroker(writer=live)
    prop = broker.propose("adventure")
    conn = db.connect(get_settings().database_path)
    try:
        confirm_action(conn, prop["proposal_id"])
    finally:
        conn.close()
    fake_live = MagicMock()
    fake_live.transport = "relay"
    fake_live.transport_identity.return_value = relay_identity_from_url(
        "http://localhost:60080", opener_class="no-redirect-opener"
    )
    broker.writer = fake_live
    out = broker.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["ok"] is False
    assert out["classification"] == "TRANSPORT_IDENTITY_MISMATCH"
    assert captured.get("count", 0) == 0
    assert fake_live.write.call_count == 0


# --- Dry-run never live -----------------------------------------------------


def test_dry_run_surface_never_live_even_with_live_env(isolated_db, monkeypatch):
    monkeypatch.setenv("KOLMAFA_LIVE_RELAY_ENABLED", "true")
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    rt = DonRuntime()
    prop = rt.propose_action("adventure")
    assert prop["ok"] is True
    assert prop["transport"] == "gcli-dry-run"
    conn = db.connect(get_settings().database_path)
    try:
        confirm_action(conn, prop["proposal_id"])
    finally:
        conn.close()
    out = rt.execute_approved(prop["proposal_id"], expected_action="adventure")
    assert out["transport"] == "gcli-dry-run"
    assert out["execution_performed"] is False


def test_mcp_surface_dry_run_isolation(isolated_db, monkeypatch):
    monkeypatch.setenv("KOLMAFA_LIVE_RELAY_ENABLED", "true")
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    resp = handle_request_dict(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "don_propose_action", "arguments": {"action": "adventure"}}}
    )
    payload = resp["result"]["content"][0]["json"]
    assert payload["ok"] is True
    assert payload["transport"] == "gcli-dry-run"
    conn = db.connect(get_settings().database_path)
    try:
        confirm_action(conn, payload["proposal_id"])
    finally:
        conn.close()
    resp2 = handle_request_dict(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "don_execute_approved", "arguments": {"proposal_id": payload["proposal_id"], "expected_action": "adventure"}}}
    )
    payload2 = resp2["result"]["content"][0]["json"]
    assert payload2["transport"] == "gcli-dry-run"
    assert payload2["execution_performed"] is False


# --- External / LAN / exotic-encoding URLs rejected -------------------------


EXTERNAL_URLS = [
    "http://example.com",
    "http://evil.test:60080",
    "http://203.0.113.10",
]

LAN_URLS = [
    "http://192.168.1.10",
    "http://10.0.0.5",
    "http://172.16.0.1",
    "http://169.254.169.254",
    "http://0.0.0.0",
]

EXOTIC_URLS = [
    "http://127.1",
    "http://2130706433",
    "http://0x7f000001",
    "http://0177.0.0.1",
    "http://[::ffff:127.0.0.1]",
    "http://%6cocalhost",
    "http://localhost@evil.test",
    "http://127.0.0.1:60080@evil.test",
    "http://[::1]:60080",
    "http://localhost.evil.test",
]


@pytest.mark.parametrize("url", EXTERNAL_URLS)
def test_external_host_rejected(url):
    with pytest.raises(TransportIdentityError) as exc:
        validate_relay_destination(url)
    assert exc.value.classification == "NON_LOOPBACK_RELAY_REJECTED"


@pytest.mark.parametrize("url", LAN_URLS)
def test_lan_rejected(url):
    with pytest.raises(TransportIdentityError) as exc:
        validate_relay_destination(url)
    assert exc.value.classification == "NON_LOOPBACK_RELAY_REJECTED"


@pytest.mark.parametrize("url", EXOTIC_URLS)
def test_exotic_encoding_rejected(url):
    with pytest.raises(TransportIdentityError):
        validate_relay_destination(url)


@pytest.mark.parametrize("url", EXTERNAL_URLS + LAN_URLS + EXOTIC_URLS)
def test_writer_rejects_all_zero_calls(url):
    captured: dict = {}
    w = RelayWriter(relay_base_url=url, relay_pwd="t7_fake_pwd_DO_NOT_LOG", opener=counting_opener(captured))
    result = w.write("adventure")
    assert result.return_code == 2
    assert captured.get("count", 0) == 0
    assert "t7_fake_pwd_DO_NOT_LOG" not in str(result)


# --- Redirect rejected ------------------------------------------------------


def test_redirect_rejected_zero_calls_audit_safe():
    from urllib.error import HTTPError

    def redirect_opener(req, timeout=30):
        raise HTTPError(req.full_url, 302, "Found", {"Location": "http://evil.test/sideCommand"}, None)

    captured: dict = {}

    def counting_redirect(req, timeout=30):
        captured["count"] = captured.get("count", 0) + 1
        return redirect_opener(req, timeout)

    w = RelayWriter(
        relay_base_url="http://localhost:60080",
        relay_pwd="t7_fake_pwd_DO_NOT_LOG",
        opener=counting_redirect,
    )
    result = w.write("adventure")
    assert result.return_code == 2
    assert "REDIRECT_DESTINATION_REJECTED" in result.stderr
    assert "t7_fake_pwd_DO_NOT_LOG" not in result.stderr
    # one attempted call that raised before any network, no retry
    assert captured["count"] == 1


# --- Credential ordering + never logged -------------------------------------


def test_credential_absent_before_validation_zero_calls():
    captured: dict = {}
    w = RelayWriter(relay_base_url="http://192.168.1.10:60080", relay_pwd="t7_fake_pwd_DO_NOT_LOG", opener=counting_opener(captured))
    result = w.write("adventure")
    assert result.return_code == 2
    assert captured.get("count", 0) == 0
    # The pwd must never reach a request payload
    assert captured.get("data") is None
    assert "t7_fake_pwd_DO_NOT_LOG" not in str(result)


def test_userinfo_credential_in_url_rejected_before_payload():
    captured: dict = {}
    w = RelayWriter(relay_base_url="http://user:t7_fake_pwd_DO_NOT_LOG@localhost", relay_pwd="t7_fake_pwd_DO_NOT_LOG", opener=counting_opener(captured))
    result = w.write("adventure")
    assert result.return_code == 2
    assert captured.get("count", 0) == 0
    assert "t7_fake_pwd_DO_NOT_LOG" not in str(result)


def test_credential_never_logged_on_network_error():
    def failing_opener(req, timeout=30):
        raise URLError("connection refused by t7_fake_pwd_DO_NOT_LOG host")

    w = RelayWriter(
        relay_base_url="http://localhost:60080",
        relay_pwd="t7_fake_pwd_DO_NOT_LOG",
        opener=failing_opener,
    )
    result = w.write("adventure")
    assert result.return_code == 1
    assert "t7_fake_pwd_DO_NOT_LOG" not in result.stderr
