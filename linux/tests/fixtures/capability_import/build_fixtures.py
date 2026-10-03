"""Deterministic builder for the synthetic capability-import fixtures.

Generates, from hand-authored inputs only:

- kolmafia_capability_index.csv  (4 capability rows, production 39-column shape)
- kolmafia_priority_flags.csv    (2 priority rows referencing a subset of them)
- kolmafia_capability.hashtable.json  (capacity 16, size 4, hash fnv1a_64)
- agent_resource.hashtable.json       (capacity 8, size 2, hash fnv1a_64)
- HASHTABLE_PROVENANCE.json           (sha256/entries/source/stats per artifact)

The capability table deliberately includes a PSL=1 probe: entry ids
`ash.fixture.local_computation.noargs` and `ash.fixture.recursive_candidate.string`
share a home slot mod 16, so the second is placed at psl 1. This exercises the
production validator's PSL invariant without monkeypatching anything.

No live KOL_Master corpus is read or copied. Regenerate with:

    python3.13 tests/fixtures/capability_import/build_fixtures.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from kolmafa.capability_import import EXPECTED_CAPABILITY_COLUMNS, _fnv1a_64  # noqa: E402


BOOLEAN_COLUMNS: tuple[str, ...] = (
    "argument_dependent",
    "reads_game_state",
    "mutates_game_state",
    "reads_preferences",
    "writes_preferences",
    "reads_files",
    "writes_files",
    "contacts_network",
    "spends_turns",
    "spends_meat",
    "spends_items",
    "changes_inventory",
    "changes_equipment",
    "changes_choice_state",
    "social_or_kmail_output",
    "authentication_effect",
    "process_or_ui_effect",
    "nested_cli_execution",
    "nested_ash_execution",
    "script_execution",
    "deferred_execution",
    "hook_or_lifecycle_surface",
    "relay_or_url_surface",
    "recursive_classification_required",
    "fail_closed_if_unresolved",
)


def _capability_row(
    *,
    entry_id: str,
    name: str,
    signature: str,
    domains_touched: str,
    read_or_mutate: str,
    candidate_risk: str,
    reads_game_state: str = "false",
    mutates_game_state: str = "false",
    spends_turns: str = "false",
    recursive: str = "false",
    fail_closed: str = "false",
    notes: str = "",
    aliases: str = "",
    **extra: str,
) -> dict[str, str]:
    row = {column: ("false" if column in BOOLEAN_COLUMNS else "") for column in EXPECTED_CAPABILITY_COLUMNS}
    row.update(
        {
            "entry_id": entry_id,
            "name": name,
            "entry_type": "ash_function",
            "language": "ASH",
            "signature_or_syntax": signature,
            "aliases": aliases,
            "source_document": "fixture-doc.pdf",
            "source_location": "line 1",
            "evidence_status": "synthetic_fixture",
            "read_or_mutate": read_or_mutate,
            "domains_touched": domains_touched,
            "candidate_risk": candidate_risk,
            "reads_game_state": reads_game_state,
            "mutates_game_state": mutates_game_state,
            "spends_turns": spends_turns,
            "recursive_classification_required": recursive,
            "fail_closed_if_unresolved": fail_closed,
            "native_or_runtime_surface": "ash_runtime",
            "notes": notes,
        }
    )
    for key, value in extra.items():
        if key not in EXPECTED_CAPABILITY_COLUMNS:
            raise KeyError(key)
        row[key] = value
    return row


CAPABILITY_ROWS: list[dict[str, str]] = [
    _capability_row(
        entry_id="ash.fixture.local_computation.noargs",
        name="fixture local computation",
        signature="int fixture_local_computation()",
        domains_touched="local_computation",
        read_or_mutate="read-only",
        candidate_risk="read_only",
        notes="read-only local computation candidate",
    ),
    _capability_row(
        entry_id="ash.fixture.game_state_probe.noargs",
        name="fixture game state probe",
        signature="int fixture_game_state_probe()",
        domains_touched="game_state_observation",
        read_or_mutate="read-only",
        candidate_risk="read_only",
        reads_game_state="true",
        aliases="fixture_probe",
        notes="read-only game-state observation",
    ),
    _capability_row(
        entry_id="ash.fixture.mutating_candidate.string",
        name="fixture mutating candidate",
        signature="void fixture_mutating_candidate(string label)",
        domains_touched="gameplay_mutation",
        read_or_mutate="mutating",
        candidate_risk="mutating_confirmation",
        reads_game_state="true",
        mutates_game_state="true",
        spends_turns="true",
        notes="mutating candidate requiring confirmation",
    ),
    _capability_row(
        entry_id="ash.fixture.recursive_candidate.string",
        name="fixture recursive candidate",
        signature="int fixture_recursive_candidate(string label)",
        domains_touched="nested_execution",
        read_or_mutate="read-only",
        candidate_risk="unresolved",
        reads_game_state="false",
        nested_ash_execution="true",
        recursive="true",
        fail_closed="true",
        notes="recursive classification required, fail closed",
    ),
]

PRIORITY_ROWS: list[dict[str, str]] = [
    _capability_row(
        entry_id="ash.fixture.local_computation.noargs",
        name="fixture local computation",
        signature="int fixture_local_computation()",
        domains_touched="local_computation",
        read_or_mutate="read-only",
        candidate_risk="read_only",
        notes="priority subset row",
    ),
    _capability_row(
        entry_id="ash.fixture.recursive_candidate.string",
        name="fixture recursive candidate",
        signature="int fixture_recursive_candidate(string label)",
        domains_touched="nested_execution",
        read_or_mutate="read-only",
        candidate_risk="unresolved",
        recursive="true",
        fail_closed="true",
        nested_ash_execution="true",
        notes="priority subset row",
    ),
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPECTED_CAPABILITY_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8", newline="")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_table(keys: list[str], values: list[dict], capacity: int) -> dict:
    slots: list[dict | None] = [None] * capacity
    for key, value in zip(keys, values):
        home = _fnv1a_64(key) % capacity
        index = home
        psl = 0
        while slots[index] is not None:
            index = (index + 1) % capacity
            psl += 1
        slots[index] = {"key": key, "value": value, "psl": psl}
    return {"capacity": capacity, "size": len(keys), "hash": "fnv1a_64", "slots": slots}


def _stats(table: dict) -> dict:
    psls = [slot["psl"] for slot in table["slots"] if slot is not None]
    capacity = table["capacity"]
    size = table["size"]
    return {
        "capacity": capacity,
        "size": size,
        "load_factor": round(size / capacity, 4),
        "max_psl": max(psls),
        "avg_psl": round(sum(psls) / len(psls), 4),
        "empty_slots": capacity - size,
    }


def _provenance_record(path: Path, table: dict, source: str) -> dict:
    stats = _stats(table)
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "entries": stats["size"],
        "source": source,
        "stats": stats,
    }


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    capability_csv = FIXTURE_DIR / "kolmafia_capability_index.csv"
    priority_csv = FIXTURE_DIR / "kolmafia_priority_flags.csv"
    capability_table_path = FIXTURE_DIR / "kolmafia_capability.hashtable.json"
    resource_table_path = FIXTURE_DIR / "agent_resource.hashtable.json"
    provenance_path = FIXTURE_DIR / "HASHTABLE_PROVENANCE.json"

    _write_csv(capability_csv, CAPABILITY_ROWS)
    _write_csv(priority_csv, PRIORITY_ROWS)

    capability_keys = [row["entry_id"] for row in CAPABILITY_ROWS]
    capability_values = [
        {"entry_id": row["entry_id"], "name": row["name"], "candidate_risk": row["candidate_risk"]}
        for row in CAPABILITY_ROWS
    ]
    capability_table = _build_table(capability_keys, capability_values, capacity=16)
    capability_table_path.write_text(
        json.dumps(capability_table, indent=2) + "\n", encoding="utf-8"
    )

    resource_keys = ["fixture.resource.alpha", "fixture.resource.beta"]
    resource_values = [
        {"category": "Fixture Resources", "resource_count": 3, "source_doc": "fixture"},
        {"category": "Fixture Resources", "resource_count": 5, "source_doc": "fixture"},
    ]
    resource_table = _build_table(resource_keys, resource_values, capacity=8)
    resource_table_path.write_text(
        json.dumps(resource_table, indent=2) + "\n", encoding="utf-8"
    )

    provenance = {
        "kolmafia_capability.hashtable.json": _provenance_record(
            capability_table_path, capability_table, "fixture/kolmafia_capability_index.csv"
        ),
        "agent_resource.hashtable.json": _provenance_record(
            resource_table_path, resource_table, "fixture/kol_agent_index.json"
        ),
    }
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")

    print("wrote fixtures to", FIXTURE_DIR)
    print("capability table: size", capability_table["size"], "capacity", capability_table["capacity"])
    print("resource table: size", resource_table["size"], "capacity", resource_table["capacity"])


if __name__ == "__main__":
    main()
