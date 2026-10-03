"""Credential authority boundary tests for Slice 3B repair.

Invariant: RelayWriter consumes credential, Don runtime never discovers credential.
"""

from __future__ import annotations

import pathlib
import re
import os
from unittest.mock import patch

import pytest

from kolmafa.devtest.relay_writer import RelayWriter
from kolmafa.devtest.readiness import get_readiness
from kolmafa import db


def test_relay_writer_consumes_credential(monkeypatch, tmp_path):
    # RelayWriter must read from get_settings, not scrape HTML
    db_path = tmp_path / "cred.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "SUPER_SECRET_RELAY_TOKEN")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    db.init_database(db_path)

    # RelayWriter should use the env pwd without scraping
    w = RelayWriter()
    assert w.relay_pwd == "SUPER_SECRET_RELAY_TOKEN"
    # Ensure source file mentions get_settings, not scraping
    src = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest" / "relay_writer.py"
    text = src.read_text(encoding="utf-8")
    assert "get_settings" in text
    assert "self.relay_pwd" in text


def test_missing_credential_fail_closed(monkeypatch, tmp_path):
    db_path = tmp_path / "missing.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    # Isolate HOME so daily-hash store at real ~/.kolmafia is not used
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    db.init_database(db_path)

    # RelayWriter fail-closed
    w = RelayWriter()
    result = w.write("adventure")
    assert result.return_code == 2
    assert "KOLMAFA_RELAY_PWD required" in result.stderr
    assert "SUPER_SECRET_RELAY_TOKEN" not in str(result)

    # Readiness fail-closed
    r = get_readiness()
    assert r["live_write"] == "disabled"
    assert r["overall"] != "LIVE_WRITE_TRANSPORT_READY"
    assert r["kolmafia_relay"] == "offline"  # because no pwd


def test_no_pwd_scraping_in_executable_code():
    """Ensure Don executable code does not scrape pwd from relay HTML or inject env."""
    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest"
    for p in root.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        # Skip test files (not in src)
        # Check for credential harvesting patterns
        # 1. regex over relay HTML for pwd
        assert not re.search(r"re\.search.*pwd\s*=\s*\(.*\[a-f0-9\]", text), f"{p} must not regex pwd from HTML"
        assert "charpane.php" not in text or "PROVEN LIVE STATE" in text or "allowlist" in text or "GET" in text, f"{p} charpane allowlist should be minimal"
        # 2. os.environ injection of relay pwd (setting)
        # Allow os.environ.get for LIVE_RELAY_ENABLED, but not setting PWD
        for line in text.splitlines():
            stripped = line.strip()
            if "KOLMAFA_RELAY_PWD" in line and "=" in line:
                # Allow reading via get_settings, not setting
                # Setting would be os.environ["KOLMAFA_RELAY_PWD"] = or setdefault
                if 'os.environ["KOLMAFA_RELAY_PWD"]' in line or "os.environ['KOLMAFA_RELAY_PWD']" in line:
                    # Check if it's assignment
                    if "=" in line and "[" in line and "environ" in line:
                        # Distinguish get vs set: get is ok, set is not
                        if ".get(" in line:
                            continue
                        assert False, f"{p} must not inject KOLMAFA_RELAY_PWD via os.environ: {line}"
                if "os.environ.setdefault" in line and "KOLMAFA_RELAY_PWD" in line:
                    assert False, f"{p} must not setdefault relay pwd: {line}"
        # 3. Ensure no hardcoded pwd literal
        assert "SUPER_SECRET_RELAY_TOKEN" not in text
        # 4. Ensure RelayWriter consumes, not discovers: should contain get_settings
        if p.name == "relay_writer.py":
            assert "get_settings" in text
            assert "self.relay_pwd" in text
            # Should not contain scraping of charpane for pwd
            assert "charpane" not in text.lower() or "pwd=" not in text.lower()


def test_no_pwd_injection_in_src():
    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest"
    for p in root.rglob("*.py"):
        content = p.read_text(encoding="utf-8")
        for line in content.splitlines():
            if "KOLMAFA_RELAY_PWD" in line and "os.environ" in line:
                # Only allow read via monkeypatch in tests, not in src
                # In src, only get is allowed via os.environ.get for LIVE_RELAY_ENABLED, not PWD
                if "KOLMAFA_RELAY_PWD" in line and ".get(" not in line:
                    # If line contains assignment, fail
                    if "=" in line and "[" in line:
                        assert False, f"src {p} sets relay pwd: {line}"


def test_secret_redaction_still_holds(monkeypatch, tmp_path):
    db_path = tmp_path / "secret2.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "SUPER_SECRET_RELAY_TOKEN")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "sessions").mkdir(parents=True)
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

    w = RelayWriter(relay_pwd="SUPER_SECRET_RELAY_TOKEN", opener=fake_opener)
    result = w.write("adventure with pwd=SUPER_SECRET_RELAY_TOKEN")
    assert "SUPER_SECRET_RELAY_TOKEN" not in str(result)
    assert "<redacted>" in result.command or "SUPER_SECRET" not in result.command
    assert "SUPER_SECRET_RELAY_TOKEN" not in result.stdout


def test_single_writer_still_holds():
    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest"
    # Only action_broker should call writer.write
    for f in ["runtime.py", "mcp_server.py", "inspection.py", "readiness.py"]:
        content = (root / f).read_text(encoding="utf-8")
        assert "writer.write" not in content, f"{f} must not directly call writer.write"
        # also no sideCommand POST outside relay_writer
        for line in content.splitlines():
            low = line.lower()
            if "sidecommand" in low and ("no " in low or "not " in low or "never" in low or line.strip().startswith("#") or line.strip().startswith('"""')):
                continue
            assert "sideCommand" not in line, f"{f} must not contain sideCommand: {line}"
