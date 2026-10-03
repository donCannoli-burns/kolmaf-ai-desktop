"""Portable capability reconciliation for fixed native queries.

Don owns this adapter metadata; KoLmafia owns the native answers. This module
computes exactly what the portable capability directory should advertise for
``native.can-equip`` and how tool routing must classify equipability intent.
It performs no network access, no proposals, no confirmations, and no broker
or writer calls.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping


NATIVE_CAN_EQUIP_ID = "native.can-equip"
NATIVE_OWNER = "KoLmafia"
ADAPTER_OWNER = "Don"
OBSERVATION_AUTHORITY = "OBSERVATION_ONLY"


def build_registry_entry(
    *,
    helper_sha256: str,
    helper_canonical: str,
    helper_installed: str,
) -> dict[str, Any]:
    """Return the exact portable registry entry Don advertises.

    Conformant with the bundle registry schema (id/provider/authority
    required); remaining keys are descriptive metadata, never authority.
    """

    if not re.fullmatch(r"[0-9a-f]{64}", helper_sha256 or ""):
        raise ValueError("helper_sha256 must be a 64-character hex digest")
    if not helper_canonical or not helper_installed:
        raise ValueError("helper paths must be non-empty")
    return {
        "activation": "lazy",
        "adapter_owner": ADAPTER_OWNER,
        "authority": OBSERVATION_AUTHORITY,
        "context_cost": "low",
        "freshness": "LIVE",
        "helper_canonical": helper_canonical,
        "helper_installed": helper_installed,
        "helper_sha256": helper_sha256,
        "id": NATIVE_CAN_EQUIP_ID,
        "native_owner": NATIVE_OWNER,
        "provider": "don-runtime",
        "transport": {
            "caller_controls_code": False,
            "caller_controls_destination": False,
            "caller_controls_function": False,
            "method": "GET",
            "type": "fixed-relay-get",
        },
    }


def check_native_health(
    *,
    canonical: Path,
    installed: Path,
    expected_sha256: str,
    live_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Determine native.can-equip health from files, hash, and optional live proof.

    ``live_result`` is an already-normalized ``don-native-query-v1`` result or
    None when no live probe was performed. File/hash gates never pass on live
    state alone, and a live probe never passes without intact files.
    """

    checks: dict[str, bool] = {}
    try:
        checks["canonical_exists"] = canonical.is_file()
    except OSError:
        checks["canonical_exists"] = False
    try:
        installed_bytes = installed.read_bytes() if installed.is_file() else None
    except OSError:
        installed_bytes = None
    checks["installed_exists"] = installed_bytes is not None
    checks["hash_matches"] = bool(
        installed_bytes is not None
        and hashlib.sha256(installed_bytes).hexdigest() == expected_sha256
    )
    live_ok: bool | None = None
    if live_result is not None:
        live_ok = bool(
            isinstance(live_result, Mapping)
            and live_result.get("capability") == NATIVE_CAN_EQUIP_ID
            and live_result.get("status") == "SUCCESS"
            and isinstance(live_result.get("result"), bool)
        )
    checks["live_schema_recognized"] = bool(live_ok) if live_ok is not None else False

    if not checks["canonical_exists"]:
        status = "UNAVAILABLE"
    elif not checks["installed_exists"] or not checks["hash_matches"]:
        status = "DEGRADED"
    elif live_ok is False:
        status = "DEGRADED"
    else:
        status = "READY"
    return {"id": NATIVE_CAN_EQUIP_ID, "status": status, "checks": checks}


def advertisement_for_bootstrap(health_status: str) -> dict[str, Any] | None:
    """Return the bootstrap advertisement only when health is READY."""

    if health_status != "READY":
        return None
    return {
        NATIVE_CAN_EQUIP_ID: {
            "status": "READY",
            "authority": OBSERVATION_AUTHORITY,
            "freshness": "LIVE",
        }
    }


_MUTATION_VERBS = (
    "equip",
    "unequip",
    "wear",
    "put on",
    "put this on",
    "change my hat",
    "take off",
)


def route_intent(text: str) -> dict[str, Any]:
    """Classify equipability language without granting authority.

    Equipability questions route to observation; equip imperatives route to the
    governed T2 path. Observation never carries mutation authority.
    """

    lowered = (text or "").casefold()
    if not lowered.strip():
        return {"route": "none", "authority": None}
    ability_question = "?" in lowered and any(
        token in lowered
        for token in ("can i", "can my", "could i", "is this", "is it", "usable", "equipable", "wearable")
    )
    if ability_question:
        return {"route": NATIVE_CAN_EQUIP_ID, "authority": OBSERVATION_AUTHORITY}
    if any(verb in lowered for verb in _MUTATION_VERBS):
        return {"route": "don.propose-action", "authority": "T2"}
    return {"route": "none", "authority": None}
