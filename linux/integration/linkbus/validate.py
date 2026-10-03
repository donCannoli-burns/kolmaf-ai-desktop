"""Validate kolmaf-provider/v1 manifests and canonical kolmaf:// identities.

Read-only: parses JSON manifests, checks enums/URIs/relationships, and probes
installed-target existence with os.path.exists. No network, no gameplay,
no relay, no filesystem writes. Stdlib only.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

SCHEMA_PROVIDER = "kolmaf-provider/v1"

AUTHORITY = frozenset(
    [
        "NAVIGATION_ONLY",
        "REFERENCE_ONLY",
        "GUIDANCE_ONLY",
        "OBSERVATION_ONLY",
        "TEST_ONLY",
        "LOCAL_DOCUMENT_WRITE",
        "GOVERNED_MUTATION",
        "STRUCTURAL_DENY",
    ]
)

FRESHNESS = frozenset(
    ["STATIC", "VERSIONED", "SESSION", "LIVE", "DERIVED", "HISTORICAL"]
)

RELATIONSHIPS = frozenset(
    [
        "DOCUMENTS",
        "PROVIDES",
        "IMPLEMENTS",
        "DEPENDS_ON",
        "REFERENCES",
        "RELATED_TO",
        "TESTED_BY",
        "CAN_VERIFY",
        "CAN_RENDER",
        "GENERATED_FROM",
        "OBSERVED_FROM",
    ]
)

URI_RE = re.compile(r"^kolmaf://[a-z0-9][a-z0-9\-_]*(/[a-z0-9][a-z0-9\-_.]+)+$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]*$")

EXPECTED_PROVIDER_IDS = frozenset(
    [
        "kol-agent-sandbox",
        "tokens-of-loathing",
        "kol-agent-memory",
        "kolmafia-skills",
        "kol-ash-it-down",
        "kol-goblin-docs",
        "kol-html-matrix",
    ]
)


def error(code: str, message: str, field: str = "") -> dict:
    return {"code": code, "message": message, "field": field}


def expand_target_path(raw: str) -> str:
    """Expand ~ and $VARS for installed-target probes (read-only)."""
    return os.path.expandvars(os.path.expanduser(raw))


def load_manifests(provider_dir: Path) -> tuple[list[dict], list[dict], list[str]]:
    """Load every *.json manifest, sorted by filename for determinism."""
    errors: list[dict] = []
    docs: list[dict] = []
    files: list[str] = []
    if not provider_dir.is_dir():
        return docs, [error("PROVIDER_MISSING", f"provider dir absent: {provider_dir}")], files
    for path in sorted(provider_dir.glob("*.json")):
        files.append(path.name)
        try:
            docs.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(error("INVALID_MANIFEST", f"{path.name}: {exc}", path.name))
    if not docs and not errors:
        errors.append(error("PROVIDER_MISSING", f"no manifests in {provider_dir}"))
    return docs, errors, files


def validate_manifest_structure(doc: dict, source: str = "") -> list[dict]:
    """Field/enum/URI-shape checks for one manifest. No existence probes."""
    errors: list[dict] = []
    if not isinstance(doc, dict):
        return [error("INVALID_MANIFEST", f"{source}: manifest is not an object", source)]
    if doc.get("schema") != SCHEMA_PROVIDER:
        errors.append(
            error(
                "INVALID_SCHEMA",
                f"{source}: schema must be {SCHEMA_PROVIDER!r}",
                "schema",
            )
        )
    manifest_id = doc.get("id")
    if not isinstance(manifest_id, str) or not ID_RE.match(manifest_id):
        errors.append(error("INVALID_ID", f"{source}: bad provider id", "id"))
    uri = doc.get("uri")
    if not isinstance(uri, str) or not URI_RE.match(uri):
        errors.append(error("INVALID_URI", f"{source}: malformed kolmaf:// uri", "uri"))
    authority = doc.get("authority")
    if authority not in AUTHORITY:
        errors.append(
            error("UNKNOWN_AUTHORITY", f"{source}: unknown authority {authority!r}", "authority")
        )
    freshness = doc.get("freshness")
    if freshness is not None and freshness not in FRESHNESS:
        errors.append(
            error("UNKNOWN_FRESHNESS", f"{source}: unknown freshness {freshness!r}", "freshness")
        )
    for field in ("targets", "relationships"):
        if not isinstance(doc.get(field), list):
            errors.append(
                error("MISSING_FIELD", f"{source}: {field!r} must be a list", field)
            )
    for i, target in enumerate(doc.get("targets", [])):
        field = f"targets[{i}]"
        if not isinstance(target, dict):
            errors.append(error("INVALID_TARGET", f"{source}: {field} not an object", field))
            continue
        turi = target.get("uri")
        if not isinstance(turi, str) or not URI_RE.match(turi):
            errors.append(error("INVALID_URI", f"{source}: {field} malformed uri", field))
        if not isinstance(target.get("path"), str) or not target.get("path"):
            errors.append(error("INVALID_TARGET", f"{source}: {field} empty path", field))
        if not isinstance(target.get("required"), bool):
            errors.append(error("INVALID_TARGET", f"{source}: {field} required flag", field))
        kind = target.get("kind", "file")
        if kind not in ("file", "dir"):
            errors.append(error("INVALID_TARGET", f"{source}: {field} bad kind", field))
    for i, rel in enumerate(doc.get("relationships", [])):
        field = f"relationships[{i}]"
        if not isinstance(rel, dict):
            errors.append(error("INVALID_RELATIONSHIP", f"{source}: {field} not object", field))
            continue
        if rel.get("type") not in RELATIONSHIPS:
            errors.append(
                error(
                    "UNKNOWN_RELATIONSHIP",
                    f"{source}: {field} unknown type {rel.get('type')!r}",
                    field,
                )
            )
        rtarget = rel.get("target")
        if not isinstance(rtarget, str) or not URI_RE.match(rtarget):
            errors.append(error("INVALID_URI", f"{source}: {field} malformed target", field))
    return errors


def check_duplicates(docs: list[dict]) -> list[dict]:
    errors: list[dict] = []
    seen_ids: dict[str, int] = {}
    seen_uris: dict[str, int] = {}
    for doc in docs:
        manifest_id = doc.get("id")
        uri = doc.get("uri")
        if isinstance(manifest_id, str):
            seen_ids[manifest_id] = seen_ids.get(manifest_id, 0) + 1
        if isinstance(uri, str):
            seen_uris[uri] = seen_uris.get(uri, 0) + 1
    for manifest_id, count in sorted(seen_ids.items()):
        if count > 1:
            errors.append(error("DUPLICATE_ID", f"duplicate provider id: {manifest_id}", "id"))
    for uri, count in sorted(seen_uris.items()):
        if count > 1:
            errors.append(error("DUPLICATE_URI", f"duplicate provider uri: {uri}", "uri"))
    return errors


def check_expected(docs: list[dict]) -> list[dict]:
    errors: list[dict] = []
    found = {doc.get("id") for doc in docs if isinstance(doc.get("id"), str)}
    for missing in sorted(EXPECTED_PROVIDER_IDS - found):
        errors.append(error("PROVIDER_MISSING", f"expected provider manifest absent: {missing}"))
    for extra in sorted(found - EXPECTED_PROVIDER_IDS):
        errors.append(error("UNEXPECTED_PROVIDER", f"unexpected provider manifest: {extra}"))
    return errors


def collect_registered_uris(docs: list[dict]) -> set[str]:
    registered: set[str] = set()
    for doc in docs:
        uri = doc.get("uri")
        if isinstance(uri, str) and URI_RE.match(uri):
            registered.add(uri)
        for target in doc.get("targets", []) or []:
            if isinstance(target, dict):
                turi = target.get("uri")
                if isinstance(turi, str) and URI_RE.match(turi):
                    registered.add(turi)
    return registered


def check_relationship_targets(docs: list[dict]) -> list[dict]:
    registered = collect_registered_uris(docs)
    errors: list[dict] = []
    for doc in docs:
        for rel in doc.get("relationships", []) or []:
            if not isinstance(rel, dict):
                continue
            target = rel.get("target")
            if isinstance(target, str) and URI_RE.match(target) and target not in registered:
                errors.append(
                    error(
                        "UNKNOWN_URI",
                        f"{doc.get('id')}: relationship target not registered: {target}",
                        "relationships",
                    )
                )
    return errors


def check_targets_exist(doc: dict) -> tuple[list[dict], list[dict]]:
    """Probe installed targets read-only. Returns (missing_required, missing_optional)."""
    missing_required: list[dict] = []
    missing_optional: list[dict] = []
    for target in doc.get("targets", []) or []:
        if not isinstance(target, dict):
            continue
        path = expand_target_path(str(target.get("path", "")))
        if os.path.exists(path):
            continue
        record = {
            "uri": target.get("uri"),
            "path": target.get("path"),
            "provider": doc.get("id"),
        }
        if target.get("required") is True:
            missing_required.append(record)
        else:
            missing_optional.append(record)
    return missing_required, missing_optional


def validate_all(provider_dir: Path) -> tuple[list[dict], list[dict], list[str]]:
    """Full structural validation: load, structure, expected set, duplicates, refs."""
    docs, errors, files = load_manifests(provider_dir)
    for doc, name in zip(docs, files):
        errors.extend(validate_manifest_structure(doc, name))
    errors.extend(check_expected(docs))
    errors.extend(check_duplicates(docs))
    errors.extend(check_relationship_targets(docs))
    return docs, errors, files


def resolve(uri: str, registry: dict) -> tuple[dict | None, dict | None]:
    """Resolve one kolmaf:// URI against a compiled registry. No fallback."""
    if not isinstance(uri, str) or not URI_RE.match(uri):
        return None, error("INVALID_URI", f"malformed kolmaf:// uri: {uri!r}")
    identities = registry.get("identities", {})
    entry = identities.get(uri)
    if entry is None:
        for provider in registry.get("providers", []):
            if provider.get("uri") == uri:
                return {"provider": provider.get("id"), "uri": uri, "kind": "provider"}, None
        return None, error("NOT_FOUND", f"unknown registered uri: {uri}")
    return entry, None
