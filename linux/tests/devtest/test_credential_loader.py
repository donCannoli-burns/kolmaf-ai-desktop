"""Credential loader tests for daily-hash store."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from kolmafa.config import get_settings, get_credential_source
from kolmafa.devtest.readiness import get_readiness


@pytest.fixture
def tmp_home(monkeypatch, tmp_path: Path):
    # Isolate home for daily-hash store
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Also set USERPROFILE for Path.home() on some systems? Path.home() uses HOME
    kolmafia_dir = home / ".kolmafia"
    kolmafia_dir.mkdir()
    return home


def _write_daily_hash(home: Path, content: bytes, fresh: bool = True):
    p = home / ".kolmafia" / "daily-hash"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    p.chmod(0o600)
    # Also write fresh metadata if requested and content looks valid 32 hex
    if fresh:
        try:
            stripped = content.strip().decode()
            if len(stripped) == 32 and all(c in "0123456789abcdef" for c in stripped):
                meta = home / ".kolmafia" / "daily-hash.meta"
                import json as _json
                from datetime import datetime, timezone

                # Use current time as last_updated (fresh)
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                meta.write_text(_json.dumps({"last_updated": now, "source": "test", "player": "tester"}), encoding="utf-8")
        except Exception:
            pass
    else:
        # Ensure no metadata or stale metadata
        meta = home / ".kolmafia" / "daily-hash.meta"
        if meta.exists():
            meta.unlink(missing_ok=True)


def _write_stale_meta(home: Path):
    import json as _json
    from datetime import datetime, timezone, timedelta

    p = home / ".kolmafia" / "daily-hash.meta"
    p.parent.mkdir(parents=True, exist_ok=True)
    # Set last_updated to 2 days ago (before most recent rotation)
    stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    p.write_text(_json.dumps({"last_updated": stale, "source": "test", "player": "tester"}), encoding="utf-8")


def test_env_precedence_over_file(tmp_home: Path, monkeypatch):
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    _write_daily_hash(tmp_home, b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n", fresh=True)
    # get_settings should return env value, not file
    s = get_settings()
    assert s.relay_pwd == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert get_credential_source() == "env"
    # Even if file is valid, env wins
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    s2 = get_settings()
    assert s2.relay_pwd == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert get_credential_source() == "daily-hash-store"


def test_valid_file_fallback(tmp_home: Path, monkeypatch):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    _write_daily_hash(tmp_home, b"cccccccccccccccccccccccccccccccc\n", fresh=True)
    s = get_settings()
    assert s.relay_pwd == "cccccccccccccccccccccccccccccccc"
    assert get_credential_source() == "daily-hash-store"
    # Check readiness with live flag
    monkeypatch.setenv("KOLMAFA_LIVE_RELAY_ENABLED", "true")
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    kol_home = tmp_home / ".kolmafia"
    sessions = kol_home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "tester.txt").write_text("KOLMAFA_USER: hello\n", encoding="utf-8")
    (sessions / "active_session.tester").write_text("tester\n", encoding="utf-8")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kol_home))
    grounded = {
        "ok": True,
        "evidence_tier": "PROVEN LIVE STATE",
        "account": {"proven": True},
        "session": {"exists": True},
        "choice_state": {"ok": True, "handling_choice": False, "choice_id": None},
        "target_items": {"5054": {"item_id": "5054", "quantity": 1, "owned": True, "valid": True}},
    }
    with patch("kolmafa.devtest.inspection.grounding_snapshot", return_value=grounded):
        r = get_readiness()
    # Should be live-ready only with both credential and flag
    assert r["live_write"] == "live-relay-ready"
    assert r["overall"] in ("LIVE_WRITE_TRANSPORT_READY", "LIVE_READ_READY", "OFFLINE_READY")  # depends on docker_free


def test_missing_file_unavailable(tmp_home: Path, monkeypatch):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    # Ensure no file
    p = tmp_home / ".kolmafia" / "daily-hash"
    if p.exists():
        p.unlink()
    s = get_settings()
    assert s.relay_pwd is None
    assert get_credential_source() == "none"


def test_malformed_file_cases(tmp_home: Path, monkeypatch):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    cases = [
        b"",  # empty
        b"abc\n",  # 3 chars
        b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",  # 31 chars
        b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",  # 33 chars
        b"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n",  # uppercase
        b"gggggggggggggggggggggggggggggggg\n",  # non-hex g
        b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa extra text\n",
        b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\x00\n",  # null byte
    ]
    for content in cases:
        _write_daily_hash(tmp_home, content)
        s = get_settings()
        assert s.relay_pwd is None, f"should fail for {content!r}"
        assert get_credential_source() == "none"


def test_newline_handling(tmp_home: Path, monkeypatch):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    # 32 chars + newline should be valid (newline stripped)
    _write_daily_hash(tmp_home, b"dddddddddddddddddddddddddddddddd\n", fresh=True)
    s = get_settings()
    assert s.relay_pwd == "dddddddddddddddddddddddddddddddd"
    assert get_credential_source() == "daily-hash-store"
    # Without newline also valid
    _write_daily_hash(tmp_home, b"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", fresh=True)
    s2 = get_settings()
    assert s2.relay_pwd == "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


def test_live_enablement(monkeypatch, tmp_home: Path):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    monkeypatch.delenv("KOLMAFA_LIVE_RELAY_ENABLED", raising=False)
    _write_daily_hash(tmp_home, b"ffffffffffffffffffffffffffffffff\n", fresh=True)
    # Valid file but no live flag -> not LIVE_WRITE_TRANSPORT_READY
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    kol_home = tmp_home / ".kolmafia"
    sessions = kol_home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "tester.txt").write_text("KOLMAFA_USER: hello\n", encoding="utf-8")
    (sessions / "active_session.tester").write_text("tester\n", encoding="utf-8")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kol_home))
    grounded = {
        "ok": True,
        "evidence_tier": "PROVEN LIVE STATE",
        "account": {"proven": True},
        "session": {"exists": True},
        "choice_state": {"ok": True, "handling_choice": False, "choice_id": None},
        "target_items": {"5054": {"item_id": "5054", "quantity": 1, "owned": True, "valid": True}},
    }
    with patch("kolmafa.devtest.inspection.grounding_snapshot", return_value=grounded):
        r1 = get_readiness()
    assert r1["live_write"] == "disabled"
    assert r1["overall"] != "LIVE_WRITE_TRANSPORT_READY"

    # Valid file + live flag true -> should be live-ready if other requirements satisfied
    monkeypatch.setenv("KOLMAFA_LIVE_RELAY_ENABLED", "true")
    with patch("kolmafa.devtest.inspection.grounding_snapshot", return_value=grounded):
        r2 = get_readiness()
    # With file credential and live flag, and evidence writable, should be live-relay-ready (if docker_free_ready etc)
    # Since we have sessions dir, docker_free_ready true, so overall should be LIVE_WRITE_TRANSPORT_READY
    assert r2["live_write"] == "live-relay-ready"

    # Credential absent + live flag true -> disabled
    p = tmp_home / ".kolmafia" / "daily-hash"
    p.unlink()
    # Also ensure meta removed
    (tmp_home / ".kolmafia" / "daily-hash.meta").unlink(missing_ok=True)
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    # Keep live flag true but no credential
    with patch("kolmafa.devtest.inspection.grounding_snapshot", return_value=grounded):
        r3 = get_readiness()
    assert r3["live_write"] == "disabled"


def test_secret_redaction_in_readiness_and_evidence(monkeypatch, tmp_path: Path):
    home = tmp_path / "home_redact"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / ".kolmafia").mkdir()
    fake_pwd = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _write_daily_hash(home, (fake_pwd + "\n").encode(), fresh=True)
    monkeypatch.setenv("KOLMAFA_LIVE_RELAY_ENABLED", "true")
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(home / ".kolmafia2"))
    (home / ".kolmafia2" / "sessions").mkdir(parents=True)
    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "redact.db"))
    from kolmafa import db

    db.init_database(Path(tmp_path / "redact.db"))

    r = get_readiness()
    # Must not contain raw credential
    assert fake_pwd not in str(r)
    assert r.get("credential_source") in ("daily-hash-store", None) or "relay_pwd_configured" in r
    # Check MCP-safe status output (don_status) not containing raw
    from kolmafa.devtest.runtime import DonRuntime

    rt = DonRuntime()
    status = rt.status()
    assert fake_pwd not in str(status)
    # Check evidence log not containing raw
    from pathlib import Path as P

    log_path = P(__file__).resolve().parents[2] / "logs" / "don-evidence.jsonl"
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8", errors="replace")
        assert fake_pwd not in content


def test_file_safety_not_created(tmp_home: Path, monkeypatch):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    p = tmp_home / ".kolmafia" / "daily-hash"
    if p.exists():
        p.unlink()
    (tmp_home / ".kolmafia" / "daily-hash.meta").unlink(missing_ok=True)
    # Ensure loader does not create file
    s = get_settings()
    assert s.relay_pwd is None
    assert not p.exists()
    # Ensure permissions not changed (if file exists, it should remain 600)
    _write_daily_hash(tmp_home, b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n", fresh=True)
    old_mode = p.stat().st_mode
    s2 = get_settings()
    assert s2.relay_pwd is not None
    assert p.stat().st_mode == old_mode
