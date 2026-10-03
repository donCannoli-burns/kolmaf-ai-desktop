"""Readiness consolidation for Don Edition.

Wraps current ``kolmafa.bridge.check_status`` and adds Don-level overall state.
No SpringBridge / port 8080 checks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kolmafa import bridge
from kolmafa.config import get_settings
from kolmafa.redaction import redact_text

# Overall states aligned with design packet.
OFFLINE_READY = "OFFLINE_READY"
LIVE_READ_READY = "LIVE_READ_READY"
LIVE_WRITE_READY = "LIVE_WRITE_READY"
LIVE_WRITE_TRANSPORT_READY = "LIVE_WRITE_TRANSPORT_READY"
BLOCKED = "BLOCKED"


def get_readiness() -> dict[str, Any]:
    """Return Don readiness report without leaking secrets."""

    settings = get_settings()
    status: bridge.BridgeStatus = bridge.check_status(
        database_path=settings.database_path,
        kolmafia_home=settings.kolmafia_home,
        cli_command=settings.cli_command,
        transport=settings.transport,
        relay_base_url=settings.relay_base_url,
        relay_pwd=settings.relay_pwd,
        player_name=settings.player_name,
    )

    try:
        from kolmafa.db import SCHEMA_PATH
        schema_ok = SCHEMA_PATH.exists()
    except Exception:
        schema_ok = False

    project = "ok" if schema_ok else "problem"
    database = "ok" if status.database_path.parent.exists() else "problem"
    session = "ok" if status.docker_free_ready else "problem"
    player = "known" if status.player_name else "unknown"
    session_path = str(status.session_file) if status.session_file is not None else None

    live_read: dict[str, Any] = {
        "ready": False,
        "reason": "live-read proof unavailable",
        "evidence_tier": "UNAVAILABLE",
    }
    if status.player_name and status.session_file is not None and status.session_file.is_file():
        if status.transport == "docker-free":
            live_read = {
                "ready": True,
                "reason": "docker-free session observation",
                "evidence_tier": "LOCAL SESSION STATE",
            }
        else:
            try:
                from kolmafa.devtest.inspection import grounding_snapshot

                grounded = grounding_snapshot(timeout=10.0)
                account = grounded.get("account", {}) if isinstance(grounded.get("account"), dict) else {}
                choice_state = grounded.get("choice_state", {}) if isinstance(grounded.get("choice_state"), dict) else {}
                item = grounded.get("target_items", {}).get("5054", {}) if isinstance(grounded.get("target_items"), dict) else {}
                ready = bool(
                    grounded.get("ok")
                    and account.get("proven")
                    and grounded.get("session", {}).get("exists")
                    and choice_state.get("ok")
                    and item.get("valid")
                )
                live_read = {
                    "ready": ready,
                    "reason": "grounded current-state reads" if ready else "current-state read gates not proven",
                    "evidence_tier": grounded.get("evidence_tier", "UNAVAILABLE"),
                    "player": grounded.get("player"),
                    "choice_state": choice_state,
                    "item_5054": item,
                }
            except Exception as exc:
                live_read = {
                    "ready": False,
                    "reason": redact_text(str(exc))[:200],
                    "evidence_tier": "UNAVAILABLE",
                }

    read_only_inspection = "ready" if live_read["ready"] else "unavailable"
    evidence_writable = True
    try:
        from kolmafa.devtest.evidence import DEFAULT_EVIDENCE_PATH
        DEFAULT_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        test = DEFAULT_EVIDENCE_PATH.parent / ".writetest"
        test.write_text("", encoding="utf-8")
        test.unlink(missing_ok=True)
    except Exception:
        evidence_writable = False

    import os

    live_flag = os.environ.get("KOLMAFA_LIVE_RELAY_ENABLED", "").lower() in ("1", "true", "yes")
    live_relay_configured = bool(status.relay_pwd_configured and status.transport != "docker-free")
    live_write = (
        "live-relay-ready"
        if live_relay_configured and live_flag and evidence_writable and live_read["ready"]
        else "disabled"
    )

    if project != "ok":
        overall = BLOCKED
    elif live_write == "live-relay-ready":
        overall = LIVE_WRITE_TRANSPORT_READY
    elif live_read["ready"]:
        overall = LIVE_READ_READY
    else:
        overall = OFFLINE_READY

    return {
        "project": project,
        "database": database,
        "session": session,
        "session_path": session_path,
        "kolmafia_relay": "ok" if live_relay_configured else "offline",
        "player": player,
        "read_only_inspection": read_only_inspection,
        "live_read": live_read,
        "live_write": live_write,
        "overall": overall,
        "docker_free_ready": status.docker_free_ready,
        "docker_free_problems": list(status.docker_free_problems),
        "transport": status.transport,
    }
