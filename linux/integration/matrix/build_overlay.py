"""Build the kolmaf Matrix overlay from registry + corpus (Slice 3).

Read-only against the installed Matrix corpus and the validated LinkBus
registry. Writes only the generated overlay tree under the Don project.
Never modifies Matrix nodes, IDs, mem:// pointers, provenance, workflows,
or relations. No network, no gameplay, no relay. Stdlib only, plus reuse
of linkbus vocabularies and the deterministic JSON writer (the registry is
consumed, never extended).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from linkbus.compile_registry import write_json_deterministic
from linkbus.validate import AUTHORITY, FRESHNESS, RELATIONSHIPS, URI_RE, error

OVERLAY_SCHEMA = "kolmaf-overlay/v1"
ROOT_ID = "kolmaf-constellation"
ROOT_TITLE = "KOLMAF-AI CONSTELLATION"

# Provenance integrity baseline (Slice-1 inventory + Slice-3 verification).
MATRIX_BASELINE = {
    "nodes": 665,
    "unique_ids": 665,
    "mem_pointers": 665,
    "workflows": 13,
    "usecases": 29,
}

CORPUS_FILES = ("hyper-data.json", "agent-master-index.json", "source-manifest.json")

# Corpus-observed surface mentions grounding mem:// <-> kolmaf:// aliases.
# js:data-of-loathing (mem://doc-fdd0fc84c469/0023#91b7df967bf7) names the
# data-of-loathing surface; js:data-loathers-service
# (mem://doc-fdd0fc84c469/0024#7e1ef8627fef) names the hosted database the
# local dol.sqlite mirrors. Both alias to the tokens provider identity.
ALIAS_MATCH_STRINGS = {
    "tokens-of-loathing": ["data-of-loathing", "data.loathers.net"],
}

TOKEN_RE = re.compile(r"[a-z0-9]+")


def load_registry(registry_path: Path) -> tuple[dict | None, dict | None]:
    if not registry_path.is_file():
        return None, error("REGISTRY_MISSING", f"registry absent: {registry_path}")
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, error("INVALID_REGISTRY", f"registry unreadable: {exc}")
    if (
        not isinstance(registry, dict)
        or registry.get("schema") != "kolmaf-registry/v1"
        or not isinstance(registry.get("providers"), list)
        or not isinstance(registry.get("identities"), dict)
    ):
        return None, error("INVALID_REGISTRY", "registry shape is not kolmaf-registry/v1")
    return registry, None


def matrix_home_from_registry(registry: dict) -> Path | None:
    identities = registry.get("identities", {})
    entry = identities.get("kolmaf://matrix/nodes")
    if not isinstance(entry, dict) or not entry.get("path"):
        return None
    return Path(os.path.expandvars(os.path.expanduser(str(entry["path"])))).parent


def load_corpus_nodes(matrix_home: Path) -> list[dict]:
    hyper = json.loads((matrix_home / "hyper-data.json").read_text(encoding="utf-8"))
    return [n for n in hyper.get("nodes", []) if isinstance(n, dict)]


def summarize_corpus(matrix_home: Path) -> tuple[dict | None, dict | None]:
    try:
        nodes = load_corpus_nodes(matrix_home)
        hyper = json.loads((matrix_home / "hyper-data.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        return None, error("MATRIX_UNREADABLE", f"hyper-data.json unreadable: {exc}")
    ids = [n.get("id") for n in nodes]
    pointers = [n.get("pointer") for n in nodes]
    mem = [p for p in pointers if isinstance(p, str) and p.startswith("mem://")]
    return {
        "nodes": len(nodes),
        "unique_ids": len(set(ids)),
        "mem_pointers": len(mem),
        "distinct_mem_pointers": len(set(mem)),
        "workflows": len(hyper.get("workflows", [])),
        "usecases": len(hyper.get("usecases", [])),
    }, None


def corpus_pointer_index(matrix_home: Path) -> dict:
    return {str(n["pointer"]): str(n.get("id")) for n in load_corpus_nodes(matrix_home)}


def discovery_keywords(
    name: str, provider_id: str, uri: str, capabilities: list, routes: list
) -> list[str]:
    tokens: set[str] = set()
    for blob in [name, provider_id, uri] + list(capabilities) + list(routes):
        for token in TOKEN_RE.findall(str(blob).lower()):
            if len(token) > 1:
                tokens.add(token)
    return sorted(tokens)


def flatten_routes(manifest: dict) -> list[str]:
    routes: list[str] = []
    for section in ("human", "agent"):
        part = manifest.get(section, {})
        if isinstance(part, dict):
            for value in part.values():
                if isinstance(value, str) and value:
                    routes.append(value)
    return routes


def overlay_id_for_provider(provider_id: str) -> str:
    return f"kolmaf-provider-{provider_id}"


def overlay_id_for_uri(uri: str) -> str:
    return "kolmaf-target-" + uri[len("kolmaf://"):].replace("/", "-").replace(".", "-")


def overlay_id_for(uri: str) -> str:
    if uri.startswith("kolmaf://provider/"):
        return overlay_id_for_provider(uri[len("kolmaf://provider/"):].split("/")[0])
    return overlay_id_for_uri(uri)


def build_aliases(
    providers: list[dict], corpus_nodes: list[dict], pointer_index: dict
) -> list[dict]:
    found: dict[tuple[str, str], dict] = {}
    for provider in providers:
        pid = str(provider.get("id"))
        for match in ALIAS_MATCH_STRINGS.get(pid, []):
            for node in corpus_nodes:
                blob = json.dumps(node, ensure_ascii=False).lower()
                if match.lower() in blob and node.get("pointer") in pointer_index:
                    key = (str(node["pointer"]), str(provider.get("uri")))
                    record = found.setdefault(
                        key,
                        {
                            "mem_pointer": node["pointer"],
                            "matrix_node_id": node["id"],
                            "kolmaf_uri": provider.get("uri"),
                            "basis": [],
                        },
                    )
                    mention = f"corpus node mentions {match!r}"
                    if mention not in record["basis"]:
                        record["basis"].append(mention)
    aliases = []
    for record in found.values():
        record["basis"] = "; ".join(sorted(record["basis"]))
        aliases.append(record)
    return sorted(aliases, key=lambda a: (str(a["mem_pointer"]), str(a["kolmaf_uri"])))


def build_overlay(
    registry: dict, manifests_by_id: dict, corpus_nodes: list[dict], pointer_index: dict
) -> tuple[dict | None, list[dict]]:
    errors: list[dict] = []
    registered = set(registry.get("identities", {})) | {
        p.get("uri") for p in registry.get("providers", []) if p.get("uri")
    }
    providers = sorted(registry.get("providers", []), key=lambda p: str(p.get("uri")))
    provider_nodes = []
    target_nodes = []
    for provider in providers:
        pid = provider.get("id")
        puri = provider.get("uri")
        manifest = manifests_by_id.get(pid)
        if manifest is None:
            errors.append(error("PROVIDER_MISSING", f"no manifest for provider: {pid}"))
            continue
        if provider.get("authority") not in AUTHORITY:
            errors.append(error("UNKNOWN_AUTHORITY", f"{pid}: unknown authority"))
        if provider.get("freshness") not in FRESHNESS:
            errors.append(error("UNKNOWN_FRESHNESS", f"{pid}: unknown freshness"))
        relationships = []
        for rel in provider.get("relationships", []) or []:
            if rel.get("type") not in RELATIONSHIPS:
                errors.append(
                    error(
                        "UNKNOWN_RELATIONSHIP",
                        f"{pid}: unknown relation type {rel.get('type')!r}; "
                        "contract extension refused",
                    )
                )
                continue
            if rel.get("target") not in registered:
                errors.append(error("UNKNOWN_URI", f"{pid}: target not registered"))
                continue
            relationships.append(
                {
                    "type": rel.get("type"),
                    "target": rel.get("target"),
                    "target_overlay_id": overlay_id_for(str(rel.get("target"))),
                }
            )
        routes = flatten_routes(manifest)
        provider_nodes.append(
            {
                "overlay_id": overlay_id_for_provider(str(pid)),
                "kind": "provider",
                "uri": puri,
                "title": manifest.get("name", pid),
                "provider": pid,
                "authority": provider.get("authority"),
                "freshness": provider.get("freshness"),
                "capabilities": sorted(provider.get("capabilities", []) or []),
                "human_route": manifest.get("human", {}),
                "agent_route": manifest.get("agent", {}),
                "relationships": sorted(
                    relationships, key=lambda r: (str(r["type"]), str(r["target"]))
                ),
                "target_status": {
                    "required_total": sum(
                        1 for t in provider.get("identities", []) if t.get("required")
                    ),
                    "required_exists": sum(
                        1
                        for t in provider.get("identities", [])
                        if t.get("required") and t.get("exists")
                    ),
                },
                "provenance": manifest.get("provenance", {}),
                "discovery_keywords": discovery_keywords(
                    str(manifest.get("name", pid)),
                    str(pid),
                    str(puri),
                    provider.get("capabilities", []) or [],
                    routes,
                ),
            }
        )
        for target in sorted(
            provider.get("identities", []), key=lambda t: str(t.get("uri"))
        ):
            turi = target.get("uri")
            if turi not in registered:
                errors.append(error("UNKNOWN_URI", f"{pid}: target uri not registered"))
                continue
            target_nodes.append(
                {
                    "overlay_id": overlay_id_for_uri(str(turi)),
                    "kind": "target",
                    "uri": turi,
                    "title": f"{manifest.get('name', pid)} — {turi}",
                    "provider": pid,
                    "authority": provider.get("authority"),
                    "freshness": provider.get("freshness"),
                    "target_status": {
                        "exists": bool(target.get("exists")),
                        "required": bool(target.get("required")),
                        "path": target.get("path"),
                    },
                    "provenance": manifest.get("provenance", {}),
                    "discovery_keywords": discovery_keywords(
                        str(manifest.get("name", pid)),
                        str(pid),
                        str(turi),
                        provider.get("capabilities", []) or [],
                        routes,
                    ),
                }
            )
    if errors:
        return None, errors
    aliases = build_aliases(providers, corpus_nodes, pointer_index)
    overlay = {
        "schema": OVERLAY_SCHEMA,
        "status": "active",
        "root": {
            "overlay_id": ROOT_ID,
            "title": ROOT_TITLE,
            "uri": None,
            "children": [n["overlay_id"] for n in provider_nodes],
        },
        "providers": provider_nodes,
        "identities": sorted(target_nodes, key=lambda n: str(n["uri"])),
        "aliases": aliases,
        "counts": {
            "providers": len(provider_nodes),
            "identities": len(target_nodes),
            "aliases": len(aliases),
        },
    }
    return overlay, []


def resolve_overlay(overlay: dict, uri: str) -> tuple[dict | None, dict | None]:
    if not isinstance(uri, str) or not URI_RE.match(uri):
        return None, error("INVALID_URI", f"malformed kolmaf:// uri: {uri!r}")
    for node in (overlay.get("providers", []) or []) + (overlay.get("identities", []) or []):
        if node.get("uri") == uri:
            return node, None
    return None, error("NOT_FOUND", f"unknown registered uri: {uri}")


def adapt_matrix_node(node: dict) -> dict:
    tags = node.get("tags", []) or []
    return {
        "kind": "matrix",
        "title": str(node.get("name", node.get("id"))),
        "text": " ".join(
            [
                str(node.get("name", "")),
                str(node.get("id", "")),
                " ".join(str(t) for t in tags),
                str(node.get("pointer", "")),
            ]
        ).lower(),
        "ref": str(node.get("pointer", "")),
    }


def adapt_overlay_node(node: dict) -> dict:
    routes: list[str] = []
    for section in ("human_route", "agent_route"):
        part = node.get(section, {})
        if isinstance(part, dict):
            routes.extend(str(v) for v in part.values() if isinstance(v, str))
    text = " ".join(
        [
            str(node.get("title", "")),
            str(node.get("uri", "")),
            " ".join(node.get("discovery_keywords", [])),
            " ".join(routes),
        ]
    ).lower()
    return {
        "kind": str(node.get("kind")),
        "title": str(node.get("title")),
        "text": text,
        "ref": str(node.get("uri")),
    }


def search_records(records: list[dict], query: str, limit: int | None = None) -> list[dict]:
    """Single shared discovery path: lowercase substring match, Matrix-style.

    Returns every match; display capping belongs to presentation (the Matrix
    UI caps at 500) so a provider is never silently cut from results.
    """
    needle = (query or "").lower()
    hits = [r for r in records if needle and needle in r["text"]]
    return hits if limit is None else hits[:limit]


def degraded_overlay(code: str, note: str) -> dict:
    return {
        "schema": OVERLAY_SCHEMA,
        "status": "degraded",
        "code": code,
        "note": note,
        "root": None,
        "providers": [],
        "identities": [],
        "aliases": [],
        "counts": {"providers": 0, "identities": 0, "aliases": 0},
    }


def load_manifests_by_id(manifests_dir: Path) -> dict:
    by_id = {}
    for path in sorted(manifests_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("id"):
            by_id[str(doc["id"])] = doc
    return by_id


def compile_all(
    matrix_home: Path | None,
    registry_path: Path,
    manifests_dir: Path,
    out_dir: Path,
) -> tuple[int, dict]:
    registry, load_error = load_registry(registry_path)
    if registry is None:
        code = load_error.get("code") if load_error else "INVALID_REGISTRY"
        if code == "REGISTRY_MISSING":
            out_dir.mkdir(parents=True, exist_ok=True)
            overlay = degraded_overlay(
                "REGISTRY_MISSING",
                "LinkBus registry unavailable; Matrix corpus untouched and fully usable. "
                + str(load_error.get("message") if load_error else ""),
            )
            write_json_deterministic(out_dir / "kolmaf-overlay.json", overlay)
            status = {
                "schema": "kolmaf-overlay-status/v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "ok": False,
                "code": "REGISTRY_MISSING",
                "counts": overlay["counts"],
            }
            write_json_deterministic(out_dir / "status.json", status)
            return 3, status
        return 1, {"ok": False, "errors": [load_error],
                   "counts": {"providers": 0, "identities": 0}}
    home = matrix_home or matrix_home_from_registry(registry)
    if home is None or not (home / "hyper-data.json").is_file():
        return 1, {
            "ok": False,
            "code": "MATRIX_UNREADABLE",
            "message": f"matrix corpus not found under {home}",
        }
    summary, summary_error = summarize_corpus(home)
    if summary is None:
        return 1, {
            "ok": False,
            "code": "MATRIX_UNREADABLE",
            "message": str(summary_error),
        }
    pointer_index = corpus_pointer_index(home)
    manifests_by_id = load_manifests_by_id(manifests_dir)
    overlay, build_errors = build_overlay(
        registry, manifests_by_id, load_corpus_nodes(home), pointer_index
    )
    if overlay is None:
        return 1, {
            "ok": False,
            "errors": build_errors,
            "counts": {"providers": 0, "identities": 0},
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json_deterministic(out_dir / "kolmaf-overlay.json", overlay)
    status = {
        "schema": "kolmaf-overlay-status/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "code": "ACTIVE",
        "matrix_baseline": {k: summary[k] for k in MATRIX_BASELINE},
        "counts": overlay["counts"],
        "errors": [],
    }
    write_json_deterministic(out_dir / "status.json", status)
    return 0, status


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve()
    default_root = here.parents[2]
    parser = argparse.ArgumentParser(description="Build kolmaf Matrix overlay (offline)")
    parser.add_argument("--project-root", default=str(default_root))
    parser.add_argument("--registry", default="data/runtime/linkbus/registry.json")
    parser.add_argument("--providers", default="integration/providers")
    parser.add_argument("--matrix-home", default="")
    parser.add_argument("--out", default="data/runtime/matrix")
    args = parser.parse_args(argv)
    root = Path(args.project_root)

    def resolve_arg(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    matrix_home = Path(args.matrix_home) if args.matrix_home else None
    code, result = compile_all(
        matrix_home, resolve_arg(args.registry), resolve_arg(args.providers),
        resolve_arg(args.out),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
