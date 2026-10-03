"""Don Edition runtime facade.

Thin adapter over current ``kolmafa`` runtime.
Exposes structured operations for OpenCode tools.

Reuse decisions:
- REUSE AS-IS: db, rag, bridge session observation, redaction, config
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from kolmafa import bridge, db, rag
from kolmafa.config import get_settings
from kolmafa.redaction import redact_text

from kolmafa.devtest.evidence import record_evidence
from kolmafa.devtest.readiness import get_readiness
from kolmafa.devtest import inspection as dev_inspection
from kolmafa.devtest.action_broker import ActionBroker
from kolmafa.bridge import DryRunGcliWriter


class DonRuntime:
    """Cohesive facade for Don Edition operations."""

    def status(self) -> dict[str, Any]:
        """Return readiness + bridge status (T1 read-only)."""

        readiness = get_readiness()
        record_evidence("don_status", "offline", "kolmafa.devtest.runtime", str(readiness.get("overall")))
        return readiness

    def search_context(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search local SQLite/FTS5 corpus (T1)."""

        settings = get_settings()
        # Ensure database exists and schema is initialized for offline search
        try:
            if not settings.database_path.exists():
                db.init_database(settings.database_path)
            else:
                # Ensure FTS table exists; if not, init
                with db.connect(settings.database_path) as conn:
                    exists = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='documents_fts'"
                    ).fetchone()
                    if not exists:
                        db.init_database(settings.database_path)
        except Exception:
            # If init fails, continue with empty results
            pass

        results: list[dict[str, Any]] = []
        try:
            with db.connect(settings.database_path) as conn:
                rows = rag.search(conn, query, limit=limit)
                for r in rows:
                    # Row may be sqlite Row; convert
                    try:
                        d = dict(r)
                    except Exception:
                        d = {k: r[k] for k in r.keys()}
                    # redact snippet etc already redacted by rag, but ensure
                    results.append(
                        {
                            "title": redact_text(d.get("title", "")),
                            "source_path": redact_text(d.get("source_path", "")),
                            "snippet": redact_text(d.get("snippet", "")),
                            "score": d.get("score"),
                            "source_label": redact_text(d.get("source_label", "")),
                            "quality_class": d.get("quality_class"),
                        }
                    )
        except Exception as exc:
            record_evidence("don_context_search", "offline", "kolmafa.rag", f"error: {exc}")
            return {"query": redact_text(query), "results": [], "error": redact_text(str(exc))}

        record_evidence("don_context_search", "offline", "kolmafa.rag", f"found {len(results)}")
        return {"query": redact_text(query), "results": results, "count": len(results)}

    def session_status(self) -> dict[str, Any]:
        """Return read-only session observation status (T1)."""

        settings = get_settings()
        player = settings.player_name or "unknown"
        try:
            kolmafia_home = settings.kolmafia_home
            session_path = bridge.session_file(kolmafia_home, player) if player != "unknown" else None
        except Exception as exc:
            record_evidence("don_session_status", "offline", "kolmafa.bridge", f"error: {exc}")
            return {"player": redact_text(player), "session_file": None, "exists": False, "error": redact_text(str(exc))}

        info: dict[str, Any] = {
            "player": redact_text(player),
            "kolmafia_home": str(settings.kolmafia_home),
            "transport": settings.transport,
        }

        if session_path is None:
            info.update({"session_file": None, "exists": False, "reason": "player_name_unset"})
            record_evidence("don_session_status", "offline", "kolmafa.bridge", "player_name_unset")
            return info

        exists = session_path.is_file()
        info.update({"session_file": str(session_path), "exists": exists})

        if exists:
            try:
                stat = session_path.stat()
                info.update({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
                # Do not tail entire log; just report existence and cursor status if DB available
                try:
                    with db.connect(settings.database_path) as conn:
                        events = bridge.read_safe_session_events(session_path, player)
                        info.update({"recent_user_events": len(events)})
                        # Redacted sample count only, not bodies
                        if events:
                            info.update({"sample_event_id": events[0].event_id})
                except Exception:
                    pass
            except Exception as exc:
                info.update({"error": redact_text(str(exc))})

        if settings.transport != "docker-free" and player != "unknown":
            try:
                account = dev_inspection.account_session_snapshot(timeout=10.0)
                info.update(
                    {
                        "logged_in": account.get("logged_in", False),
                        "active_player": account.get("player"),
                        "matches_expected": account.get("matches_expected", False),
                        "account_proven": account.get("proven", False),
                        "active_session_pointer": account.get("active_session_pointer"),
                        "active_session_pointer_exists": account.get("active_session_pointer_exists", False),
                        "evidence_tier": account.get("evidence"),
                    }
                )
            except Exception as exc:
                info.update({"logged_in": False, "active_player": None, "account_proven": False, "error": redact_text(str(exc))})

        # Also include readiness docker_free problems
        readiness = get_readiness()
        info.update(
            {
                "docker_free_ready": readiness.get("docker_free_ready"),
                "docker_free_problems": readiness.get("docker_free_problems"),
                "overall": readiness.get("overall"),
            }
        )
        record_evidence("don_session_status", "offline", "kolmafa.bridge", f"exists={exists}")
        return info

    def relay_snapshot(self) -> dict[str, Any]:
        """Return read-only relay snapshot (T1 live-read, no mutation)."""

        return dev_inspection.relay_snapshot()

    def equipment_snapshot(self, native_transport: Any | None = None) -> dict[str, Any]:
        """Return narrow read-only equipment/inventory snapshot (live-read).

        An explicit native transport refines only the equipability preflight;
        the default preserves fail-closed UNKNOWN.
        """

        return dev_inspection.equipment_snapshot(native_transport=native_transport)

    def propose_action(self, action: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Propose a game-affecting action via broker (no execution)."""

        # Explicit dry-run writer: MCP/test/inspection surfaces must never
        # infer a live writer from env. Live transport requires explicit
        # injection by a commissioned caller, not env inference.
        broker = ActionBroker(writer=DryRunGcliWriter())
        return broker.propose(action, arguments)

    def execute_approved(self, proposal_id: str, expected_action: str | None = None, expected_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a previously confirmed proposal via broker DryRunGcliWriter/fake transport only.

        The broker is constructed with an explicitly injected DryRunGcliWriter,
        never via environment inference, so a test/mock dry-run selection can
        never resolve to a live RelayWriter even when KOLMAFA_LIVE_RELAY_ENABLED
        is set. There is no live fallback on this surface.
        """

        broker = ActionBroker(writer=DryRunGcliWriter())
        return broker.execute_approved(proposal_id, expected_action=expected_action, expected_arguments=expected_arguments)
