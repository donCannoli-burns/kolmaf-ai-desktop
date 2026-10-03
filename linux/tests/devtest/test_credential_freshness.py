"""Freshness tests for daily-hash credential."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from kolmafa.config import get_settings, get_credential_source, _most_recent_rotation_utc
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


@pytest.fixture
def tmp_home(monkeypatch, tmp_path: Path):
    home = tmp_path / "home_fresh"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / ".kolmafia").mkdir(parents=True)
    return home


def _write_hash_and_meta(home: Path, hash_hex: str, last_updated_iso: str | None, raw_meta: str | None = None):
    h = home / ".kolmafia" / "daily-hash"
    h.write_text(hash_hex + "\n", encoding="utf-8")
    h.chmod(0o600)
    m = home / ".kolmafia" / "daily-hash.meta"
    if raw_meta is not None:
        m.write_text(raw_meta, encoding="utf-8")
    elif last_updated_iso is not None:
        m.write_text(json.dumps({"last_updated": last_updated_iso, "source": "test"}), encoding="utf-8")
    else:
        if m.exists():
            m.unlink()


def test_valid_current_hash_and_metadata_accepted(monkeypatch, tmp_home: Path):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    # Use current time as last_updated
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_hash_and_meta(tmp_home, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", now)
    assert get_settings().relay_pwd == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert get_credential_source() == "daily-hash-store"


def test_stale_metadata_rejected(monkeypatch, tmp_home: Path):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    # Metadata before latest rotation -> stale
    # Use a fixed past date far before rotation
    stale = "2024-01-01T00:00:00Z"
    _write_hash_and_meta(tmp_home, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", stale)
    # Mock most recent rotation to be after stale (2024-02-01)
    fake_now = datetime(2024, 2, 2, 12, 0, tzinfo=timezone.utc)
    with patch("kolmafa.config._most_recent_rotation_utc", return_value=datetime(2024, 2, 1, 19, 30, tzinfo=ZoneInfo("America/Phoenix")) if ZoneInfo else datetime(2024, 2, 1, 2, 30, tzinfo=timezone.utc)):
        # Simpler: patch to return a time after stale
        # We'll directly patch _is_daily_hash_fresh to use fake_now
        import kolmafa.config as cfg

        # Patch _most_recent_rotation_utc to return a fixed recent rotation after stale
        with patch.object(cfg, "_most_recent_rotation_utc", return_value=datetime(2024, 1, 2, 2, 30, tzinfo=timezone.utc)):
            assert get_settings().relay_pwd is None
            assert get_credential_source() == "none"


def test_missing_metadata_rejected(monkeypatch, tmp_home: Path):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    h = tmp_home / ".kolmafia" / "daily-hash"
    h.write_text("cccccccccccccccccccccccccccccccc\n", encoding="utf-8")
    # No meta file
    meta = tmp_home / ".kolmafia" / "daily-hash.meta"
    if meta.exists():
        meta.unlink()
    assert get_settings().relay_pwd is None
    assert get_credential_source() == "none"


def test_malformed_metadata_rejected(monkeypatch, tmp_home: Path):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    _write_hash_and_meta(tmp_home, "dddddddddddddddddddddddddddddddd", None, raw_meta="not json")
    assert get_settings().relay_pwd is None
    _write_hash_and_meta(tmp_home, "dddddddddddddddddddddddddddddddd", None, raw_meta=json.dumps({"source": "test"}))
    assert get_settings().relay_pwd is None
    _write_hash_and_meta(tmp_home, "dddddddddddddddddddddddddddddddd", None, raw_meta=json.dumps({"last_updated": ""}))
    assert get_settings().relay_pwd is None


def test_malformed_last_updated_rejected(monkeypatch, tmp_home: Path):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    _write_hash_and_meta(tmp_home, "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "not-a-date")
    assert get_settings().relay_pwd is None
    _write_hash_and_meta(tmp_home, "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "2024-13-01T00:00:00Z")
    assert get_settings().relay_pwd is None


def test_metadata_exactly_at_boundary_accepted(monkeypatch, tmp_home: Path):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    # Use a fixed rotation time
    import kolmafa.config as cfg

    # Choose a known rotation: 2024-01-01 19:30 Phoenix = 2024-01-02 02:30 UTC
    boundary = datetime(2024, 1, 2, 2, 30, tzinfo=timezone.utc)
    # Write meta with last_updated exactly at boundary
    _write_hash_and_meta(tmp_home, "ffffffffffffffffffffffffffffffff", boundary.isoformat().replace("+00:00", "Z"))
    with patch.object(cfg, "_most_recent_rotation_utc", return_value=boundary):
        assert get_settings().relay_pwd == "ffffffffffffffffffffffffffffffff"
        assert get_credential_source() == "daily-hash-store"


def test_before_today_rotation_accepts_yesterday_update(monkeypatch, tmp_home: Path):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    import kolmafa.config as cfg

    # Simulate now is 2024-01-02 10:00 Phoenix (which is 17:00 UTC), before today's 19:30 Phoenix
    # Most recent rotation is yesterday 19:30
    # Credential updated after yesterday's 19:30 (e.g., yesterday 20:00 Phoenix) should be accepted
    # We'll mock _most_recent_rotation_utc to return yesterday 19:30
    yesterday_rotation = datetime(2024, 1, 1, 2, 30, tzinfo=timezone.utc)  # 2023-12-31 19:30 Phoenix in UTC
    # Actually need to be precise: if now is Jan2 10am Phoenix, recent is Jan1 19:30 Phoenix
    # So last_updated at Jan1 20:00 Phoenix = Jan2 03:00 UTC, which is after yesterday rotation
    last_updated = datetime(2024, 1, 2, 3, 0, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    _write_hash_and_meta(tmp_home, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", last_updated)
    with patch.object(cfg, "_most_recent_rotation_utc", return_value=yesterday_rotation):
        assert get_settings().relay_pwd == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_after_today_rotation_rejects_before_today_update(monkeypatch, tmp_home: Path):
    monkeypatch.delenv("KOLMAFA_RELAY_PWD", raising=False)
    import kolmafa.config as cfg

    # Simulate now is 2024-01-02 20:00 Phoenix (after today's 19:30), recent is today 19:30
    today_rotation = datetime(2024, 1, 3, 2, 30, tzinfo=timezone.utc)  # Jan2 19:30 Phoenix in UTC
    # Credential updated before today's 19:30 (e.g., yesterday 20:00)
    last_updated = datetime(2024, 1, 2, 3, 0, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    _write_hash_and_meta(tmp_home, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", last_updated)
    with patch.object(cfg, "_most_recent_rotation_utc", return_value=today_rotation):
        assert get_settings().relay_pwd is None
        assert get_credential_source() == "none"


def test_env_wins_over_stale_file(monkeypatch, tmp_home: Path):
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "cccccccccccccccccccccccccccccccc")
    # Stale file
    stale = "2024-01-01T00:00:00Z"
    _write_hash_and_meta(tmp_home, "dddddddddddddddddddddddddddddddd", stale)
    # Even though file is stale, env should win
    assert get_settings().relay_pwd == "cccccccccccccccccccccccccccccccc"
    assert get_credential_source() == "env"
    # Also test missing meta with env still wins
    meta = tmp_home / ".kolmafia" / "daily-hash.meta"
    if meta.exists():
        meta.unlink()
    assert get_settings().relay_pwd == "cccccccccccccccccccccccccccccccc"
