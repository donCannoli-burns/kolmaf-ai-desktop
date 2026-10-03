"""Pure local KoLmafia item identity resolution for Don Edition."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parents[3] / "data" / "item_identity.json"
CATALOG_SCHEMA = "kolmafa-item-identity-v1"


@dataclass(frozen=True, slots=True)
class CanonicalItem:
    """Canonical identity resolved from the frozen local catalog."""

    id: int
    canonical_name: str


def _load_catalog() -> dict[str, str]:
    try:
        payload: Any = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("item identity catalog is unavailable or corrupt") from exc

    if not isinstance(payload, dict) or payload.get("schema") != CATALOG_SCHEMA:
        raise ValueError("item identity catalog schema is invalid")
    source = payload.get("source")
    items = payload.get("items")
    if not isinstance(source, dict) or not isinstance(items, dict) or not items:
        raise ValueError("item identity catalog provenance or entries are invalid")
    for field in ("kind", "path", "sha256", "kolmafia_revision", "items_version", "file_size"):
        if field not in source:
            raise ValueError(f"item identity catalog provenance missing {field}")

    resolved: dict[str, str] = {}
    for raw_id, raw_name in items.items():
        if not isinstance(raw_id, str) or not raw_id.isdigit() or int(raw_id) <= 0:
            raise ValueError("item identity catalog contains an invalid item id")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("item identity catalog contains an empty item name")
        resolved[str(int(raw_id))] = raw_name
    return resolved


def resolve_item_id(item_id: int) -> CanonicalItem:
    """Resolve a positive numeric item ID from the frozen local catalog.

    This function performs no HTTP, relay, process, credential, or filesystem
    mutation. Unknown and malformed IDs fail closed.
    """
    if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
        raise ValueError("item id must be a positive integer")
    try:
        canonical_name = _load_catalog()[str(item_id)]
    except KeyError as exc:
        raise ValueError(f"unknown item id: {item_id}") from exc
    return CanonicalItem(id=item_id, canonical_name=canonical_name)


def resolve_item_name(item_id: Any, approved_name: Any) -> CanonicalItem:
    """Validate a numeric ID and exact canonical name from the frozen catalog."""
    if isinstance(item_id, str):
        if not item_id.strip().isdigit():
            raise ValueError("item id must be a positive numeric value")
        normalized_id = int(item_id.strip())
    elif isinstance(item_id, int) and not isinstance(item_id, bool):
        normalized_id = item_id
    else:
        raise ValueError("item id must be a positive numeric value")
    if not isinstance(approved_name, str) or not approved_name.strip():
        raise ValueError("item name is required")
    if any(char in approved_name for char in "\r\n\x00"):
        raise ValueError("item name contains control characters")

    resolved = resolve_item_id(normalized_id)
    if approved_name.strip().casefold() != resolved.canonical_name.casefold():
        raise ValueError(
            f"item id/name mismatch for {resolved.id}: "
            f"expected canonical name {resolved.canonical_name!r}"
        )
    return resolved
