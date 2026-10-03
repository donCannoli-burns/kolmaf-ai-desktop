"""External integration: real KOL_Master capability corpus.

Asserts properties of the real sibling-workspace corpus (capability index,
priority flags, frozen hashtables, provenance). Deselected from the portable
CI gate by the `external_integration` marker. When the corpus is absent it
skips with a precise, narrowly-scoped reason; it never borrows, copies, or
vendors external content into this repository.

Corpus-specific facts asserted here (997 capability rows, 386 priority
annotations, 997/2048 capability hashtable, 34/64 agent-resource hashtable)
are properties of the external corpus, not of the importer contract, and
are therefore not reproduced by the portable fixtures.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from kolmafa import capability_import, cli

_CORPUS_CANDIDATES = (
    Path(__file__).parents[2] / "KOL_Master",
    Path(__file__).parents[2] / "kolmaf-AI" / "KOL_Master",
    Path(__file__).parents[2] / "donCannoli-dev-kolmaf-ai" / "KOL_Master",
)

pytestmark = pytest.mark.external_integration

REAL_CAPABILITY_ROWS = 997
REAL_PRIORITY_ROWS = 386
REAL_CAPABILITY_HASHTABLE_SIZE = 997
REAL_CAPABILITY_HASHTABLE_CAPACITY = 2048
REAL_RESOURCE_HASHTABLE_SIZE = 34
REAL_RESOURCE_HASHTABLE_CAPACITY = 64


def _corpus_root() -> Path | None:
    for candidate in _CORPUS_CANDIDATES:
        if (candidate / "reference" / "kolmafia_capability_index.csv").is_file():
            return candidate
    return None


@pytest.fixture(scope="module")
def corpus() -> dict[str, Path]:
    root = _corpus_root()
    if root is None:
        pytest.skip(f"real KOL_Master capability corpus absent at {_CORPUS_CANDIDATES[0]}")
    reference = root / "reference"
    hashtable = root / "graph" / "hashtable"
    return {
        "capability_index": reference / "kolmafia_capability_index.csv",
        "priority_flags": reference / "kolmafia_priority_flags.csv",
        "capability_hashtable": hashtable / "kolmafia_capability.hashtable.json",
        "resource_hashtable": hashtable / "agent_resource.hashtable.json",
        "provenance": hashtable / "HASHTABLE_PROVENANCE.json",
    }


@pytest.fixture(scope="module")
def loaded_authority(tmp_path_factory, corpus) -> Path:
    database_path = tmp_path_factory.mktemp("external_authority") / "authority.db"
    result = capability_import.load_capability_authority(
        database_path,
        corpus["capability_index"],
        corpus["priority_flags"],
    )
    assert result.ok
    return database_path


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=capability_import.EXPECTED_CAPABILITY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_real_validator_accepts_canonical_corpus_and_reports_checksum(corpus) -> None:
    result = capability_import.validate_capability_csv_files([corpus["capability_index"]])

    assert result.ok
    assert result.row_count == REAL_CAPABILITY_ROWS
    assert [artifact.row_count for artifact in result.artifacts] == [REAL_CAPABILITY_ROWS]
    assert [artifact.column_count for artifact in result.artifacts] == [39]
    assert result.artifacts[0].sha256 == hashlib.sha256(corpus["capability_index"].read_bytes()).hexdigest()
    assert result.rows[0].values["source_corpus"] == "kolmafia_capability_index.csv"
    assert result.rows[0].values["source_row_number"] == 2
    assert result.rows[0].values["source_content_hash"]


def test_real_cli_validate_outputs_json_without_runtime_mutation(corpus, capsys) -> None:
    return_code = cli.main(["validate-capability-import", "--json", str(corpus["capability_index"])])
    output = capsys.readouterr().out

    payload = json.loads(output)
    assert return_code == 0
    assert payload["ok"] is True
    assert payload["row_count"] == REAL_CAPABILITY_ROWS
    assert payload["artifacts"][0]["sha256"] == hashlib.sha256(
        corpus["capability_index"].read_bytes()
    ).hexdigest()


def test_real_load_replaces_records_and_adds_priority_annotations(loaded_authority) -> None:
    with sqlite3.connect(loaded_authority) as connection:
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

    assert capability_count == REAL_CAPABILITY_ROWS
    assert annotation_count == REAL_PRIORITY_ROWS
    assert annotated_missing == 0


def test_real_load_rolls_back_on_missing_priority_entry_id(loaded_authority, corpus, tmp_path: Path) -> None:
    bad_priority = tmp_path / "kolmafia_priority_flags.csv"
    rows = [
        dict(row)
        for row in csv.DictReader(corpus["priority_flags"].read_text(encoding="utf-8").splitlines())
    ]
    rows[0]["entry_id"] = "ash.priority_missing.noargs"
    _write_csv(bad_priority, rows)

    bad_result = capability_import.load_capability_authority(
        loaded_authority, corpus["capability_index"], bad_priority
    )

    assert not bad_result.ok
    assert any("priority entry_id has no capability authority row" in error.message for error in bad_result.errors)
    with sqlite3.connect(loaded_authority) as connection:
        assert connection.execute("SELECT count(*) FROM capability_records").fetchone()[0] == REAL_CAPABILITY_ROWS
        assert (
            connection.execute("SELECT count(*) FROM capability_priority_annotations").fetchone()[0]
            == REAL_PRIORITY_ROWS
        )


def test_real_load_rolls_back_on_sqlite_constraint_failure(loaded_authority, corpus) -> None:
    with sqlite3.connect(loaded_authority) as connection:
        connection.execute(
            """
            CREATE TRIGGER abort_priority_annotations
            BEFORE INSERT ON capability_priority_annotations
            BEGIN
                SELECT RAISE(ABORT, 'real corpus priority annotation constraint failure');
            END;
            """
        )

    bad_result = capability_import.load_capability_authority(
        loaded_authority, corpus["capability_index"], corpus["priority_flags"]
    )

    assert not bad_result.ok
    assert any("rolled back" in error.message for error in bad_result.errors)
    with sqlite3.connect(loaded_authority) as connection:
        assert connection.execute("SELECT count(*) FROM capability_records").fetchone()[0] == REAL_CAPABILITY_ROWS
        assert (
            connection.execute("SELECT count(*) FROM capability_priority_annotations").fetchone()[0]
            == REAL_PRIORITY_ROWS
        )


def test_real_cli_load_outputs_deterministic_json_and_text(corpus, tmp_path: Path, capsys) -> None:
    database_path = tmp_path / "authority.db"
    argv = [
        "load-capability-import",
        "--db",
        str(database_path),
        "--capability-csv",
        str(corpus["capability_index"]),
        "--priority-csv",
        str(corpus["priority_flags"]),
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
        "capability_records": REAL_CAPABILITY_ROWS,
        "priority_annotations": REAL_PRIORITY_ROWS,
    }
    assert payload["annotation_count"] == REAL_PRIORITY_ROWS
    assert payload["offline"] is True
    assert payload["live_kol_mutation"] is False

    text_code = cli.main(argv[:-1])
    text_output = capsys.readouterr().out
    assert text_code == 0
    assert f"capability_records: {REAL_CAPABILITY_ROWS}" in text_output
    assert f"priority_annotations: {REAL_PRIORITY_ROWS}" in text_output
    assert "offline only" in text_output
    assert "does not contact KoLmafia or mutate live KoL state" in text_output


def test_real_load_fails_on_checksum_mismatch_without_mutation(corpus, tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    result = capability_import.load_capability_authority(
        database_path,
        corpus["capability_index"],
        corpus["priority_flags"],
        expected_sha256={"kolmafia_capability_index.csv": "0" * 64},
    )

    assert not result.ok
    assert any("SHA256 does not match" in error.message for error in result.errors)
    assert not database_path.exists()


def test_real_hashtable_checker_accepts_advisory_artifacts_and_provenance(corpus) -> None:
    result = capability_import.validate_hashtable_artifacts(
        [corpus["capability_hashtable"], corpus["resource_hashtable"]],
        corpus["provenance"],
        canonical_capability_csv_path=corpus["capability_index"],
    )

    assert result.ok
    assert [artifact.artifact_name for artifact in result.artifacts] == [
        "kolmafia_capability.hashtable.json",
        "agent_resource.hashtable.json",
    ]
    assert [artifact.size for artifact in result.artifacts] == [
        REAL_CAPABILITY_HASHTABLE_SIZE,
        REAL_RESOURCE_HASHTABLE_SIZE,
    ]
    assert [artifact.capacity for artifact in result.artifacts] == [
        REAL_CAPABILITY_HASHTABLE_CAPACITY,
        REAL_RESOURCE_HASHTABLE_CAPACITY,
    ]
    assert all(artifact.hash_marker == "fnv1a_64" for artifact in result.artifacts)
    assert result.artifacts[0].sha256 == hashlib.sha256(
        corpus["capability_hashtable"].read_bytes()
    ).hexdigest()
    assert result.artifacts[1].provenance_entries == REAL_RESOURCE_HASHTABLE_SIZE


def test_real_hashtable_checker_detects_tampered_provenance_checksum(corpus, tmp_path: Path) -> None:
    provenance = json.loads(corpus["provenance"].read_text(encoding="utf-8"))
    provenance["kolmafia_capability.hashtable.json"]["sha256"] = "0" * 64
    tampered_provenance = tmp_path / "HASHTABLE_PROVENANCE.json"
    _write_json(tampered_provenance, provenance)

    result = capability_import.validate_hashtable_artifacts(
        [corpus["capability_hashtable"], corpus["resource_hashtable"]],
        tampered_provenance,
        canonical_capability_csv_path=corpus["capability_index"],
    )

    assert not result.ok
    assert any("SHA256 does not match provenance" in error.message for error in result.errors)


def test_real_hashtable_checker_detects_tampered_frozen_shape(corpus, tmp_path: Path) -> None:
    table = json.loads(corpus["capability_hashtable"].read_text(encoding="utf-8"))
    table["slots"] = table["slots"][:-1]
    tampered_table = tmp_path / "kolmafia_capability.hashtable.json"
    _write_json(tampered_table, table)

    provenance = json.loads(corpus["provenance"].read_text(encoding="utf-8"))
    provenance["kolmafia_capability.hashtable.json"]["sha256"] = hashlib.sha256(
        tampered_table.read_bytes()
    ).hexdigest()
    tampered_provenance = tmp_path / "HASHTABLE_PROVENANCE.json"
    _write_json(tampered_provenance, provenance)

    result = capability_import.validate_hashtable_artifacts(
        [tampered_table, corpus["resource_hashtable"]],
        tampered_provenance,
        canonical_capability_csv_path=corpus["capability_index"],
    )

    assert not result.ok
    assert any("slot count must equal capacity" in error.message for error in result.errors)


def test_real_hashtable_checker_detects_csv_to_capability_cache_drift(corpus, tmp_path: Path) -> None:
    table = json.loads(corpus["capability_hashtable"].read_text(encoding="utf-8"))
    table["size"] = REAL_CAPABILITY_HASHTABLE_SIZE - 1
    tampered_table = tmp_path / "kolmafia_capability.hashtable.json"
    _write_json(tampered_table, table)

    provenance = json.loads(corpus["provenance"].read_text(encoding="utf-8"))
    provenance_record = provenance["kolmafia_capability.hashtable.json"]
    provenance_record["sha256"] = hashlib.sha256(tampered_table.read_bytes()).hexdigest()
    provenance_record["entries"] = REAL_CAPABILITY_HASHTABLE_SIZE - 1
    provenance_record["stats"]["size"] = REAL_CAPABILITY_HASHTABLE_SIZE - 1
    tampered_provenance = tmp_path / "HASHTABLE_PROVENANCE.json"
    _write_json(tampered_provenance, provenance)

    result = capability_import.validate_hashtable_artifacts(
        [tampered_table, corpus["resource_hashtable"]],
        tampered_provenance,
        canonical_capability_csv_path=corpus["capability_index"],
    )

    assert not result.ok
    assert any("CSV row count differs" in error.message for error in result.errors)


def test_real_authority_report_json_is_deterministic_and_read_only(
    loaded_authority, corpus, capsys
) -> None:
    before_bytes = loaded_authority.read_bytes()
    with sqlite3.connect(loaded_authority) as connection:
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
        str(loaded_authority),
        "--capability-csv",
        str(corpus["capability_index"]),
        "--priority-csv",
        str(corpus["priority_flags"]),
        "--hashtable",
        str(corpus["capability_hashtable"]),
        "--hashtable",
        str(corpus["resource_hashtable"]),
        "--provenance",
        str(corpus["provenance"]),
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
    assert payload["priority_annotation_summary"]["annotation_count"] == REAL_PRIORITY_ROWS
    assert [item["status"] for item in payload["csv_drift"]] == ["match", "match"]
    assert payload["hashtable_validation"]["ok"] is True
    assert payload["offline"] is True
    assert payload["read_only"] is True
    assert payload["live_kol_mutation"] is False
    assert loaded_authority.read_bytes() == before_bytes
    with sqlite3.connect(loaded_authority) as connection:
        after_counts = {
            "capability_records": connection.execute("SELECT count(*) FROM capability_records").fetchone()[0],
            "agent_resource_records": connection.execute("SELECT count(*) FROM agent_resource_records").fetchone()[0],
            "capability_priority_annotations": connection.execute(
                "SELECT count(*) FROM capability_priority_annotations"
            ).fetchone()[0],
        }
    assert after_counts == before_counts


def test_real_authority_report_text_contains_equivalent_offline_read_only_summary(
    loaded_authority, corpus, capsys
) -> None:
    return_code = cli.main(
        [
            "authority-report",
            "--db",
            str(loaded_authority),
            "--capability-csv",
            str(corpus["capability_index"]),
            "--priority-csv",
            str(corpus["priority_flags"]),
        ]
    )
    output = capsys.readouterr().out

    assert return_code == 0
    assert f"capability_records: {REAL_CAPABILITY_ROWS}" in output
    assert "agent_resource_records: 0" in output
    assert f"capability_priority_annotations: {REAL_PRIORITY_ROWS}" in output
    assert "authority_checksum.capability_records:" in output
    assert f"priority_annotation_count: {REAL_PRIORITY_ROWS}" in output
    assert "csv_drift: kolmafia_capability_index.csv status=match" in output
    assert "csv_drift: kolmafia_priority_flags.csv status=match" in output
    assert "offline/read-only" in output
    assert "performs no imports, writes, external calls, or live KoL mutation" in output


def test_real_authority_report_flags_csv_content_drift_without_mutation(
    loaded_authority, corpus, tmp_path: Path, capsys
) -> None:
    before_bytes = loaded_authority.read_bytes()
    drifted_capability = tmp_path / "kolmafia_capability_index.csv"
    rows = [
        dict(row)
        for row in csv.DictReader(corpus["capability_index"].read_text(encoding="utf-8").splitlines())
    ]
    rows[0]["candidate_risk"] = "mutating"
    _write_csv(drifted_capability, rows)

    return_code = cli.main(
        [
            "authority-report",
            "--db",
            str(loaded_authority),
            "--capability-csv",
            str(drifted_capability),
            "--priority-csv",
            str(corpus["priority_flags"]),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert return_code == 0
    assert payload["csv_drift"][0]["status"] == "drift"
    assert "content checksum drift" in payload["csv_drift"][0]["messages"]
    assert payload["csv_drift"][1]["status"] == "match"
    assert loaded_authority.read_bytes() == before_bytes


def test_real_authority_report_flags_advisory_hashtable_provenance_mismatch(
    loaded_authority, corpus, tmp_path: Path, capsys
) -> None:
    provenance = json.loads(corpus["provenance"].read_text(encoding="utf-8"))
    provenance["agent_resource.hashtable.json"]["sha256"] = "0" * 64
    tampered_provenance = tmp_path / "HASHTABLE_PROVENANCE.json"
    _write_json(tampered_provenance, provenance)

    return_code = cli.main(
        [
            "authority-report",
            "--db",
            str(loaded_authority),
            "--hashtable",
            str(corpus["capability_hashtable"]),
            "--hashtable",
            str(corpus["resource_hashtable"]),
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
