"""Build deterministic work indexes (Slice 4).

Validates first; on any hygiene failure writes nothing and returns non-zero,
leaving previous outputs intact. On success, builds every projection in a
temporary directory and atomically replaces the outputs (build-then-replace).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from linkbus.validate import URI_RE

from .records import SOURCE_DIRS, load_all
from .validate import INDEX_MARKER, validate_all

INDEX_SCHEMA = "kolmaf-work-index/v1"


def registered_uris(registry_path: Path) -> tuple[set, dict | None]:
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return set(), {"code": "REGISTRY_MISSING", "message": f"registry unreadable: {exc}"}
    if (
        not isinstance(registry, dict)
        or registry.get("schema") != "kolmaf-registry/v1"
        or not isinstance(registry.get("providers"), list)
        or not isinstance(registry.get("identities"), dict)
    ):
        return set(), {"code": "INVALID_REGISTRY", "message": "not kolmaf-registry/v1"}
    uris = set(registry["identities"])
    uris.update(p["uri"] for p in registry["providers"] if p.get("uri"))
    bad = [u for u in uris if not URI_RE.match(u)]
    if bad:
        return set(), {"code": "INVALID_REGISTRY", "message": f"bad uris: {bad[:3]}"}
    return uris, None


def normalize(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if not k.startswith("_")}
    out["source"] = doc.get("_source", "")
    out["body"] = doc.get("_body", "")
    return out


def render_index(records: list[dict], project_root: Path) -> str:
    by_kind: dict[str, list[dict]] = {}
    for doc in records:
        by_kind.setdefault(str(doc.get("kind")), []).append(doc)
    for docs in by_kind.values():
        docs.sort(key=lambda d: str(d.get("id")))

    def line(doc: dict) -> str:
        source = str(doc.get("_source", ""))
        if source.startswith("docs/"):
            source = source[len("docs/"):]
        extra = ""
        if doc.get("kind") == "task":
            extra = f" — {doc.get('status')} — owner {doc.get('owner')}"
        elif doc.get("kind") == "escalation":
            extra = f" — {doc.get('status')} — {doc.get('class')}"
        else:
            extra = f" — {doc.get('status')}"
        return f"- [{doc.get('id')}]({source}) — {doc.get('title')}{extra}\n"

    tasks = by_kind.get("task", [])
    out = [INDEX_MARKER + "\n", "# Kolmaf-AI Work Index\n",
           "\nGenerated projection. Sources live under `docs/tasks|escalations|decisions|architecture/`.\n"]
    sections = [
        ("Active Tasks", [d for d in tasks if d.get("status") in ("QUEUED", "ACTIVE")]),
        ("Blocked Tasks", [d for d in tasks if d.get("status") == "BLOCKED"]),
        ("Verification Queue", [d for d in tasks if d.get("status") == "VERIFY"]),
        ("Open Escalations",
         [d for d in by_kind.get("escalation", []) if d.get("status") == "OPEN"]),
        ("Recent/Current Decisions", by_kind.get("decision", [])),
        ("Current Architecture",
         [d for d in by_kind.get("architecture", []) if d.get("status") == "CURRENT"]),
        ("Completed Tasks", [d for d in tasks if d.get("status") in ("DONE", "CANCELLED")]),
    ]
    for title, docs in sections:
        out.append(f"\n## {title}\n\n")
        out.append("_(none)_\n" if not docs else "".join(line(d) for d in docs))
    out.append("\n## Handoff\n\n- [docs/handoff.md](handoff.md) — chronological evidence\n")
    slices = sorted((project_root / "state").glob("slice-*.md"))
    out.append("\n## Migration Slice Records\n\n")
    out.append(
        "".join(f"- [{p.name}](../state/{p.name})\n" for p in slices) or "_(none)_\n"
    )
    return "".join(out)


def atomic_replace(tmp_path: Path, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_path, final_path)


def write_json_atomically(final_path: Path, obj: object) -> None:
    """Write tmp beside the target, then replace (same filesystem, atomic)."""
    data = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = final_path.parent / (final_path.name + ".tmp")
    tmp.write_bytes(data)
    atomic_replace(tmp, final_path)


def write_text_atomically(final_path: Path, text: str) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = final_path.parent / (final_path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    atomic_replace(tmp, final_path)


def compile_all(
    project_root: Path,
    registry_path: Path,
    out_dir: Path,
    index_path: Path,
) -> tuple[int, dict]:
    registered, reg_error = registered_uris(registry_path)
    if reg_error is not None:
        return 1, {"ok": False, "errors": [reg_error]}
    records, load_errors = load_all(project_root)
    errors = list(load_errors)
    errors.extend(validate_all(records, registered, project_root))
    if errors:
        return 1, {"ok": False, "errors": errors}
    normalized = [normalize(d) for d in records]
    by_kind = {}
    for doc in normalized:
        by_kind.setdefault(doc["kind"], []).append(doc)
    counts = {
        "records": len(normalized),
        "by_kind": {k: len(v) for k, v in sorted(by_kind.items())},
        "tasks_by_status": {},
        "escalations_by_status": {},
    }
    for doc in by_kind.get("task", []):
        counts["tasks_by_status"][doc["status"]] = counts["tasks_by_status"].get(doc["status"], 0) + 1
    for doc in by_kind.get("escalation", []):
        counts["escalations_by_status"][doc["status"]] = (
            counts["escalations_by_status"].get(doc["status"], 0) + 1
        )
    payloads = {
        "records.json": {
            "schema": INDEX_SCHEMA,
            "records": sorted(normalized, key=lambda d: (d["kind"], d["id"])),
        },
        "tasks.json": {"schema": INDEX_SCHEMA, "records": by_kind.get("task", [])},
        "escalations.json": {"schema": INDEX_SCHEMA, "records": by_kind.get("escalation", [])},
        "decisions.json": {"schema": INDEX_SCHEMA, "records": by_kind.get("decision", [])},
        "architecture.json": {"schema": INDEX_SCHEMA, "records": by_kind.get("architecture", [])},
    }
    with_timestamps = {
        "schema": "kolmaf-work-status/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "counts": counts,
        "errors": [],
    }
    # Validation passed above, so no partial-output risk from here on.
    for name, obj in payloads.items():
        write_json_atomically(out_dir / name, obj)
    write_json_atomically(out_dir / "status.json", with_timestamps)
    write_text_atomically(index_path, render_index(records, project_root))
    return 0, {"ok": True, "counts": counts, "errors": []}


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve()
    default_root = here.parents[2]
    parser = argparse.ArgumentParser(description="Build kolmaf work index (offline)")
    parser.add_argument("--project-root", default=str(default_root))
    parser.add_argument("--registry", default="data/runtime/linkbus/registry.json")
    parser.add_argument("--out", default="data/runtime/work")
    parser.add_argument("--index", default="docs/INDEX.md")
    args = parser.parse_args(argv)
    root = Path(args.project_root)

    def resolve_arg(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    code, result = compile_all(
        root, resolve_arg(args.registry), resolve_arg(args.out),
        resolve_arg(args.index),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
