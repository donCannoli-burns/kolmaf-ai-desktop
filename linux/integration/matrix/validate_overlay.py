"""Validate a built kolmaf Matrix overlay against registry + corpus (Slice 3).

Checks projection completeness, enum fidelity, authority non-promotion,
alias grounding, and identifier uniqueness. Never modifies anything.
"""

from __future__ import annotations

from linkbus.validate import AUTHORITY, FRESHNESS, RELATIONSHIPS, error

from .build_overlay import OVERLAY_SCHEMA, ROOT_ID, ROOT_TITLE


def validate_overlay(overlay: dict, registry: dict, corpus_pointers: set) -> list[dict]:
    errors: list[dict] = []
    if not isinstance(overlay, dict) or overlay.get("schema") != OVERLAY_SCHEMA:
        return [error("INVALID_OVERLAY", "overlay is not kolmaf-overlay/v1")]
    providers = overlay.get("providers", []) or []
    identities = overlay.get("identities", []) or []
    registry_providers = {p.get("uri"): p for p in registry.get("providers", [])}
    registry_identities = registry.get("identities", {})

    root = overlay.get("root")
    if not isinstance(root, dict) or root.get("overlay_id") != ROOT_ID:
        errors.append(error("INVALID_OVERLAY", "constellation root missing"))
    elif root.get("title") != ROOT_TITLE or root.get("uri") is not None:
        errors.append(error("INVALID_OVERLAY", "constellation root identity wrong"))
    elif sorted(root.get("children", []) or []) != sorted(
        n.get("overlay_id") for n in providers
    ):
        errors.append(error("INVALID_OVERLAY", "root children mismatch providers"))

    if len(providers) != 7:
        errors.append(error("PROVIDER_MISSING", f"expected 7 provider roots, got {len(providers)}"))
    if len(identities) != len(registry_identities):
        errors.append(
            error(
                "IDENTITY_COUNT_MISMATCH",
                f"overlay {len(identities)} targets vs registry {len(registry_identities)}",
            )
        )

    seen_overlay_ids: set[str] = set()
    seen_uris: set[str] = set()
    for node in providers + identities:
        oid = node.get("overlay_id")
        uri = node.get("uri")
        if oid in seen_overlay_ids:
            errors.append(error("DUPLICATE_URI", f"duplicate overlay id: {oid}"))
        seen_overlay_ids.add(oid)
        if uri in seen_uris:
            errors.append(error("DUPLICATE_URI", f"duplicate overlay uri: {uri}"))
        seen_uris.add(uri)
        if node.get("authority") not in AUTHORITY:
            errors.append(error("UNKNOWN_AUTHORITY", f"{oid}: unknown authority"))
        if node.get("freshness") not in FRESHNESS:
            errors.append(error("UNKNOWN_FRESHNESS", f"{oid}: unknown freshness"))
        if node.get("kind") == "provider":
            expected = registry_providers.get(uri)
            if expected is None:
                errors.append(error("UNKNOWN_PROVIDER", f"{oid}: provider uri not registered"))
            elif node.get("authority") != expected.get("authority"):
                errors.append(
                    error("AUTHORITY_PROMOTED", f"{oid}: authority differs from registry")
                )
        else:
            expected = registry_identities.get(uri)
            if expected is None:
                errors.append(error("UNKNOWN_URI", f"{oid}: target uri not registered"))
            elif node.get("authority") != _provider_authority(registry, expected):
                errors.append(
                    error("AUTHORITY_PROMOTED", f"{oid}: authority differs from registry")
                )
        for rel in node.get("relationships", []) or []:
            if rel.get("type") not in RELATIONSHIPS:
                errors.append(error("UNKNOWN_RELATIONSHIP", f"{oid}: bad relation type"))
            if rel.get("target") not in registry_providers and (
                rel.get("target") not in registry_identities
            ):
                errors.append(error("UNKNOWN_URI", f"{oid}: relation target not registered"))

    for alias in overlay.get("aliases", []) or []:
        if alias.get("mem_pointer") not in corpus_pointers:
            errors.append(error("NOT_FOUND", f"alias mem pointer absent: {alias}"))
        if alias.get("kolmaf_uri") not in registry_providers and (
            alias.get("kolmaf_uri") not in registry_identities
        ):
            errors.append(error("UNKNOWN_URI", f"alias kolmaf uri not registered: {alias}"))
    return errors


def _provider_authority(registry: dict, identity: dict) -> str | None:
    for provider in registry.get("providers", []):
        if provider.get("id") == identity.get("provider"):
            return provider.get("authority")
    return None
