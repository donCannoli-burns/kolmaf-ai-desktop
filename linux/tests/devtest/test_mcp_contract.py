"""MCP tool contract tests for Don Edition."""

from __future__ import annotations

from kolmafa.devtest.mcp_server import handle_request_dict, TOOLS


def test_tools_list_contains_three_required() -> None:
    resp = handle_request_dict({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "result" in resp
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "don_status" in names
    assert "don_context_search" in names
    assert "don_session_status" in names
    # schemas must be objects
    for t in tools:
        assert "input_schema" in t
        assert t["input_schema"]["type"] == "object"


def test_don_status_tool_returns_overall() -> None:
    resp = handle_request_dict(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "don_status", "arguments": {}}}
    )
    assert "result" in resp
    payload = resp["result"]["content"][0]["json"]
    assert "overall" in payload
    assert payload["overall"] in ("OFFLINE_READY", "LIVE_READ_READY", "LIVE_WRITE_READY", "BLOCKED")
    # must not expose secrets
    text = str(payload)
    assert "KOLMAFA_RELAY_PWD" not in text


def test_don_context_search_tool_requires_query() -> None:
    resp = handle_request_dict(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "don_context_search", "arguments": {"query": "helmet turtle", "limit": 5}},
        }
    )
    assert "result" in resp
    payload = resp["result"]["content"][0]["json"]
    assert payload["query"] == "helmet turtle"
    assert "results" in payload


def test_don_session_status_tool_is_readonly() -> None:
    resp = handle_request_dict(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "don_session_status", "arguments": {}}}
    )
    assert "result" in resp
    payload = resp["result"]["content"][0]["json"]
    assert "player" in payload
    # must not contain pwd
    assert "pwd" not in str(payload).lower() or "<redacted>" in str(payload)


def test_unknown_tool_returns_error() -> None:
    resp = handle_request_dict(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "don_raw_relay", "arguments": {}}}
    )
    assert "error" in resp


def test_no_legacy_tools_exposed() -> None:
    names = set(TOOLS.keys())
    for forbidden in ["raw_cli", "raw_relay", "arbitrary_ash", "browser_navigate", "shell", "send_message", "kmail"]:
        assert forbidden not in names
