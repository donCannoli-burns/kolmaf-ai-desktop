"""Minimal OpenCode tool surface for Don Edition.

Exposes T1 read-only tools over a simple JSON-RPC stdio loop.
Tools:
- don_status
- don_context_search
- don_session_status

No live mutation, no SpringBridge, no port 8080.

All broker-backed tools run with an explicitly injected DryRunGcliWriter/fake
transport. This surface never infers a live writer from the environment, so a
dry-run selection can never resolve to a live RelayWriter.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from kolmafa.devtest.runtime import DonRuntime

TOOLS = {
    "don_status": {
        "description": "Don Edition readiness/status (T1 read-only, no secrets)",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "don_context_search": {
        "description": "Search local SQLite/FTS5 corpus (T1 read-only)",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "don_session_status": {
        "description": "Read-only session status/inspection (T1, no mutation)",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "don_relay_snapshot": {
        "description": "Read-only relay inspection snapshot (T1 live-read, no mutation, allowlisted endpoints only)",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "don_equipment_status": {
        "description": "Narrow read-only current-state snapshot (T1 live-read: account/session, item quantities, choice state, no mutation)",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "don_propose_action": {
        "description": "Propose a game-affecting action (no execution, returns proposal_id for durable confirmation)",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Normalized game action (e.g., adventure, use, equip)"},
                "arguments": {"type": "object", "description": "Optional arguments dict"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    "don_execute_approved": {
        "description": "Execute a previously confirmed proposal via the injected DryRunGcliWriter/fake transport only (single writer, T3 denied). Never selects or falls back to a live RelayWriter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string", "description": "Proposal/confirmation ID from don_propose_action"},
                "expected_action": {"type": "string", "description": "Exact action text for binding verification"},
                "expected_arguments": {"type": "object", "description": "Exact arguments for binding verification"},
            },
            "required": ["proposal_id"],
            "additionalProperties": False,
        },
    },
}


def _dispatch(tool: str, arguments: dict[str, Any]) -> Any:
    runtime = DonRuntime()
    if tool == "don_status":
        return runtime.status()
    if tool == "don_context_search":
        query = arguments.get("query", "")
        limit = int(arguments.get("limit", 10))
        return runtime.search_context(query, limit=limit)
    if tool == "don_session_status":
        return runtime.session_status()
    if tool == "don_relay_snapshot":
        return runtime.relay_snapshot()
    if tool == "don_equipment_status":
        return runtime.equipment_snapshot()
    if tool == "don_propose_action":
        return runtime.propose_action(arguments.get("action", ""), arguments.get("arguments"))
    if tool == "don_execute_approved":
        return runtime.execute_approved(
            arguments.get("proposal_id", ""),
            expected_action=arguments.get("expected_action"),
            expected_arguments=arguments.get("expected_arguments"),
        )
    raise ValueError(f"unknown tool: {tool}")


def _handle_request(req: dict[str, Any]) -> dict[str, Any]:
    """Handle one JSON-RPC request dict and return response dict."""

    req_id = req.get("id")
    method = req.get("method")

    # MCP-style list_tools
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"capabilities": {"tools": {}}}}
    if method in ("tools/list", "list_tools"):
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": [{"name": k, **v} for k, v in TOOLS.items()]},
        }
    if method in ("tools/call", "call_tool"):
        params = req.get("params", {})
        name = params.get("name") or params.get("tool")
        arguments = params.get("arguments") or params.get("input") or {}
        try:
            result = _dispatch(name, arguments)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "json", "json": result}]}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}}

    # Fallback: treat method as tool name directly (simple test harness)
    if method in TOOLS:
        try:
            result = _dispatch(method, req.get("params", {}))
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> None:
    """Run stdio JSON-RPC loop."""

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}) + "\n")
            sys.stdout.flush()
            continue
        resp = _handle_request(req)
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


# Expose for tests without stdio
def handle_request_dict(req: dict[str, Any]) -> dict[str, Any]:
    return _handle_request(req)


if __name__ == "__main__":
    main()
