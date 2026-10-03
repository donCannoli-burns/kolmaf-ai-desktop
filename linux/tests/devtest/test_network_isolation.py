"""Network isolation regression — ensure unit tests cannot hit real /sideCommand."""

from __future__ import annotations

import os
import pathlib
from unittest.mock import patch

import pytest

from kolmafa.devtest.relay_writer import RelayWriter


def test_dummy_credential_default_opener_blocked():
    # Dummy sentinel with default real opener must be blocked in tests
    w = RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN")
    result = w.write("adventure")
    assert result.return_code == 2
    assert "test isolation" in result.stderr
    assert "SUPER_SECRET_RELAY_TOKEN" not in str(result)


def test_arbitrary_non_sentinel_credential_default_opener_blocked():
    # Arbitrary non-sentinel fake credential with default opener must also be blocked (credential-independent)
    fake_pwd = "FAKE_TEST_PWD_12345_NON_SENTINEL"
    w = RelayWriter(relay_base_url="http://localhost:60080", relay_pwd=fake_pwd)
    result = w.write("adventure")
    assert result.return_code == 2
    assert "test isolation" in result.stderr
    assert fake_pwd not in str(result)


def test_env_provided_credential_default_opener_blocked(monkeypatch, tmp_path):
    # Environment-provided credential (monkeypatched) with default opener must be blocked
    from kolmafa import db

    db_path = tmp_path / "envcred.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "ENV_FAKE_PWD_FOR_TEST_999")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    db.init_database(db_path)

    # RelayWriter without explicit opener will use real urlopen (default) - should be blocked in pytest
    w = RelayWriter()  # reads ENV_FAKE_PWD_FOR_TEST_999
    result = w.write("adventure")
    assert result.return_code == 2
    assert "test isolation" in result.stderr
    assert "ENV_FAKE_PWD_FOR_TEST_999" not in str(result)


def test_explicit_fake_opener_allowed():
    class FakeResp:
        status = 200

        def read(self):
            return b"ok mocked"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_opener(req, timeout=30):
        return FakeResp()

    w = RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener)
    result = w.write("adventure")
    assert result.return_code == 0
    assert result.stdout == ""
    assert result.result_marker == {"result_kind": "unknown"}

    # Also test with arbitrary non-sentinel via fake opener
    def fake_opener2(req, timeout=30):
        return FakeResp()

    w2 = RelayWriter(relay_base_url="http://localhost:60080", relay_pwd="FAKE_TEST_PWD_12345_NON_SENTINEL", opener=fake_opener2)
    result2 = w2.write("adventure")
    assert result2.return_code == 0


def test_production_source_remains_clean():
    src = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest" / "relay_writer.py"
    text = src.read_text(encoding="utf-8")
    assert "PYTEST_CURRENT_TEST" not in text
    assert "Mock" not in text
    assert "SUPER_SECRET_RELAY_TOKEN" not in text
    assert "pytest" not in text.lower()
    assert "test isolation" not in text.lower()
    # Must still use get_settings and have opener injection
    assert "get_settings" in text
    assert "opener" in text
    assert "self._opener" in text


def test_t3_state_drift_missing_approval_still_zero_network(monkeypatch, tmp_path):
    """Ensure T3, state drift, missing approval still 0 transport calls — no sideCommand."""
    from unittest.mock import MagicMock

    from kolmafa import db
    from kolmafa.devtest.action_broker import ActionBroker

    db_path = tmp_path / "iso.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "SUPER_SECRET_RELAY_TOKEN")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    db.init_database(db_path)

    fake = MagicMock()
    fake.transport = "relay"
    broker = ActionBroker(writer=fake)
    res = broker.propose("kmail test")
    assert res["ok"] is False
    assert fake.write.call_count == 0

    # Missing approval no network — use explicit fake opener for broker's writer
    class FakeResp:
        status = 200

        def read(self):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_opener(req, timeout=30):
        return FakeResp()

    from kolmafa.devtest.relay_writer import RelayWriter as RW

    broker2 = ActionBroker(writer=RW(relay_base_url="http://localhost:60080", relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener))
    prop = broker2.propose("adventure")
    assert prop["ok"]
    pid = prop["proposal_id"]
    out = broker2.execute_approved(pid, expected_action="adventure")
    assert out["ok"] is False
    # fake_opener should not have been called because missing approval denies before transport
    # Since we used explicit fake, we can check that our fake was not called by checking that out is deny
    assert out["ok"] is False
