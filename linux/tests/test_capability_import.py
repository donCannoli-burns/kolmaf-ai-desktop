"""Portable capability-import contract tests.

Repository-contained synthetic fixtures only (tests/fixtures/capability_import).
No external corpus path, no machine-local path, no network. Validates the
importer contract: header/boolean/required-field shape, duplicates, checksums,
row provenance, SQLite transactional load, priority linkage, rollback, CSV
drift, advisory hashtable validation, and the read-only authority report.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from kolmafa import capability_import, cli

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "capability_import"
CAPABILITY_INDEX = FIXTURE_DIR / "kolmafia_capability_index.csv"
PRIORITY_FLAGS = FIXTURE_DIR / "kolmafia_priority_flags.csv"
CAPABILITY_HASHTABLE = FIXTURE_DIR / "kolmafia_capability.hashtable.json"
RESOURCE_HASHTABLE = FIXTURE_DIR / "agent_resource.hashtable.json"
HASHTABLE_PROVENANCE = FIXTURE_DIR / "HASHTABLE_PROVENANCE.json"

FIXTURE_CAPABILITY_ROWS = 4
FIXTURE_PRIORITY_ROWS = 2


def _write_csv(path: Path, rows: list[dict[str, str]], header: tuple[str, ...] | None = None) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=header or capability_import.EXPECTED_CAPABILITY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _valid_row(entry_id: str = "ash.fixture.noargs") -> dict[str, str]:
    row = {column: ("false" if column in _BOOLEAN_COLS else "") for column in capability_import.EXPECTED_CAPABILITY_COLUMNS}
    row.update(
        {
            "entry_id": entry_id,
            "name": "fixture",
            "entry_type": "ash_function",
            "language": "ASH",
            "signature_or_syntax": "int fixture()",
            "source_document": "fixture-doc.pdf",
            "source_location": "line 1",
            "evidence_status": "synthetic_fixture",
            "read_or_mutate": "read-only",
            "domains_touched": "local_computation",
            "candidate_risk": "read_only",
            "reads_game_state": "true",
            "native_or_runtime_surface": "ash_runtime",
        }
    )
    return row


_BOOLEAN_COLS = frozenset(capability_import.EXPECTED_CAPABILITY_COLUMNS) - frozenset(
    {
        "entry_id",
        "name",
        "entry_type",
        "language",
        "signature_or_syntax",
        "aliases",
        "source_document",
        "source_location",
        "evidence_status",
        "read_or_mutate",
        "domains_touched",
        "candidate_risk",
        "native_or_runtime_surface",
        "notes",
    }
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_validator_accepts_canonical_reference_fixture_and_reports_checksum() -> None:
    result = capability_import.validate_capability_csv_files([CAPABILITY_INDEX])

    assert result.ok
    assert result.row_count == FIXTURE_CAPABILITY_ROWS
    assert [artifact.row_count for artifact in result.artifacts] == [FIXTURE_CAPABILITY_ROWS]
    assert [artifact.column_count for artifact in result.artifacts] == [39]
    assert result.artifacts[0].sha256 == hashlib.sha256(CAPABILITY_INDEX.read_bytes()).hexdigest()
    assert result.rows[0].values["source_corpus"] == "kolmafia_capability_index.csv"
    assert result.rows[0].values["source_row_number"] == 2
    assert result.rows[0].values["source_content_hash"]


def test_validator_detects_duplicate_entry_id_within_artifact(tmp_path: Path) -> None:
    path = tmp_path / "kolmafia_capability_index.csv"
    row = _valid_row("ash.duplicate.noargs")
    _write_csv(path, [row, row.copy()])

    result = capability_import.validate_capability_csv_files([path])

    assert not result.ok
    assert result.rows == ()
    assert any("duplicate entry_id: ash.duplicate.noargs" in error.message for error in result.errors)


def test_validator_detects_duplicate_entry_id_across_artifacts(tmp_path: Path) -> None:
    capability_path = tmp_path / "capability" / "kolmafia_capability_index.csv"
    priority_path = tmp_path / "priority" / "kolmafia_priority_flags.csv"
    capability_path.parent.mkdir()
    priority_path.parent.mkdir()
    duplicate_entry_id = "ash.cross_artifact_duplicate.noargs"
    _write_csv(capability_path, [_valid_row(duplicate_entry_id)])
    _write_csv(priority_path, [_valid_row(duplicate_entry_id)])

    result = capability_import.validate_capability_csv_files([capability_path, priority_path])

    assert not result.ok
    assert result.rows == ()
    assert any(
        "duplicate entry_id across capability CSV artifacts: "
        "ash.cross_artifact_duplicate.noargs first seen in kolmafia_capability_index.csv row 2"
        in error.message
        for error in result.errors
    )


def test_validator_fails_closed_on_missing_extra_and_malformed_fields(tmp_path: Path) -> None:
    missing_path = tmp_path / "kolmafia_capability_index.csv"
    missing_header = capability_import.EXPECTED_CAPABILITY_COLUMNS[:-1]
    _write_csv(missing_path, [{key: value for key, value in _valid_row().items() if key != "notes"}], missing_header)

    result = capability_import.validate_capability_csv_files([missing_path])

    assert not result.ok
    assert any("header does not exactly match" in error.message for error in result.errors)

    short_row_path = tmp_path / "kolmafia_priority_flags.csv"
    row = _valid_row("ash.short.noargs")
    with short_row_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(capability_import.EXPECTED_CAPABILITY_COLUMNS)
        writer.writerow([row[column] for column in capability_import.EXPECTED_CAPABILITY_COLUMNS[:-1]])

    short_row = capability_import.validate_capability_csv_files([short_row_path])

    assert not short_row.ok
    assert any("missing field: notes" in error.message for error in short_row.errors)

    malformed_path = tmp_path / "kolmafia_priority_flags.csv"
    row = _valid_row("ash.malformed.noargs")
    row["reads_game_state"] = "yes"
    with malformed_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(capability_import.EXPECTED_CAPABILITY_COLUMNS)
        writer.writerow([row[column] for column in capability_import.EXPECTED_CAPABILITY_COLUMNS] + ["extra"])

    malformed = capability_import.validate_capability_csv_files([malformed_path])

    assert not malformed.ok
    messages = {error.message for error in malformed.errors}
    assert "CSV row has extra fields" in messages
    assert "malformed boolean field: reads_game_state" in messages


def test_validator_fails_closed_on_checksum_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "kolmafia_capability_index.csv"
    _write_csv(path, [_valid_row()])

    result = capability_import.validate_capability_csv_files(
        [path],
        expected_sha256={"kolmafia_capability_index.csv": "0" * 64},
    )

    assert not result.ok
    assert any("SHA256 does not match" in error.message for error in result.errors)


def test_cli_validate_capability_import_outputs_json_without_runtime_mutation(capsys) -> None:
    return_code = cli.main(["validate-capability-import", "--json", str(CAPABILITY_INDEX)])
    output = capsys.readouterr().out

    payload = json.loads(output)
    assert return_code == 0
    assert payload["ok"] is True
    assert payload["row_count"] == FIXTURE_CAPABILITY_ROWS
    assert payload["artifacts"][0]["sha256"] == hashlib.sha256(CAPABILITY_INDEX.read_bytes()).hexdigest()


def test_load_capability_authority_replaces_records_and_adds_priority_annotations(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"

    result = capability_import.load_capability_authority(database_path, CAPABILITY_INDEX, PRIORITY_FLAGS)

    assert result.ok
    assert result.capability_count == FIXTURE_CAPABILITY_ROWS
    assert result.annotation_count == FIXTURE_PRIORITY_ROWS
    with sqlite3.connect(database_path) as connection:
        capability_count = connection.execute("SELECT count(*) FROM capability_records").fetchone()[0]
        annotation_count = connection.execute("SELECT count(*) FROM capability_priority_annotations").fetchone()[0]
        annotated_missing = connection.execute(
            """
            SELECT count(*)
            FROM capability_priority_annotations AS annotations
            LEFT JOIN capability_records AS capabilities USING(entry_id)
            WHERE capabilities.entry_id IS NULL
            """
        ).fetchone()[0]

    assert capability_count == FIXTURE_CAPABILITY_ROWS
    assert annotation_count == FIXTURE_PRIORITY_ROWS
    assert annotated_missing == 0


def test_load_capability_authority_rolls_back_on_missing_priority_entry_id(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    first_result = capability_import.load_capability_authority(database_path, CAPABILITY_INDEX, PRIORITY_FLAGS)
    assert first_result.ok

    bad_priority = tmp_path / "kolmafia_priority_flags.csv"
    rows = [dict(row) for row in csv.DictReader(PRIORITY_FLAGS.read_text(encoding="utf-8").splitlines())]
    rows[0]["entry_id"] = "ash.priority_missing.noargs"
    _write_csv(bad_priority, rows)

    bad_result = capability_import.load_capability_authority(database_path, CAPABILITY_INDEX, bad_priority)

    assert not bad_result.ok
    assert any("priority entry_id has no capability authority row" in error.message for error in bad_result.errors)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM capability_records").fetchone()[0] == FIXTURE_CAPABILITY_ROWS
        assert connection.execute("SELECT count(*) FROM capability_priority_annotations").fetchone()[0] == FIXTURE_PRIORITY_ROWS


def test_load_capability_authority_rolls_back_on_sqlite_constraint_failure(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    first_result = capability_import.load_capability_authority(database_path, CAPABILITY_INDEX, PRIORITY_FLAGS)
    assert first_result.ok

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER abort_priority_annotations
            BEFORE INSERT ON capability_priority_annotations
            BEGIN
                SELECT RAISE(ABORT, 'fixture priority annotation constraint failure');
            END;
            """
        )

    bad_result = capability_import.load_capability_authority(database_path, CAPABILITY_INDEX, PRIORITY_FLAGS)

    assert not bad_result.ok
    assert any("rolled back" in error.message for error in bad_result.errors)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM capability_records").fetchone()[0] == FIXTURE_CAPABILITY_ROWS
        assert connection.execute("SELECT count(*) FROM capability_priority_annotations").fetchone()[0] == FIXTURE_PRIORITY_ROWS


def test_cli_load_capability_import_outputs_deterministic_json_and_text(tmp_path: Path, capsys) -> None:
    database_path = tmp_path / "authority.db"
    argv = [
        "load-capability-import",
        "--db",
        str(database_path),
        "--capability-csv",
        str(CAPABILITY_INDEX),
        "--priority-csv",
        str(PRIORITY_FLAGS),
        "--json",
    ]

    first_code = cli.main(argv)
    first_output = capsys.readouterr().out
    second_code = cli.main(argv)
    second_output = capsys.readouterr().out

    payload = json.loads(first_output)
    assert first_code == 0
    assert second_code == 0
    assert first_output == second_output
    assert payload["status"] == "ok"
    assert payload["counts"] == {
        "capability_records": FIXTURE_CAPABILITY_ROWS,
        "priority_annotations": FIXTURE_PRIORITY_ROWS,
    }
    assert payload["annotation_count"] == FIXTURE_PRIORITY_ROWS
    assert payload["offline"] is True
    assert payload["live_kol_mutation"] is False

    text_code = cli.main(argv[:-1])
    text_output = capsys.readouterr().out
    assert text_code == 0
    assert f"capability_records: {FIXTURE_CAPABILITY_ROWS}" in text_output
    assert f"priority_annotations: {FIXTURE_PRIORITY_ROWS}" in text_output
    assert "offline only" in text_output
    assert "does not contact KoLmafia or mutate live KoL state" in text_output


def test_load_capability_authority_fails_on_checksum_mismatch_without_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    result = capability_import.load_capability_authority(
        database_path,
        CAPABILITY_INDEX,
        PRIORITY_FLAGS,
        expected_sha256={"kolmafia_capability_index.csv": "0" * 64},
    )

    assert not result.ok
    assert any("SHA256 does not match" in error.message for error in result.errors)
    assert not database_path.exists()


def test_hashtable_checker_accepts_advisory_artifacts_and_provenance() -> None:
    result = capability_import.validate_hashtable_artifacts(
        [CAPABILITY_HASHTABLE, RESOURCE_HASHTABLE],
        HASHTABLE_PROVENANCE,
        canonical_capability_csv_path=CAPABILITY_INDEX,
    )

    assert result.ok
    assert [artifact.artifact_name for artifact in result.artifacts] == [
        "kolmafia_capability.hashtable.json",
        "agent_resource.hashtable.json",
    ]
    assert [artifact.size for artifact in result.artifacts] == [4, 2]
    assert [artifact.capacity for artifact in result.artifacts] == [16, 8]
    assert all(artifact.hash_marker == "fnv1a_64" for artifact in result.artifacts)
    assert result.artifacts[0].sha256 == hashlib.sha256(CAPABILITY_HASHTABLE.read_bytes()).hexdigest()
    assert result.artifacts[1].provenance_entries == 2


def test_hashtable_checker_detects_tampered_provenance_checksum(tmp_path: Path) -> None:
    provenance = json.loads(HASHTABLE_PROVENANCE.read_text(encoding="utf-8"))
    provenance["kolmafia_capability.hashtable.json"]["sha256"] = "0" * 64
    tampered_provenance = tmp_path / "HASHTABLE_PROVENANCE.json"
    _write_json(tampered_provenance, provenance)

    result = capability_import.validate_hashtable_artifacts(
        [CAPABILITY_HASHTABLE, RESOURCE_HASHTABLE],
        tampered_provenance,
        canonical_capability_csv_path=CAPABILITY_INDEX,
    )

    assert not result.ok
    assert any("SHA256 does not match provenance" in error.message for error in result.errors)


def test_hashtable_checker_detects_tampered_frozen_shape(tmp_path: Path) -> None:
    table = json.loads(CAPABILITY_HASHTABLE.read_text(encoding="utf-8"))
    table["slots"] = table["slots"][:-1]
    tampered_table = tmp_path / "kolmafia_capability.hashtable.json"
    _write_json(tampered_table, table)

    provenance = json.loads(HASHTABLE_PROVENANCE.read_text(encoding="utf-8"))
    provenance["kolmafia_capability.hashtable.json"]["sha256"] = hashlib.sha256(
        tampered_table.read_bytes()
    ).hexdigest()
    tampered_provenance = tmp_path / "HASHTABLE_PROVENANCE.json"
    _write_json(tampered_provenance, provenance)

    result = capability_import.validate_hashtable_artifacts(
        [tampered_table, RESOURCE_HASHTABLE],
        tampered_provenance,
        canonical_capability_csv_path=CAPABILITY_INDEX,
    )

    assert not result.ok
    assert any("slot count must equal capacity" in error.message for error in result.errors)


def test_hashtable_checker_detects_csv_to_capability_cache_drift(tmp_path: Path) -> None:
    table = json.loads(CAPABILITY_HASHTABLE.read_text(encoding="utf-8"))
    table["size"] = 3
    tampered_table = tmp_path / "kolmafia_capability.hashtable.json"
    _write_json(tampered_table, table)

    provenance = json.loads(HASHTABLE_PROVENANCE.read_text(encoding="utf-8"))
    provenance_record = provenance["kolmafia_capability.hashtable.json"]
    provenance_record["sha256"] = hashlib.sha256(tampered_table.read_bytes()).hexdigest()
    provenance_record["entries"] = 3
    provenance_record["stats"]["size"] = 3
    tampered_provenance = tmp_path / "HASHTABLE_PROVENANCE.json"
    _write_json(tampered_provenance, provenance)

    result = capability_import.validate_hashtable_artifacts(
        [tampered_table, RESOURCE_HASHTABLE],
        tampered_provenance,
        canonical_capability_csv_path=CAPABILITY_INDEX,
    )

    assert not result.ok
    assert any("CSV row count differs" in error.message for error in result.errors)


def test_hashtable_checker_detects_duplicate_slot_shape(tmp_path: Path) -> None:
    table = json.loads(CAPABILITY_HASHTABLE.read_text(encoding="utf-8"))
    occupied = [slot for slot in table["slots"] if slot is not None]
    table["slots"][0] = dict(occupied[0])
    tampered_table = tmp_path / "kolmafia_capability.hashtable.json"
    _write_json(tampered_table, table)

    provenance = json.loads(HASHTABLE_PROVENANCE.read_text(encoding="utf-8"))
    provenance["kolmafia_capability.hashtable.json"]["sha256"] = hashlib.sha256(
        tampered_table.read_bytes()
    ).hexdigest()
    tampered_provenance = tmp_path / "HASHTABLE_PROVENANCE.json"
    _write_json(tampered_provenance, provenance)

    result = capability_import.validate_hashtable_artifacts(
        [tampered_table, RESOURCE_HASHTABLE],
        tampered_provenance,
        canonical_capability_csv_path=CAPABILITY_INDEX,
    )

    assert not result.ok
    assert any("duplicate hashtable key" in error.message for error in result.errors)


def test_hashtable_checker_detects_tampered_psl(tmp_path: Path) -> None:
    table = json.loads(CAPABILITY_HASHTABLE.read_text(encoding="utf-8"))
    for slot in table["slots"]:
        if slot is not None:
            slot["psl"] = slot["psl"] + 1
    tampered_table = tmp_path / "kolmafia_capability.hashtable.json"
    _write_json(tampered_table, table)

    provenance = json.loads(HASHTABLE_PROVENANCE.read_text(encoding="utf-8"))
    provenance["kolmafia_capability.hashtable.json"]["sha256"] = hashlib.sha256(
        tampered_table.read_bytes()
    ).hexdigest()
    tampered_provenance = tmp_path / "HASHTABLE_PROVENANCE.json"
    _write_json(tampered_provenance, provenance)

    result = capability_import.validate_hashtable_artifacts(
        [tampered_table, RESOURCE_HASHTABLE],
        tampered_provenance,
        canonical_capability_csv_path=CAPABILITY_INDEX,
    )

    assert not result.ok
    assert any("PSL invariant failed" in error.message for error in result.errors)


def test_authority_report_requires_explicit_database_path() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(["authority-report", "--json"])

    assert exc_info.value.code == 2


def test_authority_report_json_is_deterministic_and_read_only(tmp_path: Path, capsys) -> None:
    database_path = tmp_path / "authority.db"
    load_result = capability_import.load_capability_authority(database_path, CAPABILITY_INDEX, PRIORITY_FLAGS)
    assert load_result.ok
    before_bytes = database_path.read_bytes()
    with sqlite3.connect(database_path) as connection:
        before_counts = {
            "capability_records": connection.execute("SELECT count(*) FROM capability_records").fetchone()[0],
            "agent_resource_records": connection.execute("SELECT count(*) FROM agent_resource_records").fetchone()[0],
            "capability_priority_annotations": connection.execute(
                "SELECT count(*) FROM capability_priority_annotations"
            ).fetchone()[0],
        }

    argv = [
        "authority-report",
        "--db",
        str(database_path),
        "--capability-csv",
        str(CAPABILITY_INDEX),
        "--priority-csv",
        str(PRIORITY_FLAGS),
        "--hashtable",
        str(CAPABILITY_HASHTABLE),
        "--hashtable",
        str(RESOURCE_HASHTABLE),
        "--provenance",
        str(HASHTABLE_PROVENANCE),
        "--json",
    ]

    first_code = cli.main(argv)
    first_output = capsys.readouterr().out
    second_code = cli.main(argv)
    second_output = capsys.readouterr().out

    payload = json.loads(first_output)
    assert first_code == 0
    assert second_code == 0
    assert first_output == second_output
    assert payload["counts"] == before_counts
    assert set(payload["authority_checksums"]) == {
        "capability_records",
        "agent_resource_records",
        "capability_priority_annotations",
    }
    assert payload["priority_annotation_summary"]["annotation_count"] == FIXTURE_PRIORITY_ROWS
    assert [item["status"] for item in payload["csv_drift"]] == ["match", "match"]
    assert payload["hashtable_validation"]["ok"] is True
    assert payload["offline"] is True
    assert payload["read_only"] is True
    assert payload["live_kol_mutation"] is False
    assert database_path.read_bytes() == before_bytes
    with sqlite3.connect(database_path) as connection:
        after_counts = {
            "capability_records": connection.execute("SELECT count(*) FROM capability_records").fetchone()[0],
            "agent_resource_records": connection.execute("SELECT count(*) FROM agent_resource_records").fetchone()[0],
            "capability_priority_annotations": connection.execute(
                "SELECT count(*) FROM capability_priority_annotations"
            ).fetchone()[0],
        }
    assert after_counts == before_counts


def test_authority_report_text_contains_equivalent_offline_read_only_summary(
    tmp_path: Path,
    capsys,
) -> None:
    database_path = tmp_path / "authority.db"
    assert capability_import.load_capability_authority(database_path, CAPABILITY_INDEX, PRIORITY_FLAGS).ok

    return_code = cli.main(
        [
            "authority-report",
            "--db",
            str(database_path),
            "--capability-csv",
            str(CAPABILITY_INDEX),
            "--priority-csv",
            str(PRIORITY_FLAGS),
        ]
    )
    output = capsys.readouterr().out

    assert return_code == 0
    assert f"capability_records: {FIXTURE_CAPABILITY_ROWS}" in output
    assert "agent_resource_records: 0" in output
    assert f"capability_priority_annotations: {FIXTURE_PRIORITY_ROWS}" in output
    assert "authority_checksum.capability_records:" in output
    assert f"priority_annotation_count: {FIXTURE_PRIORITY_ROWS}" in output
    assert "csv_drift: kolmafia_capability_index.csv status=match" in output
    assert "csv_drift: kolmafia_priority_flags.csv status=match" in output
    assert "offline/read-only" in output
    assert "performs no imports, writes, external calls, or live KoL mutation" in output


def test_authority_report_flags_csv_content_drift_without_mutation(tmp_path: Path, capsys) -> None:
    database_path = tmp_path / "authority.db"
    assert capability_import.load_capability_authority(database_path, CAPABILITY_INDEX, PRIORITY_FLAGS).ok
    before_bytes = database_path.read_bytes()
    drifted_capability = tmp_path / "kolmafia_capability_index.csv"
    rows = [dict(row) for row in csv.DictReader(CAPABILITY_INDEX.read_text(encoding="utf-8").splitlines())]
    rows[0]["candidate_risk"] = "mutating"
    _write_csv(drifted_capability, rows)

    return_code = cli.main(
        [
            "authority-report",
            "--db",
            str(database_path),
            "--capability-csv",
            str(drifted_capability),
            "--priority-csv",
            str(PRIORITY_FLAGS),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert return_code == 0
    assert payload["csv_drift"][0]["status"] == "drift"
    assert "content checksum drift" in payload["csv_drift"][0]["messages"]
    assert payload["csv_drift"][1]["status"] == "match"
    assert database_path.read_bytes() == before_bytes


def test_authority_report_flags_advisory_hashtable_provenance_mismatch(
    tmp_path: Path,
    capsys,
) -> None:
    database_path = tmp_path / "authority.db"
    assert capability_import.load_capability_authority(database_path, CAPABILITY_INDEX, PRIORITY_FLAGS).ok
    provenance = json.loads(HASHTABLE_PROVENANCE.read_text(encoding="utf-8"))
    provenance["agent_resource.hashtable.json"]["sha256"] = "0" * 64
    tampered_provenance = tmp_path / "HASHTABLE_PROVENANCE.json"
    _write_json(tampered_provenance, provenance)

    return_code = cli.main(
        [
            "authority-report",
            "--db",
            str(database_path),
            "--hashtable",
            str(CAPABILITY_HASHTABLE),
            "--hashtable",
            str(RESOURCE_HASHTABLE),
            "--provenance",
            str(tampered_provenance),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert return_code == 0
    assert payload["hashtable_validation"]["ok"] is False
    assert any(
        "SHA256 does not match provenance" in error["message"]
        for error in payload["hashtable_validation"]["errors"]
    )


def test_portable_test_file_has_no_external_corpus_dependency() -> None:
    # Needles are built from parts so this guard does not match its own
    # assertion literals; it targets the import-time path expression the
    # pre-portability test used to reach the external corpus.
    source = Path(__file__).resolve().read_text(encoding="utf-8")
    corpus_name = "KOL_" + "Master"
    assert f'parents[2] / "{corpus_name}"' not in source
    assert "sticky-" + "ricky" not in source
