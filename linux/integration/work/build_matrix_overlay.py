"""Project the work index into the Matrix discovery plane (Slice 4).

Separate deterministic projection beside the Slice-3 provider overlay
(`kolmaf-overlay.json` is never touched here). Work records keep stable
record identities (TASK-/ESC-/ADR-/arch IDs, uri None) and carry registered
kolmaf:// references in `related`. No new kolmaf identities are minted, so
the Slice-2 seven-provider contract stays strict.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .build_index import registered_uris, write_json_atomically
from .records import load_all
from .validate import validate_all

WORK_OVERLAY_SCHEMA = "kolmaf-work-overlay/v1"

GROUPS = (
    ("kolmaf-work-tasks", "Tasks", "task"),
    ("kolmaf-work-escalations", "Escalations", "escalation"),
    ("kolmaf-work-decisions", "Decisions", "decision"),
    ("kolmaf-work-architecture", "Architecture", "architecture"),
)

TOKEN_RE = re.compile(r"[a-z0-9]+")


def discovery_keywords(doc: dict) -> list[str]:
    tokens: set[str] = set()
    blobs = [
        str(doc.get("id", "")),
        str(doc.get("title", "")),
        str(doc.get("kind", "")),
        str(doc.get("status", "")),
        str(doc.get("owner", "")),
        str(doc.get("class", "")),
    ]
    blobs.extend(str(r) for r in doc.get("related", []) or [])
    for blob in blobs:
        for token in TOKEN_RE.findall(blob.lower()):
            if len(token) > 1:
                tokens.add(token)
    return sorted(tokens)


def adapt_work_record(doc: dict) -> dict:
    text = " ".join(
        [
            str(doc.get("title", "")),
            str(doc.get("id", "")),
            str(doc.get("kind", "")),
            str(doc.get("status", "")),
            str(doc.get("owner", "")),
            str(doc.get("class", "")),
            " ".join(str(r) for r in doc.get("related", []) or []),
            str(doc.get("_body", "")),
        ]
    ).lower()
    return {
        "kind": str(doc.get("kind")),
        "title": str(doc.get("title")),
        "text": text,
        "ref": str(doc.get("id")),
        "plane": "kolmaf-work-overlay",
    }


def build_work_overlay(records: list[dict]) -> dict:
    ordered = sorted(records, key=lambda d: (str(d.get("kind")), str(d.get("id"))))
    groups = []
    projected = []
    for overlay_id, title, kind in GROUPS:
        members = [d for d in ordered if d.get("kind") == kind]
        children = []
        for doc in members:
            rid = str(doc.get("id"))
            record_id = f"work-{rid}"
            children.append(record_id)
            related = [r for r in doc.get("related", []) or [] if isinstance(r, str)]
            projected.append(
                {
                    "overlay_id": record_id,
                    "kind": kind,
                    "record_id": rid,
                    "uri": None,
                    "title": doc.get("title"),
                    "status": doc.get("status"),
                    "owner": doc.get("owner"),
                    "next_actor": doc.get("next_actor"),
                    "related": sorted(related),
                    "plane": "kolmaf-work-overlay",
                    "source": doc.get("_source", ""),
                    "discovery_keywords": discovery_keywords(doc),
                }
            )
        groups.append(
            {"overlay_id": overlay_id, "title": title, "kind": kind, "children": children}
        )
    projected.sort(key=lambda r: (r["kind"], r["record_id"]))
    return {
        "schema": WORK_OVERLAY_SCHEMA,
        "status": "active",
        "root": {
            "overlay_id": "kolmaf-work",
            "title": "Work",
            "uri": None,
            "children": [g["overlay_id"] for g in groups],
        },
        "groups": groups,
        "records": projected,
        "counts": {
            "records": len(projected),
            "by_kind": {g["kind"]: len(g["children"]) for g in groups},
        },
    }


def compile_all(
    project_root: Path,
    registry_path: Path,
    out_path: Path,
    status_path: Path,
) -> tuple[int, dict]:
    registered, reg_error = registered_uris(registry_path)
    if reg_error is not None:
        return 1, {"ok": False, "errors": [reg_error]}
    records, load_errors = load_all(project_root)
    errors = list(load_errors)
    errors.extend(validate_all(records, registered, project_root))
    if errors:
        return 1, {"ok": False, "errors": errors}
    overlay = build_work_overlay(records)
    status = {
        "schema": "kolmaf-work-overlay-status/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "counts": overlay["counts"],
        "errors": [],
    }
    # Validation passed above, so no partial-output risk from here on.
    write_json_atomically(out_path, overlay)
    write_json_atomically(status_path, status)
    return 0, {"ok": True, "counts": overlay["counts"], "errors": []}


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve()
    default_root = here.parents[2]
    parser = argparse.ArgumentParser(description="Build kolmaf work overlay (offline)")
    parser.add_argument("--project-root", default=str(default_root))
    parser.add_argument("--registry", default="data/runtime/linkbus/registry.json")
    parser.add_argument("--out", default="data/runtime/matrix/kolmaf-work-overlay.json")
    parser.add_argument("--status", default="data/runtime/matrix/work-overlay-status.json")
    args = parser.parse_args(argv)
    root = Path(args.project_root)

    def resolve_arg(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    code, result = compile_all(
        root, resolve_arg(args.registry), resolve_arg(args.out),
        resolve_arg(args.status),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
