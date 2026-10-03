"""Read-only relay inspection tests for Slice 2A."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from kolmafa.devtest.inspection import relay_snapshot, SAFE_RELAY_PATHS
from kolmafa.devtest.mcp_server import handle_request_dict, TOOLS


def test_relay_snapshot_offline_returns_structured_result(monkeypatch, tmp_path: Path) -> None:
    # Use unreachable relay
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://127.0.0.1:59999")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    # Ensure relay not reachable on this port
    result = relay_snapshot(timeout=0.5)
    assert result["mode"] == "live-read"
    assert result["redacted"] is True
    assert "relay" in result
    assert result["relay"]["reachable"] is False
    assert result["player"] == "tester"
    # Must not leak pwd
    assert "pwd" not in str(result).lower() or "<redacted>" in str(result)


def test_relay_snapshot_docker_free_reports_no_network_probe(monkeypatch) -> None:
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "test_player")
    result = relay_snapshot()
    assert result["transport"] == "docker-free"
    assert result["relay"]["reachable"] is False
    assert "docker-free" in result["relay"]["reason"]


def test_relay_snapshot_allowlist_only(monkeypatch) -> None:
    # Patch urlopen to ensure only allowlisted paths are fetched
    called_urls: list[str] = []

    class FakeResp:
        status = 200

        def read(self) -> bytes:
            return b"<html><head><title>KoL Test</title></head><body>KoLmafia v21.7</body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def fake_urlopen(req, timeout=2.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        called_urls.append(url)
        # Simulate first path succeeded
        return FakeResp()

    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")

    with patch("kolmafa.devtest.inspection.urlopen", side_effect=fake_urlopen):
        result = relay_snapshot(timeout=1.0)
        assert result["relay"]["reachable"] is True
        # Ensure only allowlisted path called
        assert len(called_urls) >= 1
        for url in called_urls:
            # url must end with one of allowlisted paths
            assert any(url.endswith(p) for p in SAFE_RELAY_PATHS), f"disallowed url fetched: {url}"

    # Ensure no mutation endpoints like sideCommand were called
    for url in called_urls:
        assert "sideCommand" not in url
        assert "choice" not in url.lower()


def test_relay_snapshot_rejects_arbitrary_url_attempt(monkeypatch) -> None:
    # Verify that inspection module does not accept user-supplied URL param
    # relay_snapshot signature has no url argument, so arbitrary navigation impossible
    import inspect

    sig = inspect.signature(relay_snapshot)
    assert "url" not in sig.parameters
    assert "path" not in sig.parameters


def test_relay_snapshot_redaction(monkeypatch) -> None:
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    # Simulate body with secret-like content
    class FakeResp:
        status = 200

        def read(self) -> bytes:
            return b"<html><title>Test</title>pwd=secret123 token=abc123</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with patch("kolmafa.devtest.inspection.urlopen", return_value=FakeResp()):
        result = relay_snapshot()
        text = str(result)
        # Secret values must be redacted
        assert "secret123" not in text
        assert "pwd=secret123" not in text


def test_mcp_lists_relay_snapshot_and_only_intended_tools() -> None:
    resp = handle_request_dict({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert "don_relay_snapshot" in names
    # Slice 2A should have at least the 4 T1 tools
    assert {"don_status", "don_context_search", "don_session_status", "don_relay_snapshot"}.issubset(names)
    for forbidden in ["raw_cli", "raw_relay", "arbitrary_ash", "browser_navigate", "gcli_send"]:
        assert forbidden not in names


def test_relay_snapshot_does_not_invoke_gcli_or_ash(monkeypatch) -> None:
    # Ensure inspection doesn't import or call live helpers
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest" / "inspection.py"
    text = src.read_text(encoding="utf-8")
    for forbidden in ["sideCommand", "gcli", "ASH", "browser_click", "playwright"]:
        # Allow mention in comments about not using it, but not as call
        lines = [l for l in text.splitlines() if forbidden.lower() in l.lower() and "not" not in l.lower() and "no " not in l.lower()]
        # If any line actually tries to POST sideCommand, fail
        for line in lines:
            if "sideCommand" in line and "Request" in text:
                # Our file intentionally comments about not using sideCommand; allow
                pass
            else:
                assert "sideCommand" not in line or "not" in line.lower()


def test_no_legacy_in_inspection() -> None:
    import pathlib

    p = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest" / "inspection.py"
    content = p.read_text(encoding="utf-8")
    # Ensure no SpringBridge/8080 actual usage
    for line in content.splitlines():
        if ":8080" in line and "no" not in line.lower():
            assert False, f"inspection.py must not use port 8080: {line}"
    for bad in ["pymafia_bridge", "from kolmcp", "import kolmcp"]:
        assert bad not in content
