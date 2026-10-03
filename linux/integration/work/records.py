"""Parse kolmaf-work-record/v1 Markdown records (Slice 4).

TOML +++ front matter via stdlib tomllib — no new dependency. Read-only.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

RECORD_KINDS = ("task", "escalation", "decision", "architecture")

SOURCE_DIRS = {
    "task": "docs/tasks",
    "escalation": "docs/escalations",
    "decision": "docs/decisions",
    "architecture": "docs/architecture",
}

SCHEMA = "kolmaf-work-record/v1"


def parse_record(path: Path, project_root: Path) -> tuple[dict | None, dict | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, {"code": "UNREADABLE", "message": f"{path}: {exc}"}
    lines = text.splitlines()
    if len(lines) < 2 or lines[0].strip() != "+++":
        return None, {"code": "MALFORMED_RECORD", "message": f"{path}: missing +++ front matter"}
    try:
        end = lines.index("+++", 1)
    except ValueError:
        return None, {"code": "MALFORMED_RECORD", "message": f"{path}: unclosed +++ front matter"}
    try:
        front = tomllib.loads("\n".join(lines[1:end]))
    except tomllib.TOMLDecodeError as exc:
        return None, {"code": "MALFORMED_RECORD", "message": f"{path}: bad TOML: {exc}"}
    if not isinstance(front, dict):
        return None, {"code": "MALFORMED_RECORD", "message": f"{path}: front matter not a table"}
    body = "\n".join(lines[end + 1:]).strip()
    doc = dict(front)
    doc["_source"] = str(path.relative_to(project_root))
    doc["_body"] = body
    return doc, None


def load_all(project_root: Path) -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    errors: list[dict] = []
    for kind, subdir in SOURCE_DIRS.items():
        directory = project_root / subdir
        if not directory.is_dir():
            errors.append({"code": "RECORDS_DIR_MISSING", "message": f"absent: {subdir}"})
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name == "README.md":
                continue
            doc, err = parse_record(path, project_root)
            if err is not None:
                err["source"] = str(path.relative_to(project_root))
                errors.append(err)
            else:
                doc["_dir_kind"] = kind
                records.append(doc)
    records.sort(key=lambda d: (str(d.get("kind", "")), str(d.get("id", ""))))
    return records, errors
