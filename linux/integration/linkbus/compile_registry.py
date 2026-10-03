"""Compile validated provider manifests into a deterministic registry.

Reads integration/providers/*.json, validates, probes required installed
targets read-only, and writes data/runtime/linkbus/{registry.json,status.json,
providers/*.json}. Registry output is deterministic (sorted keys, no
timestamps); run metadata lives only in status.json. Exit 0 ok, 1 validation
errors, 2 missing required targets. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .validate import (
    check_targets_exist,
    error,
    expand_target_path,
    validate_all,
)

SCHEMA_REGISTRY = "kolmaf-registry/v1"


def write_json_deterministic(path: Path, obj: object) -> bytes:
    data = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


def build_registry(docs: list[dict]) -> dict:
    providers = []
    identities: dict[str, dict] = {}
    for doc in sorted(docs, key=lambda d: str(d.get("uri"))):
        manifest_id = doc.get("id")
        provider_entry = {
            "id": manifest_id,
            "uri": doc.get("uri"),
            "authority": doc.get("authority"),
            "freshness": doc.get("freshness"),
            "capabilities": sorted(doc.get("capabilities", []) or []),
            "identities": [],
            "relationships": sorted(
                (doc.get("relationships", []) or []),
                key=lambda r: (str(r.get("type")), str(r.get("target"))),
            ),
        }
        for target in doc.get("targets", []) or []:
            turi = target.get("uri")
            entry = {
                "provider": manifest_id,
                "uri": turi,
                "path": target.get("path"),
                "required": target.get("required"),
                "kind": target.get("kind", "file"),
            }
            provider_entry["identities"].append(entry)
            identities[str(turi)] = dict(entry)
        provider_entry["identities"].sort(key=lambda e: str(e["uri"]))
        providers.append(provider_entry)
    return {
        "schema": SCHEMA_REGISTRY,
        "uri_scheme": "kolmaf",
        "providers": providers,
        "identities": dict(sorted(identities.items())),
        "counts": {"providers": len(providers), "identities": len(identities)},
    }


def mark_exists(registry: dict) -> dict:
    """Attach read-only existence observations to every identity entry."""
    for uri, entry in registry.get("identities", {}).items():
        entry["exists"] = os.path.exists(expand_target_path(str(entry.get("path", ""))))
    for provider in registry.get("providers", []):
        for identity in provider.get("identities", []):
            identity["exists"] = registry["identities"][str(identity["uri"])]["exists"]
    return registry


def compile_all(provider_dir: Path, out_dir: Path) -> tuple[int, dict]:
    docs, errors, files = validate_all(provider_dir)
    if errors:
        return 1, {
            "ok": False,
            "errors": errors,
            "files": files,
            "counts": {"providers": len(docs), "identities": 0},
        }
    missing: list[dict] = []
    warnings: list[dict] = []
    for doc in docs:
        missing_required, missing_optional = check_targets_exist(doc)
        for record in missing_required:
            missing.append(
                {
                    "code": "REGISTERED_BUT_TARGET_MISSING",
                    "provider": record["provider"],
                    "uri": record["uri"],
                    "path": record["path"],
                }
            )
        for record in missing_optional:
            warnings.append(
                {
                    "code": "OPTIONAL_TARGET_MISSING",
                    "provider": record["provider"],
                    "uri": record["uri"],
                    "path": record["path"],
                }
            )
    if missing:
        return 2, {
            "ok": False,
            "errors": [
                error(
                    "REGISTERED_BUT_TARGET_MISSING",
                    f"{m['provider']}: required target missing: {m['uri']} -> {m['path']}",
                )
                for m in missing
            ],
            "files": files,
            "counts": {"providers": len(docs), "identities": 0},
        }
    registry = mark_exists(build_registry(docs))
    out_dir.mkdir(parents=True, exist_ok=True)
    providers_dir = out_dir / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)
    for provider in registry["providers"]:
        write_json_deterministic(providers_dir / f"{provider['id']}.json", provider)
    write_json_deterministic(out_dir / "registry.json", registry)
    status = {
        "schema": "kolmaf-linkbus-status/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "files": sorted(files),
        "counts": registry["counts"],
        "warnings": warnings,
        "errors": [],
    }
    write_json_deterministic(out_dir / "status.json", status)
    return 0, status


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve()
    default_root = here.parents[2]
    parser = argparse.ArgumentParser(description="Compile kolmaf provider registry (offline)")
    parser.add_argument("--project-root", default=str(default_root))
    parser.add_argument("--providers", default="integration/providers")
    parser.add_argument("--out", default="data/runtime/linkbus")
    args = parser.parse_args(argv)
    root = Path(args.providers)
    if not root.is_absolute():
        root = Path(args.project_root) / args.providers
    out = Path(args.out)
    if not out.is_absolute():
        out = Path(args.project_root) / args.out
    code, result = compile_all(root, out)
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
