from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from kolmafa import cli, libkol_db_inspection, source_catalog


def _create_libkol_fixture(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE skills (
                skill_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                mp_cost INTEGER NOT NULL,
                skill_type TEXT NOT NULL
            );
            CREATE TABLE item_drops (
                item_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                zone TEXT NOT NULL,
                drop_rate REAL NOT NULL
            );
            INSERT INTO skills(skill_id, name, mp_cost, skill_type) VALUES
                (1, 'Leash of Linguini', 12, 'buff'),
                (2, 'Pastamastery', 0, 'passive');
            INSERT INTO item_drops(item_id, name, zone, drop_rate) VALUES
                (101, 'spooky mushroom', 'The Spooky Forest', 0.30),
                (102, 'meat stack', 'Noob Cave', 0.75);
            """
        )


@pytest.fixture
def libkol_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "libkol-fixture.db"
    _create_libkol_fixture(database_path)
    return database_path


def _database_snapshot(database_path: Path) -> tuple[str, ...]:
    with sqlite3.connect(database_path) as connection:
        return tuple(connection.iterdump())


def _table_counts(database_path: Path) -> dict[str, int]:
    with sqlite3.connect(database_path) as connection:
        return {
            table_name: connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            for table_name in ("skills", "item_drops")
        }


def _source_catalog_table_counts(database_path: Path) -> dict[str, int]:
    with sqlite3.connect(database_path) as connection:
        return {
            "source_catalog": connection.execute("SELECT COUNT(*) FROM source_catalog").fetchone()[0],
            "source_crosswalk": connection.execute("SELECT COUNT(*) FROM source_crosswalk").fetchone()[0],
        }


def _connect_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        calls.append((args, kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(libkol_db_inspection.sqlite3, "connect", tracking_connect)
    return calls


def test_inspection_json_is_stable_and_summarizes_fixture_schema(libkol_database: Path) -> None:
    first = libkol_db_inspection.inspect_database(libkol_database)
    second = libkol_db_inspection.inspect_database(libkol_database)

    first_json = libkol_db_inspection.result_to_json(first)
    second_json = libkol_db_inspection.result_to_json(second)
    payload = json.loads(first_json)

    assert first_json == second_json
    assert payload["ok"] is True
    assert payload["offline"] is True
    assert payload["live_kol_mutation"] is False
    assert payload["summary"]["path"] == libkol_database.name
    assert str(libkol_database) not in first_json
    assert payload["summary"]["table_count"] == 2
    assert payload["summary"]["row_count"] == 4
    assert [table["name"] for table in payload["tables"]] == ["item_drops", "skills"]
    assert payload["tables"][0]["columns"] == [
        {"name": "item_id", "type": "INTEGER", "primary_key": True, "not_null": False},
        {"name": "name", "type": "TEXT", "primary_key": False, "not_null": True},
        {"name": "zone", "type": "TEXT", "primary_key": False, "not_null": True},
        {"name": "drop_rate", "type": "REAL", "primary_key": False, "not_null": True},
    ]


def test_inspection_uses_sqlite_read_only_connection_and_does_not_mutate_rows_or_tables(
    libkol_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before_dump = _database_snapshot(libkol_database)
    before_counts = _table_counts(libkol_database)
    connect_calls = _connect_spy(monkeypatch)

    result = libkol_db_inspection.inspect_database(libkol_database)

    assert result.ok is True
    assert _database_snapshot(libkol_database) == before_dump
    assert _table_counts(libkol_database) == before_counts
    assert len(connect_calls) == 1
    args, kwargs = connect_calls[0]
    assert kwargs.get("uri") is True
    assert "mode=ro" in str(args[0])


def test_inspection_proposes_source_catalog_and_crosswalk_rows_without_writing_them(
    libkol_database: Path,
) -> None:
    result = libkol_db_inspection.inspect_database(libkol_database)
    payload = json.loads(libkol_db_inspection.result_to_json(result))

    proposals = payload["proposals"]
    assert proposals["write_mode"] == "proposal_only"
    assert proposals["authority_mutation"] is False
    assert proposals["planned_rows"] == {
        "source_catalog": 1,
        "source_crosswalk": 2,
    }
    assert proposals["planned_rows"] == {
        "source_catalog": len(proposals["source_catalog"]),
        "source_crosswalk": len(proposals["source_crosswalk"]),
    }
    source_catalog_contract = set(source_catalog.SourceCatalogLoadRow.__dataclass_fields__)
    assert proposals["source_catalog"] == [
        {
            "source_id": "don-libkol",
            "name": "don-libkol",
            "title": "don-libkol archived libkol.db reference",
            "category": "archived_external_reference",
            "reference_kind": "github_repository",
            "canonical_reference": "github.com/don/libkol#libkol.db",
            "stack_language": "Python/SQLite",
            "trust": "archived_reference_unverified",
            "provenance": {
                "authority_mutation": False,
                "artifact": "inspect-libkol-db",
                "category": "archived_external_reference",
                "classification": "proposal/advisory",
                "inspected_database": "libkol-fixture.db",
                "reference_kind": "github_repository",
                "reference_label": "don-libkol",
                "write_mode": "proposal_only",
            },
            "input_sha256": payload["summary"]["sha256"],
            "source_line_sha256": "58fdbb8fb5713445bf2b8a63f53d3d81b004cc97e41aea87d7b7fd897cbc61cb",
            "source_line_number": 0,
            "local_only": True,
            "publishability": "local_reference_redacted",
            "recommendation": "inspect_offline_only_before_authority_import",
        }
    ]
    assert set(proposals["source_catalog"][0]) == source_catalog_contract
    allowed_graph_buckets = {"GAMEPLAY", "AGENT_STACK", "KNOWLEDGE_BASE"}
    assert proposals["source_crosswalk"] == [
        {
            "crosswalk_id": "don-libkol:KNOWLEDGE_BASE:libkol.table.item_drops:summarizes_table",
            "source_id": "don-libkol",
            "source_content_hash": payload["summary"]["sha256"],
            "graph_category": "KNOWLEDGE_BASE",
            "graph_node_key": "libkol.table.item_drops",
            "relationship": "summarizes_table",
            "confidence": "proposal_advisory",
            "evidence_content_hash": payload["tables"][0]["content_sha256"],
            "provenance": {
                "authority_mutation": False,
                "artifact": "inspect-libkol-db",
                "classification": "proposal/advisory",
                "evidence_content_hash": payload["tables"][0]["content_sha256"],
                "evidence_row_count": 2,
                "evidence_table": "item_drops",
                "inspected_database": "libkol-fixture.db",
                "reference_label": "don-libkol",
                "write_mode": "proposal_only",
            },
        },
        {
            "crosswalk_id": "don-libkol:KNOWLEDGE_BASE:libkol.table.skills:summarizes_table",
            "source_id": "don-libkol",
            "source_content_hash": payload["summary"]["sha256"],
            "graph_category": "KNOWLEDGE_BASE",
            "graph_node_key": "libkol.table.skills",
            "relationship": "summarizes_table",
            "confidence": "proposal_advisory",
            "evidence_content_hash": payload["tables"][1]["content_sha256"],
            "provenance": {
                "authority_mutation": False,
                "artifact": "inspect-libkol-db",
                "classification": "proposal/advisory",
                "evidence_content_hash": payload["tables"][1]["content_sha256"],
                "evidence_row_count": 2,
                "evidence_table": "skills",
                "inspected_database": "libkol-fixture.db",
                "reference_label": "don-libkol",
                "write_mode": "proposal_only",
            },
        },
    ]
    assert set(proposals["source_crosswalk"][0]) == {
        "crosswalk_id",
        "source_id",
        "source_content_hash",
        "graph_category",
        "graph_node_key",
        "relationship",
        "confidence",
        "evidence_content_hash",
        "provenance",
    }
    assert {
        row["graph_category"] for row in proposals["source_crosswalk"]
    } <= allowed_graph_buckets

    with sqlite3.connect(libkol_database) as connection:
        existing_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }
    assert existing_tables == {"item_drops", "skills"}


def test_cli_inspect_libkol_db_text_documents_manual_command_without_absolute_path(
    libkol_database: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(libkol_database.parent)

    code = cli.main(["inspect-libkol-db", "--db", str(libkol_database)])
    output = capsys.readouterr().out

    assert code == 0
    assert "proposal_mode: proposal_only" in output
    assert "source_catalog_candidate: don-libkol archived_external_reference proposal/advisory" in output
    assert "source_crosswalk_candidate: KNOWLEDGE_BASE libkol.table.item_drops" in output
    assert "source_crosswalk_candidate: KNOWLEDGE_BASE libkol.table.skills" in output
    assert "operator_command: kolmafa inspect-libkol-db --db <downloaded-libkol-db> --json" in output
    assert str(libkol_database) not in output
    assert str(libkol_database.parent) not in output


def test_cli_inspect_libkol_db_json_is_stable_redacted_and_read_only(
    libkol_database: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(libkol_database.parent)
    before_dump = _database_snapshot(libkol_database)

    argv = ["inspect-libkol-db", "--json", "--db", str(libkol_database)]
    first_code = cli.main(argv)
    first_output = capsys.readouterr().out
    second_code = cli.main(argv)
    second_output = capsys.readouterr().out

    payload = json.loads(first_output)
    assert first_code == 0
    assert second_code == 0
    assert first_output == second_output
    assert payload["ok"] is True
    assert payload["summary"]["path"] == libkol_database.name
    assert "source_catalog" in payload["proposals"]
    assert "source_crosswalk" in payload["proposals"]
    assert str(libkol_database) not in first_output
    assert str(libkol_database.parent) not in first_output
    assert _database_snapshot(libkol_database) == before_dump


def test_cli_load_source_catalog_accepts_explicit_libkol_inspection_json(
    libkol_database: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before_dump = _database_snapshot(libkol_database)
    authority_database = tmp_path / "source-authority.db"
    inspection_path = tmp_path / "libkol-inspection.json"
    inspection_path.write_text(
        libkol_db_inspection.result_to_json(libkol_db_inspection.inspect_database(libkol_database)),
        encoding="utf-8",
    )

    argv = [
        "load-source-catalog",
        "--json",
        "--db",
        str(authority_database),
        "--libkol-inspection-json",
        str(inspection_path),
    ]
    first_code = cli.main(argv)
    first_output = capsys.readouterr().out
    second_code = cli.main(argv)
    second_output = capsys.readouterr().out

    first = json.loads(first_output)
    second = json.loads(second_output)
    assert first_code == 0
    assert second_code == 0
    assert first["counts"] == {
        "conflicts": 0,
        "inserted": 3,
        "source_catalog": 1,
        "source_crosswalk": 2,
        "unchanged": 0,
    }
    assert second["counts"]["inserted"] == 0
    assert second["counts"]["unchanged"] == 3
    assert _source_catalog_table_counts(authority_database) == {
        "source_catalog": 1,
        "source_crosswalk": 2,
    }
    assert str(libkol_database) not in first_output
    assert str(inspection_path) not in first_output
    assert first["offline"] is True
    assert first["live_kol_mutation"] is False
    assert _database_snapshot(libkol_database) == before_dump


def test_cli_load_source_catalog_missing_libkol_inspection_json_redacts_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "source-authority.db"
    missing_path = tmp_path / "nested" / "missing-libkol-inspection.json"

    json_code = cli.main(
        [
            "load-source-catalog",
            "--json",
            "--db",
            str(database_path),
            "--libkol-inspection-json",
            str(missing_path),
        ]
    )
    json_output = capsys.readouterr().out
    text_code = cli.main(
        [
            "load-source-catalog",
            "--db",
            str(database_path),
            "--libkol-inspection-json",
            str(missing_path),
        ]
    )
    text_output = capsys.readouterr().out

    payload = json.loads(json_output)
    assert json_code == 1
    assert text_code == 1
    assert payload["errors"] == [
        {
            "artifact": missing_path.name,
            "row_id": None,
            "message": "unable to read libkol inspection JSON: No such file or directory",
        }
    ]
    assert (
        f"error: {missing_path.name}: unable to read libkol inspection JSON: No such file or directory"
        in text_output
    )
    combined_output = json_output + text_output
    assert str(missing_path) not in combined_output
    assert str(missing_path.parent) not in combined_output


def test_cli_inspect_libkol_db_requires_explicit_path() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(["inspect-libkol-db", "--json"])

    assert exc_info.value.code == 2
