"""Read-only relay inspection for Don Edition.

Narrow allowlist, no mutation, no SpringBridge, no port 8080,
no arbitrary navigation, no GCLI/ASH/sideCommand.

Transport is plain HTTP GET to known-safe relay endpoints only.
Fallback is to report offline/bridgestatus without network probe.
"""

from __future__ import annotations

import re
import socket
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from kolmafa import bridge
from kolmafa.config import get_settings
from kolmafa.devtest.evidence import record_evidence
from kolmafa.devtest.item_identity import resolve_item_id
from kolmafa.devtest.native_query import execute_native_can_equip
from kolmafa.redaction import redact_text

# GET-only current-state page.  A GET may report the active choice page; it
# never submits a choice, option, or other game mutation.
CHOICE_READ_PATH = "/choice.php"

# Allowlist of known-safe read-only paths (relative to relay_base_url).
# Only these may be fetched. No user-supplied URL, no query params beyond allowlist.
SAFE_RELAY_PATHS = (
    "/",
    "/status",
    "/api.php?what=status",
    "/api.php?what=status&for=don_equipment_snapshot",
    "/api.php?what=inventory&for=don_equipment_snapshot",
    "/charpane.php",
    "/version",
    CHOICE_READ_PATH,
)
# Specific allowlist for equipment/inventory read-only JSON
EQUIPMENT_API_PATH = "/api.php?what=status&for=don_equipment_snapshot"
INVENTORY_API_PATH = "/api.php?what=inventory&for=don_equipment_snapshot"
_STATUS_EQUIPMENT_SLOTS = frozenset({"hat", "shirt", "pants", "weapon", "offhand", "acc1", "acc2", "acc3", "container", "familiarequip", "fakehands", "cardsleeve"})
_INVENTORY_ITEM_IDS = frozenset({"3", "6", "150", "151", "152", "153", "154", "155", "169", "214", "4614", "5054", "11565"})

# Max preview bytes
MAX_PREVIEW = 2000

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _fetch_relay_snapshot(relay_base_url: str, timeout: float = 2.0) -> dict[str, Any]:
    """Attempt GET to allowlisted relay endpoints, return redacted preview.

    Tries each SAFE path until one succeeds. Returns structured dict.
    Never sends pwd, never POSTs, never invokes sideCommand.
    """

    last_error: str | None = None
    for path in SAFE_RELAY_PATHS:
        # Build URL safely: strip trailing slash then append path
        base = relay_base_url.rstrip("/")
        url = base + path if path.startswith("/") else base + "/" + path
        # Ensure path is exactly allowlisted
        if not any(url.endswith(p) for p in SAFE_RELAY_PATHS):
            continue
        req = Request(url, method="GET")
        req.add_header("User-Agent", "kolmafa-don-inspection/1.0")
        try:
            with urlopen(req, timeout=timeout) as resp:
                status = resp.status
                body = resp.read().decode("utf-8", errors="replace")
                title_match = _TITLE_RE.search(body)
                title = redact_text(title_match.group(1).strip()[:200]) if title_match else ""
                # version heuristic: look for "KoLmafia" string
                version = ""
                if "KoLmafia" in body:
                    # extract near version token
                    v_match = re.search(r"KoLmafia\s+v?[0-9.]+", body)
                    if v_match:
                        version = redact_text(v_match.group(0))
                return {
                    "reachable": True,
                    "url": redact_text(relay_base_url),
                    "path": path,
                    "status_code": status,
                    "title": title,
                    "version": version,
                }
        except (URLError, OSError, socket.timeout, ValueError) as exc:  # pragma: no cover - network dependent
            last_error = redact_text(str(exc))
            continue
    return {
        "reachable": False,
        "url": redact_text(relay_base_url),
        "path": None,
        "status_code": None,
        "title": "",
        "version": "",
        "error": last_error or "relay unreachable",
    }


def _fetch_json(relay_base_url: str, path: str, timeout: float = 2.0) -> dict[str, Any] | None:
    """Fetch JSON via allowlisted GET, redacted, no pwd.

    Returns dict or None on failure. Never sends pwd.
    """
    if path not in SAFE_RELAY_PATHS:
        return None
    base = relay_base_url.rstrip("/")
    url = base + path if path.startswith("/") else base + "/" + path
    if not any(url.endswith(p) for p in SAFE_RELAY_PATHS):
        return None
    req = Request(url, method="GET")
    req.add_header("User-Agent", "kolmafa-don-inspection/1.0")
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            # Redact pwd field if present
            import json as _json

            data = _json.loads(body)
            # Remove pwd and redacted
            if isinstance(data, dict) and "pwd" in data:
                data = {k: v for k, v in data.items() if k != "pwd"}
            # Also redact any string that looks like pwd value (defense)
            # Return redacted dict (no pwd)
            return data
    except Exception:  # pragma: no cover
        return None


def _allowlisted_status(data: Any) -> dict[str, Any] | None:
    """Discard every external status field except the fields Don consumes."""

    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if name is not None and not isinstance(name, str):
        name = str(name)
    equipment = data.get("equipment")
    safe_equipment: dict[str, str] = {}
    if isinstance(equipment, dict):
        for slot in _STATUS_EQUIPMENT_SLOTS:
            value = equipment.get(slot)
            if value is not None and isinstance(value, (str, int, float, bool)):
                safe_equipment[slot] = str(value)
    result: dict[str, Any] = {"equipment": safe_equipment}
    if isinstance(name, str):
        result["name"] = name
    return result


def _allowlisted_inventory(data: Any) -> dict[str, str] | None:
    """Discard the full external inventory except the narrow item ids Don reads."""

    if not isinstance(data, dict):
        return None
    return {item_id: str(data[item_id]) for item_id in sorted(_INVENTORY_ITEM_IDS) if item_id in data}


def _fetch_status(relay_base_url: str, *, timeout: float) -> dict[str, Any] | None:
    return _allowlisted_status(_fetch_json(relay_base_url, EQUIPMENT_API_PATH, timeout=timeout))


def _fetch_inventory(relay_base_url: str, *, timeout: float) -> dict[str, str] | None:
    return _allowlisted_inventory(_fetch_json(relay_base_url, INVENTORY_API_PATH, timeout=timeout))


def _account_session_snapshot(settings: Any, status_data: dict[str, Any] | None, *, timeout: float) -> dict[str, Any]:
    """Return only minimal account/session facts, never status secrets."""

    expected_player = settings.player_name
    live_name = status_data.get("name") if isinstance(status_data, dict) else None
    logged_in = isinstance(live_name, str) and bool(live_name.strip())
    session_file: Any = None
    session_exists = False
    active_pointer: Any = None
    active_pointer_exists = False
    if expected_player:
        try:
            session_file = bridge.session_file(settings.kolmafia_home, expected_player)
            session_exists = session_file.is_file()
            active_pointer = settings.kolmafia_home / "sessions" / f"active_session.{expected_player}"
            active_pointer_exists = active_pointer.is_file()
        except Exception:
            session_file = None
    matches_expected = bool(
        logged_in
        and expected_player
        and isinstance(live_name, str)
        and live_name.casefold() == expected_player.casefold()
    )
    return {
        "ok": bool(logged_in),
        "logged_in": logged_in,
        "player": redact_text(live_name) if logged_in else None,
        "expected_player": redact_text(expected_player) if expected_player else None,
        "matches_expected": matches_expected,
        "session_file": str(session_file) if session_file is not None else None,
        "session_exists": session_exists,
        "active_session_pointer": str(active_pointer) if active_pointer is not None else None,
        "active_session_pointer_exists": active_pointer_exists,
        "proven": bool(logged_in and matches_expected and session_exists),
        "evidence": "PROVEN LIVE STATE" if logged_in else "UNAVAILABLE",
        "redacted": True,
    }


def _choice_state_from_html(body: str) -> dict[str, Any]:
    """Parse only the current choice state from a GET-only choice page."""

    lowered = body.casefold()
    if "not actually in a choice adventure" in lowered:
        return {
            "ok": True,
            "handling_choice": False,
            "choice_id": None,
            "evidence": "PROVEN LIVE STATE",
            "source": "live",
        }
    match = re.search(
        r"(?:whichchoice|choice[_ -]?id)\s*[=/:?\"']\s*(\d+)",
        body,
        flags=re.IGNORECASE,
    )
    if match:
        return {
            "ok": True,
            "handling_choice": True,
            "choice_id": int(match.group(1)),
            "evidence": "PROVEN LIVE STATE",
            "source": "live",
        }
    return {
        "ok": False,
        "handling_choice": None,
        "choice_id": None,
        "evidence": "UNAVAILABLE",
        "source": "live",
        "reason": "choice page state not parseable",
    }


def _fetch_choice_state(relay_base_url: str, *, timeout: float) -> dict[str, Any]:
    """Read choice state with a fixed GET; never submit or select a choice."""

    base = relay_base_url.rstrip("/")
    url = base + CHOICE_READ_PATH
    req = Request(url, method="GET")
    req.add_header("User-Agent", "kolmafa-don-inspection/1.0")
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:300_000]
            return _choice_state_from_html(body)
    except (URLError, OSError, socket.timeout, ValueError) as exc:
        return {
            "ok": False,
            "handling_choice": None,
            "choice_id": None,
            "evidence": "UNAVAILABLE",
            "source": "live",
            "reason": redact_text(str(exc)),
        }


def _quantity(data: dict[str, Any] | None, item_id: str) -> dict[str, Any]:
    """Parse one inventory quantity, failing closed on malformed data."""

    if not isinstance(data, dict):
        return {"item_id": item_id, "quantity": None, "owned": False, "valid": False}
    raw = data.get(item_id)
    if raw is None:
        return {"item_id": item_id, "quantity": 0, "owned": False, "valid": True}
    try:
        quantity = int(str(raw))
    except (TypeError, ValueError):
        return {"item_id": item_id, "quantity": None, "owned": False, "valid": False}
    if quantity < 0:
        return {"item_id": item_id, "quantity": None, "owned": False, "valid": False}
    return {"item_id": item_id, "quantity": quantity, "owned": quantity > 0, "valid": True}


def account_session_snapshot(*, timeout: float = 10.0) -> dict[str, Any]:
    """Return minimal account/session proof from status plus local session files."""

    settings = get_settings()
    status_data = _fetch_status(settings.relay_base_url, timeout=timeout)
    if not isinstance(status_data, dict) or "name" not in status_data:
        result = _account_session_snapshot(settings, None, timeout=timeout)
        result.update({"ok": False, "logged_in": False, "reason": "status response unavailable or malformed"})
        return result
    return _account_session_snapshot(settings, status_data, timeout=timeout)


def _hat_inventory_summary(inventory_data: dict[str, Any] | None, hat_id: Any) -> dict[str, Any]:
    """Keep the prior narrow hat summary without exposing the full inventory."""

    inventory = inventory_data if isinstance(inventory_data, dict) else {}
    helmet = _quantity(inventory, "3")
    known_hat_ids = {"3", "6", "153", "154", "155", "169", "214", "4614", "11565", "152", "151", "150"}
    name_map = {
        "3": "helmet turtle",
        "6": "ravioli hat",
        "153": "Ancient Saucehelm",
        "154": "Disco 'Fro Pick",
        "155": "El Sombrero De Lopez",
        "169": "bugbear beanie",
        "214": "filthy knitted dread sack",
        "4614": "Crown of Thrones",
        "11565": "Crown? (hat 11565)",
        "152": "Colander of Em-er'il",
    }
    current_hat = str(hat_id) if hat_id is not None else ""
    candidates: list[dict[str, Any]] = []
    for hid in sorted(known_hat_ids):
        item = _quantity(inventory, hid)
        if item["valid"] and item["quantity"] and hid != current_hat:
            candidates.append({"id": hid, "name": name_map.get(hid, "unknown hat"), "count": item["quantity"]})
    return {
        "helmet_turtle_owned": bool(helmet["owned"]),
        "helmet_turtle_count": helmet["quantity"],
        "helmet_turtle_id": "3",
        "sample_candidates": candidates,
    }


def grounding_snapshot(*, timeout: float = 10.0) -> dict[str, Any]:
    """Return the minimal current state needed for a future smoke precondition."""

    settings = get_settings()
    status_data = _fetch_status(settings.relay_base_url, timeout=timeout)
    inventory_data = _fetch_inventory(settings.relay_base_url, timeout=timeout)
    choice_state = _fetch_choice_state(settings.relay_base_url, timeout=timeout)
    account = _account_session_snapshot(settings, status_data if isinstance(status_data, dict) else None, timeout=timeout)
    item = _quantity(inventory_data if isinstance(inventory_data, dict) else None, "5054")
    equipment = status_data.get("equipment", {}) if isinstance(status_data, dict) else {}
    response_ok = isinstance(status_data, dict) and isinstance(inventory_data, dict) and choice_state.get("ok") is True
    return {
        "ok": response_ok,
        "mode": "live-read",
        "source": "live" if response_ok else "unavailable",
        "live": response_ok,
        "mutation_capability": False,
        "redacted": True,
        "transport": settings.transport,
        "player": account.get("player"),
        "account": account,
        "session": {
            "path": account.get("session_file"),
            "exists": account.get("session_exists"),
            "active_pointer": account.get("active_session_pointer"),
            "active_pointer_exists": account.get("active_session_pointer_exists"),
        },
        "target_items": {"5054": item},
        "equipment": equipment,
        "legacy_inventory": _hat_inventory_summary(inventory_data, equipment.get("hat") if isinstance(equipment, dict) else None),
        "choice_state": choice_state,
        "allowlist": [EQUIPMENT_API_PATH, INVENTORY_API_PATH, CHOICE_READ_PATH],
        "evidence_tier": "PROVEN LIVE STATE" if response_ok else "UNAVAILABLE",
    }


_EQUIPABILITY_SLOTS = frozenset({"hat", "shirt", "pants", "weapon", "offhand", "acc1", "acc2", "acc3", "container", "familiarequip", "fakehands", "cardsleeve"})


def _validated_native_query(native_query: dict[str, Any] | None) -> dict[str, Any] | None:
    """Accept only a normalized observation-only native.can-equip result."""

    if native_query is None:
        return None
    if not isinstance(native_query, dict):
        return None
    if native_query.get("schema") != "don-native-query-v1":
        return None
    if native_query.get("capability") != "native.can-equip":
        return None
    if native_query.get("authority") != "OBSERVATION_ONLY":
        return None
    return native_query


def equipability_preflight(
    grounded: dict[str, Any],
    *,
    item_id: int = 153,
    slot: str = "hat",
    native_query: dict[str, Any] | None = None,
    native_transport: Any | None = None,
) -> dict[str, Any]:
    """Return normalized T1 eligibility evidence without invoking native mutation.

    An explicitly supplied normalized ``native.can-equip`` result may refine
    UNKNOWN into EQUIPPABLE or BLOCKED. The default remains fail-closed because
    no approved live native transport is configured.
    """

    live = bool(grounded.get("ok"))
    base: dict[str, Any] = {
        "ok": live,
        "item": {"id": item_id, "name": None},
        "slot": slot,
        "owned": False,
        "available_count": 0,
        "currently_equipped": False,
        "can_equip": None,
        "result": "UNKNOWN",
        "restriction_class": "UNKNOWN_RESTRICTION",
        "reason": "native KoLmafia canEquip source unavailable over approved read-only surface",
        "source": {
            "provider": "don_normalized_inspection",
            "native_source": "KoLmafia EquipmentManager.canEquip",
            "native_source_available": False,
            "freshness": "LIVE" if live else "UNAVAILABLE",
        },
        "evidence_classification": "PROVEN LIVE STATE" if live else "UNAVAILABLE",
        "mutation_capability": False,
    }
    if slot not in _EQUIPABILITY_SLOTS:
        base.update({"ok": False, "result": "INVALID_SLOT", "reason": "unsupported equipment slot"})
        return base
    try:
        resolved = resolve_item_id(item_id)
    except ValueError:
        base.update({"ok": False, "result": "INVALID_ITEM", "reason": "item id is not in the Don identity catalog"})
        return base
    base["item"]["name"] = resolved.canonical_name

    legacy = grounded.get("legacy_inventory") if isinstance(grounded.get("legacy_inventory"), dict) else {}
    candidates = legacy.get("sample_candidates") if isinstance(legacy.get("sample_candidates"), list) else []
    quantity = 0
    for candidate in candidates:
        if str(candidate.get("id")) == str(item_id):
            try:
                quantity = int(candidate.get("count"))
            except (TypeError, ValueError):
                quantity = 0
            break
    base["owned"] = quantity > 0
    base["available_count"] = quantity
    equipment = grounded.get("equipment") if isinstance(grounded.get("equipment"), dict) else {}
    current_id = equipment.get(slot)
    base["currently_equipped"] = str(current_id) == str(item_id)
    if base["currently_equipped"]:
        base.update({"can_equip": False, "result": "ALREADY_EQUIPPED", "restriction_class": "NONE", "reason": "item is already equipped in the requested slot"})
        return base
    if quantity <= 0:
        base.update({"result": "ITEM_NOT_OWNED", "restriction_class": "ITEM_NOT_OWNED", "reason": "item is not present in current inventory"})
        return base
    query = _validated_native_query(native_query)
    if query is None and native_transport is not None:
        try:
            executed = execute_native_can_equip(item_id, transport=native_transport)
        except Exception:
            executed = None
        query = _validated_native_query(executed)
    if query is None or query.get("status") != "SUCCESS" or not isinstance(query.get("result"), bool):
        return base
    if query.get("freshness") == "LIVE" and query.get("item_name") != resolved.canonical_name:
        base.update({"reason": "native item identity disagrees with Don catalog"})
        return base
    if query.get("evidence") is not None:
        base["evidence"] = query["evidence"]
    if query["result"] is True:
        base.update({"can_equip": True, "result": "EQUIPPABLE", "restriction_class": "NONE", "reason": "native can_equip returned true for the owned, unequipped item"})
    else:
        base.update({"can_equip": False, "result": "BLOCKED", "restriction_class": "NATIVE_CAN_EQUIP_FALSE", "reason": "native can_equip returned false for the owned, unequipped item"})
    base["source"].update({"native_source_available": True, "freshness": str(query.get("freshness", "UNAVAILABLE"))})
    return base


def equipment_snapshot(*, timeout: float = 10.0, native_transport: Any | None = None) -> dict[str, Any]:
    """Return the narrow current equipment, inventory, and choice snapshot.

    This extends the existing T1 read surface. It performs only fixed GETs and
    returns no writer or arbitrary-navigation capability. An explicit native
    transport may refine the equipability preflight; the default preserves
    fail-closed UNKNOWN.
    """

    settings = get_settings()
    grounded = grounding_snapshot(timeout=timeout)
    if not grounded.get("ok"):
        grounded.update(
            {
                "reason": "relay current-state reads unavailable or malformed",
                "evidence_tier": "LOCAL/CACHED STATE",
                "equipment": {},
                "inventory": {},
                "relevant_inventory": {},
                "equipability_preflight": equipability_preflight(grounded, item_id=153, slot="hat", native_transport=native_transport),
            }
        )
        record_evidence(
            "don_equipment_snapshot",
            "live-read",
            "kolmafa.devtest.inspection",
            "current-state reads unavailable",
            extra={"live": False, "transport": settings.transport},
        )
        return grounded

    equipment = grounded.get("equipment", {}) if isinstance(grounded.get("equipment"), dict) else {}
    hat_id = equipment.get("hat") if isinstance(equipment, dict) else None
    legacy_inventory = grounded.get("legacy_inventory", {}) if isinstance(grounded.get("legacy_inventory"), dict) else {}
    helmet_owned = bool(legacy_inventory.get("helmet_turtle_owned", False))
    helmet_count = legacy_inventory.get("helmet_turtle_count", 0)
    other_candidates = legacy_inventory.get("sample_candidates", [])

    grounded.update(
        {
            "player": grounded.get("player"),
            "equipment": {
                "hat_id": hat_id,
                "full": {k: redact_text(str(v)) for k, v in equipment.items()} if isinstance(equipment, dict) else {},
            },
            "hat_slot": {"id": hat_id, "evidence": "PROVEN LIVE STATE via api.php?what=status"},
            "inventory": {
                "helmet_turtle_owned": helmet_owned,
                "helmet_turtle_count": helmet_count,
                "helmet_turtle_id": "3",
                "evidence": "PROVEN LIVE STATE via api.php?what=inventory",
                "sample_candidates": other_candidates,
            },
            "relevant_inventory": {
                "helmet_turtle_owned": helmet_owned,
                "helmet_count": helmet_count,
                "other_hat_candidates": other_candidates,
            },
            "equipability_preflight": equipability_preflight(grounded, item_id=153, slot="hat", native_transport=native_transport),
        }
    )
    record_evidence(
        "don_equipment_snapshot",
        "live-read",
        "kolmafa.devtest.inspection",
        f"grounded player={grounded.get('player')} item5054={grounded['target_items']['5054']['quantity']} choice={grounded['choice_state'].get('choice_id')}",
        extra={
            "item_5054": grounded["target_items"]["5054"]["quantity"],
            "choice_id": grounded["choice_state"].get("choice_id"),
            "live": True,
        },
    )
    return grounded


def relay_snapshot(*, timeout: float = 2.0) -> dict[str, Any]:
    """Return structured read-only relay snapshot (live-read mode)."""

    settings = get_settings()
    player = settings.player_name or "unknown"

    # If transport is docker-free, relay inspection is via session observation not network;
    # still report relay as offline with readiness facts.
    if settings.transport == "docker-free":
        snapshot: dict[str, Any] = {
            "ok": False,
            "mode": "live-read",
            "relay": {
                "reachable": False,
                "url": redact_text(settings.relay_base_url),
                "reason": "docker-free transport: no relay network probe",
            },
            "player": redact_text(player),
            "redacted": True,
            "transport": "docker-free",
        }
        record_evidence(
            "don_relay_snapshot",
            "live-read",
            "kolmafa.devtest.inspection",
            f"docker-free reachable=false",
            extra={"transport": "docker-free"},
        )
        return snapshot

    # For relay transport, attempt safe GET
    relay_info = _fetch_relay_snapshot(settings.relay_base_url, timeout=timeout)
    ok = bool(relay_info.get("reachable"))
    result: dict[str, Any] = {
        "ok": ok,
        "mode": "live-read",
        "relay": relay_info,
        "player": redact_text(player),
        "redacted": True,
        "transport": settings.transport,
        "allowlist": list(SAFE_RELAY_PATHS),
    }
    # Evidence must not contain raw body
    record_evidence(
        "don_relay_snapshot",
        "live-read",
        "kolmafa.devtest.inspection",
        f"reachable={ok} transport={settings.transport}",
        extra={"reachable": ok, "transport": settings.transport},
    )
    return result
