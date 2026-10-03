from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from kolmafa import db


SCHEMA_PATH = Path(__file__).parents[1] / "sql" / "schema.sql"


def _connect_schema(tmp_path: Path) -> sqlite3.Connection:
    database_path = tmp_path / "authority.db"
    db.init_database(database_path)
    connection = db.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _foreign_keys(connection: sqlite3.Connection, table: str) -> set[tuple[str, str, str]]:
    return {
        (row["from"], row["table"], row["to"])
        for row in connection.execute(f"PRAGMA foreign_key_list({table})")
    }


def _indexes(connection: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}


def _primary_key_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return tuple(row["name"] for row in sorted(rows, key=lambda row: row["pk"]) if row["pk"])


def _index_columns(connection: sqlite3.Connection, index_name: str) -> tuple[str, ...]:
    return tuple(row["name"] for row in connection.execute(f"PRAGMA index_info({index_name})"))


def test_init_database_is_idempotent_and_enables_wal_and_foreign_keys(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"

    db.init_database(database_path)
    db.init_database(database_path)

    with db.connect(database_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_init_database_migrates_legacy_rag_and_command_tables_idempotently(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                source_path TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE VIRTUAL TABLE documents_fts USING fts5(
                title, body, source_path UNINDEXED, content='documents', content_rowid='id'
            );
            CREATE TABLE command_log (
                id INTEGER PRIMARY KEY,
                command TEXT NOT NULL,
                transport TEXT NOT NULL,
                return_code INTEGER,
                stdout TEXT,
                stderr TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO documents(id, source_path, title, body) VALUES (1, '/tmp/a.md', 'a.md', 'relay text');
            INSERT INTO command_log(id, command, transport, return_code) VALUES (1, 'status', 'gcli', 0);
            """
        )

    db.init_database(database_path)
    db.init_database(database_path)

    with db.connect(database_path) as connection:
        document = connection.execute(
            "SELECT document_id, source_path, body_redacted FROM documents WHERE id = 1"
        ).fetchone()
        command = connection.execute(
            "SELECT command_log_id, command_text_redacted FROM command_log WHERE id = 1"
        ).fetchone()

        assert document["document_id"]
        assert (document["source_path"], document["body_redacted"]) == ("/tmp/a.md", "relay text")
        assert command["command_log_id"]
        assert command["command_text_redacted"] == "status"


def test_init_database_redacts_legacy_session_line_before_hashing_and_dropping_raw_column(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-session.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE session_events (
                id INTEGER PRIMARY KEY,
                player_name TEXT NOT NULL,
                line TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO session_events(id, player_name, line)
            VALUES (1, 'player', 'hello token=raw-session-migration-secret');
            """
        )

    db.init_database(database_path)
    db.init_database(database_path)

    expected_redacted = "hello token=<redacted>"
    expected_hash = hashlib.sha256(expected_redacted.encode("utf-8")).hexdigest()
    with db.connect(database_path) as connection:
        row = connection.execute(
            "SELECT message_redacted, message_hash FROM session_events WHERE id = 1"
        ).fetchone()
        columns = _table_columns(connection, "session_events")

    assert "line" not in columns
    assert row["message_redacted"] == expected_redacted
    assert row["message_hash"] == expected_hash
    assert "raw-session-migration-secret" not in "".join(str(value) for value in row)


def test_init_database_redacts_existing_v1_command_raw_columns_before_hashing_and_dropping(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-command-v1.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE command_log (
                id INTEGER PRIMARY KEY,
                command_log_id TEXT NOT NULL UNIQUE,
                command TEXT,
                transport TEXT NOT NULL,
                command_class TEXT NOT NULL DEFAULT 'unknown',
                command_text_redacted TEXT,
                return_code INTEGER,
                stdout TEXT,
                stderr TEXT,
                stdout_redacted TEXT,
                stderr_redacted TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO command_log(
                id, command_log_id, command, transport, command_class,
                command_text_redacted, return_code, stdout, stderr,
                stdout_redacted, stderr_redacted
            ) VALUES (
                1, 'cmd-legacy', 'status token=raw-command-migration-secret', 'legacy', 'unknown',
                NULL, 1, 'cookie=raw-stdout-migration-secret ok', 'pwd=raw-stderr-migration-secret denied',
                NULL, NULL
            );
            """
        )

    db.init_database(database_path)

    expected_command = "status token=<redacted>"
    expected_stdout = "cookie=<redacted> ok"
    expected_stderr = "pwd=<redacted> denied"
    with db.connect(database_path) as connection:
        row = connection.execute(
            "SELECT command_text_redacted, command_hash, stdout_redacted, stdout_hash, "
            "stderr_redacted, stderr_hash FROM command_log WHERE id = 1"
        ).fetchone()
        columns = _table_columns(connection, "command_log")

    assert {"command", "stdout", "stderr"}.isdisjoint(columns)
    assert tuple(row) == (
        expected_command,
        hashlib.sha256(expected_command.encode("utf-8")).hexdigest(),
        expected_stdout,
        hashlib.sha256(expected_stdout.encode("utf-8")).hexdigest(),
        expected_stderr,
        hashlib.sha256(expected_stderr.encode("utf-8")).hexdigest(),
    )
    serialized = "".join(str(value) for value in row)
    assert "raw-command-migration-secret" not in serialized
    assert "raw-stdout-migration-secret" not in serialized
    assert "raw-stderr-migration-secret" not in serialized


def test_v1_authority_tables_keys_foreign_keys_and_indexes(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        expected_tables = {
            "sessions",
            "messages",
            "events",
            "tasks",
            "task_edges",
            "task_runs",
            "policy_decisions",
            "action_confirmations",
            "command_log",
            "artifacts",
            "documents",
            "document_chunks",
            "vector_rows",
            "q_states",
            "q_actions",
            "q_values",
            "rewards",
            "session_events",
        }
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
            )
        }
        assert expected_tables <= tables

        assert "session_id" in _table_columns(connection, "sessions")
        assert "task_id" in _table_columns(connection, "tasks")
        assert {"task_id", "depends_on"} <= _table_columns(connection, "task_edges")
        assert {"policy_decision_id", "requires_confirmation"} <= _table_columns(
            connection, "policy_decisions"
        )
        assert {"action_hash", "arguments_hash", "mode_hash", "state_binding_hash", "consumed_at"} <= _table_columns(
            connection, "action_confirmations"
        )

        assert ("session_id", "sessions", "session_id") in _foreign_keys(connection, "tasks")
        assert ("task_id", "tasks", "task_id") in _foreign_keys(connection, "task_edges")
        assert ("depends_on", "tasks", "task_id") in _foreign_keys(connection, "task_edges")
        assert ("policy_decision_id", "policy_decisions", "policy_decision_id") in _foreign_keys(
            connection, "action_confirmations"
        )

        indexes = _indexes(connection)
        assert {
            "idx_tasks_session_status",
            "idx_task_edges_depends_on",
            "idx_confirmations_exact_action",
            "idx_documents_source",
            "idx_chunks_document",
            "idx_q_values_action",
        } <= indexes


def test_sql_authority_capability_schema_matches_canonical_csv_contract(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        columns = _table_columns(connection, "capability_records")
        annotation_columns = _table_columns(connection, "capability_priority_annotations")

        assert _primary_key_columns(connection, "capability_records") == ("entry_id",)
        assert {
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
            "argument_dependent",
            "domains_touched",
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
            "candidate_risk",
            "recursive_classification_required",
            "fail_closed_if_unresolved",
            "native_or_runtime_surface",
            "notes",
            "source_corpus",
            "source_row_number",
            "source_content_hash",
            "provenance_json",
        } <= columns

        indexes = _indexes(connection)
        assert {
            "idx_capability_records_name_type",
            "idx_capability_records_risk",
            "idx_capability_priority_annotations_risk",
        } <= indexes
        assert _index_columns(connection, "idx_capability_records_name_type") == (
            "name",
            "entry_type",
            "language",
        )
        assert _primary_key_columns(connection, "capability_priority_annotations") == ("entry_id",)
        assert (
            "entry_id",
            "capability_records",
            "entry_id",
        ) in _foreign_keys(connection, "capability_priority_annotations")
        assert {
            "entry_id",
            "priority_candidate_risk",
            "priority_recursive_classification_required",
            "priority_fail_closed_if_unresolved",
            "annotation_json",
            "source_corpus",
            "source_row_number",
            "source_content_hash",
        } <= annotation_columns

        connection.execute(
            """
            INSERT INTO capability_records(
                entry_id, name, entry_type, language, signature_or_syntax,
                source_document, source_location, evidence_status, read_or_mutate,
                source_corpus, source_row_number, source_content_hash
            ) VALUES (
                'ash.abort.string', 'abort', 'ash_function', 'ASH', 'void abort( string? )',
                'Ash_Functions_-_Kolmafia.pdf (uploaded)', 'line 1',
                'verified_from_supplied_reference', 'mutating',
                'kolmafia_capability_index.csv', 2, 'fixture-hash'
            )
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO capability_records(
                    entry_id, name, entry_type, language, source_document,
                    source_location, evidence_status, read_or_mutate,
                    source_corpus, source_row_number, source_content_hash
                ) VALUES (
                    'ash.abort.string', 'abort duplicate', 'ash_function', 'ASH', 'doc',
                    'line 1', 'verified_from_supplied_reference', 'mutating',
                    'kolmafia_priority_flags.csv', 2, 'fixture-hash-2'
                )
                """
            )

        connection.execute(
            """
            INSERT INTO capability_priority_annotations(
                entry_id, priority_candidate_risk, source_row_number, source_content_hash
            ) VALUES ('ash.abort.string', 'unresolved', 2, 'priority-hash')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO capability_priority_annotations(
                    entry_id, priority_candidate_risk, source_row_number, source_content_hash
                ) VALUES ('ash.missing.noargs', 'unresolved', 3, 'priority-hash-2')
                """
            )


def test_sql_authority_agent_resource_schema_keys_uniqueness_and_indexes(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        columns = _table_columns(connection, "agent_resource_records")

        assert _primary_key_columns(connection, "agent_resource_records") == ("resource_id",)
        assert {
            "resource_id",
            "capability_entry_id",
            "resource_kind",
            "resource_name",
            "access_mode",
            "authority_surface",
            "source_corpus",
            "source_entry_id",
            "source_row_number",
            "source_content_hash",
            "provenance_json",
        } <= columns
        assert (
            "capability_entry_id",
            "capability_records",
            "entry_id",
        ) in _foreign_keys(connection, "agent_resource_records")

        indexes = _indexes(connection)
        assert {
            "idx_agent_resource_records_capability",
            "idx_agent_resource_records_lookup",
            "idx_agent_resource_records_source",
        } <= indexes
        assert _index_columns(connection, "idx_agent_resource_records_lookup") == (
            "resource_kind",
            "resource_name",
            "access_mode",
        )

        connection.execute(
            """
            INSERT INTO capability_records(
                entry_id, name, entry_type, language, source_document,
                source_location, evidence_status, read_or_mutate,
                source_corpus, source_row_number, source_content_hash
            ) VALUES (
                'ash.abort.string', 'abort', 'ash_function', 'ASH', 'doc',
                'line 1', 'verified_from_supplied_reference', 'mutating',
                'kolmafia_capability_index.csv', 2, 'fixture-hash'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO agent_resource_records(
                resource_id, capability_entry_id, resource_kind, resource_name, access_mode,
                source_corpus, source_entry_id, source_row_number, source_content_hash
            ) VALUES (
                'res-1', 'ash.abort.string', 'game_state', 'abort', 'mutate',
                'kolmafia_capability_index.csv', 'ash.abort.string', 2, 'fixture-hash'
            )
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO agent_resource_records(
                    resource_id, capability_entry_id, resource_kind, resource_name, access_mode,
                    source_corpus, source_entry_id, source_row_number, source_content_hash
                ) VALUES (
                    'res-2', 'ash.abort.string', 'game_state', 'abort', 'mutate',
                    'kolmafia_capability_index.csv', 'ash.abort.string', 2, 'fixture-hash'
                )
                """
            )


def test_sql_source_catalog_schema_keys_flags_and_indexes(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        columns = _table_columns(connection, "source_catalog")

        assert _primary_key_columns(connection, "source_catalog") == ("source_id",)
        assert {
            "source_id",
            "title",
            "source_name",
            "source_uri",
            "source_path",
            "source_category",
            "stack_language",
            "kol_relevance",
            "trust_level",
            "source_load_status",
            "load_manifest_id",
            "source_version",
            "source_content_hash",
            "source_metadata_hash",
            "provenance_json",
            "local_only",
            "publishable",
            "recommendation",
        } <= columns

        indexes = _indexes(connection)
        assert {
            "idx_source_catalog_category",
            "idx_source_catalog_publishability",
            "idx_source_catalog_conflict_lookup",
            "uq_source_catalog_loaded_identity_content",
        } <= indexes
        assert _index_columns(connection, "idx_source_catalog_category") == (
            "source_category",
            "stack_language",
        )
        assert _index_columns(connection, "idx_source_catalog_publishability") == (
            "local_only",
            "publishable",
        )


def test_source_catalog_tracks_load_provenance_checksums_and_conflicts(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        for source_id, content_hash in (("src-v1", "sha256-content-a"), ("src-v2", "sha256-content-b")):
            connection.execute(
                """
                INSERT INTO source_catalog(
                    source_id, title, source_name, source_uri, source_path, source_category,
                    source_load_status, load_manifest_id, source_version,
                    source_content_hash, source_metadata_hash, provenance_json,
                    local_only, publishable
                ) VALUES (
                    ?, 'Source', 'KoL docs', 'https://example.test/koldocs', NULL, 'reference',
                    'loaded', 'manifest-20260727', '2026-07-27', ?, 'sha256-metadata',
                    '{"loaded_by":"fixture"}', 0, 1
                )
                """,
                (source_id, content_hash),
            )

        conflict_candidates = connection.execute(
            """
            SELECT source_id, source_content_hash
            FROM source_catalog
            WHERE source_name = 'KoL docs' AND source_uri = 'https://example.test/koldocs'
            ORDER BY source_id
            """
        ).fetchall()
        assert [tuple(row) for row in conflict_candidates] == [
            ("src-v1", "sha256-content-a"),
            ("src-v2", "sha256-content-b"),
        ]

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO source_catalog(
                    source_id, title, source_name, source_uri, source_category,
                    source_load_status, source_content_hash
                ) VALUES (
                    'src-duplicate', 'Source', 'KoL docs', 'https://example.test/koldocs',
                    'reference', 'loaded', 'sha256-content-a'
                )
                """
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO source_catalog(
                    source_id, title, source_category, source_load_status
                ) VALUES ('src-bad-status', 'bad', 'reference', 'implicit')
                """
            )


def test_source_catalog_flag_constraints_and_input_variations(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        samples = [
            ("src-local", "Local markdown", None, "/safe/local.md", 1, 0),
            ("src-public", "Public docs", "https://example.test/doc", None, 0, 1),
            ("src-extreme", "x" * 256, "file:///safe/long", "/safe/long", 0, 0),
        ]
        for source_id, title, uri, path, local_only, publishable in samples:
            connection.execute(
                """
                INSERT INTO source_catalog(
                    source_id, title, source_uri, source_path, source_category,
                    stack_language, kol_relevance, trust_level, local_only, publishable,
                    recommendation
                ) VALUES (?, ?, ?, ?, 'reference', 'Python', 'high', 'curated', ?, ?, 'use')
                """,
                (source_id, title, uri, path, local_only, publishable),
            )

        assert connection.execute("SELECT COUNT(*) FROM source_catalog").fetchone()[0] == 3
        for flag_column, local_only, publishable in (
            ("local_only", 2, 1),
            ("publishable", 0, 2),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"""
                    INSERT INTO source_catalog(
                        source_id, title, source_category, local_only, publishable
                    ) VALUES ('bad-{flag_column}', 'bad', 'reference', ?, ?)
                    """,
                    (local_only, publishable),
                )


def test_sql_source_crosswalk_schema_foreign_keys_graph_buckets_and_indexes(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        columns = _table_columns(connection, "source_crosswalk")

        assert _primary_key_columns(connection, "source_crosswalk") == ("crosswalk_id",)
        assert {
            "crosswalk_id",
            "source_id",
            "source_content_hash",
            "graph_category",
            "graph_node_key",
            "relationship",
            "confidence",
            "evidence_content_hash",
            "provenance_json",
        } <= columns
        assert ("source_id", "source_catalog", "source_id") in _foreign_keys(
            connection, "source_crosswalk"
        )

        indexes = _indexes(connection)
        assert {
            "idx_source_crosswalk_source",
            "idx_source_crosswalk_graph",
            "idx_source_crosswalk_source_content",
        } <= indexes
        assert _index_columns(connection, "idx_source_crosswalk_graph") == (
            "graph_category",
            "graph_node_key",
        )


def test_source_crosswalk_binds_relationship_to_source_checksum_without_weakening_uniqueness(
    tmp_path: Path,
) -> None:
    with _connect_schema(tmp_path) as connection:
        connection.execute(
            """
            INSERT INTO source_catalog(
                source_id, title, source_category, source_load_status, source_content_hash
            ) VALUES ('src', 'source', 'reference', 'loaded', 'sha256-source')
            """
        )
        connection.execute(
            """
            INSERT INTO source_crosswalk(
                crosswalk_id, source_id, source_content_hash, graph_category,
                graph_node_key, relationship, evidence_content_hash, provenance_json
            ) VALUES (
                'cw-1', 'src', 'sha256-source', 'KNOWLEDGE_BASE',
                'node', 'supports', 'sha256-evidence', '{"line":1}'
            )
            """
        )

        row = connection.execute(
            """
            SELECT source_content_hash, evidence_content_hash, provenance_json
            FROM source_crosswalk WHERE crosswalk_id = 'cw-1'
            """
        ).fetchone()
        assert tuple(row) == ("sha256-source", "sha256-evidence", '{"line":1}')

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO source_crosswalk(
                    crosswalk_id, source_id, source_content_hash, graph_category,
                    graph_node_key, relationship
                ) VALUES (
                    'cw-duplicate', 'src', 'sha256-other', 'KNOWLEDGE_BASE',
                    'node', 'supports'
                )
                """
            )


@pytest.mark.parametrize("graph_category", ["GAMEPLAY", "AGENT_STACK", "KNOWLEDGE_BASE"])
def test_source_crosswalk_accepts_only_known_graph_buckets(
    tmp_path: Path, graph_category: str
) -> None:
    with _connect_schema(tmp_path) as connection:
        connection.execute(
            """
            INSERT INTO source_catalog(source_id, title, source_category, local_only, publishable)
            VALUES ('src', 'source', 'reference', 0, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO source_crosswalk(
                crosswalk_id, source_id, graph_category, graph_node_key, relationship
            ) VALUES (?, 'src', ?, 'node', 'supports')
            """,
            (f"cw-{graph_category}", graph_category),
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO source_crosswalk(
                    crosswalk_id, source_id, graph_category, graph_node_key, relationship
                ) VALUES ('cw-bad', 'src', 'UNKNOWN', 'node', 'supports')
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO source_crosswalk(
                    crosswalk_id, source_id, graph_category, graph_node_key, relationship
                ) VALUES ('cw-missing', 'missing', 'GAMEPLAY', 'node', 'supports')
                """
            )


def test_source_catalog_and_crosswalk_initialize_idempotently_without_loading_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "authority.db"

    db.init_database(database_path)
    with db.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_catalog").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM source_crosswalk").fetchone()[0] == 0
        connection.execute(
            """
            INSERT INTO source_catalog(source_id, title, source_category, local_only, publishable)
            VALUES ('src-idem', 'source', 'reference', 1, 0)
            """
        )
        connection.execute(
            """
            INSERT INTO source_crosswalk(
                crosswalk_id, source_id, graph_category, graph_node_key, relationship
            ) VALUES ('cw-idem', 'src-idem', 'KNOWLEDGE_BASE', 'node', 'supports')
            """
        )

    db.init_database(database_path)
    db.init_database(database_path)

    with db.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_catalog").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM source_crosswalk").fetchone()[0] == 1
        catalog_row = connection.execute(
            """
            SELECT source_load_status, load_manifest_id, source_content_hash, source_metadata_hash
            FROM source_catalog WHERE source_id = 'src-idem'
            """
        ).fetchone()
        crosswalk_row = connection.execute(
            """
            SELECT source_content_hash, evidence_content_hash
            FROM source_crosswalk WHERE crosswalk_id = 'cw-idem'
            """
        ).fetchone()

    assert tuple(catalog_row) == ("declared", "", "", "")
    assert tuple(crosswalk_row) == ("", "")


def test_task_edges_reject_self_dependencies_and_cycles(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        connection.execute("INSERT INTO sessions(session_id, mode, status) VALUES ('s1', 'deep', 'pending')")
        for task_id in ("a", "b", "c"):
            connection.execute(
                "INSERT INTO tasks(task_id, session_id, title, task_type, status) VALUES (?, 's1', ?, 'plan', 'pending')",
                (task_id, task_id),
            )

        with pytest.raises(sqlite3.IntegrityError, match="self-dependency"):
            connection.execute("INSERT INTO task_edges(task_id, depends_on) VALUES ('a', 'a')")

        connection.execute("INSERT INTO task_edges(task_id, depends_on) VALUES ('a', 'b')")
        connection.execute("INSERT INTO task_edges(task_id, depends_on) VALUES ('b', 'c')")

        with pytest.raises(sqlite3.IntegrityError, match="cycle"):
            connection.execute("INSERT INTO task_edges(task_id, depends_on) VALUES ('c', 'a')")


def test_confirmation_contract_binds_exact_action_and_supports_one_shot_consumption(
    tmp_path: Path,
) -> None:
    with _connect_schema(tmp_path) as connection:
        connection.execute("INSERT INTO sessions(session_id, mode, status) VALUES ('s1', 'normal', 'pending')")
        connection.execute(
            """
            INSERT INTO policy_decisions(
                policy_decision_id, session_id, decision, command_class, allowlist_id,
                requires_confirmation, reason_redacted, expires_at
            ) VALUES ('p1', 's1', 'needs_confirmation', 'game_action', 'allow-game', 1, 'fixture', datetime('now', '+1 hour'))
            """
        )
        connection.execute(
            """
            INSERT INTO action_confirmations(
                confirmation_id, session_id, policy_decision_id, actor_id, actor_surface,
                command_class, transport, action_text_redacted, action_hash, arguments_hash,
                mode_hash, state_binding_hash, allowlist_id, status, expires_at
            ) VALUES (
                'c1', 's1', 'p1', 'operator', 'cli', 'game_action', 'gcli',
                'attack redacted', 'action-hash', 'args-hash', 'mode-hash', 'state-hash',
                'allow-game', 'confirmed', datetime('now', '+1 hour')
            )
            """
        )
        connection.execute(
            """
            INSERT INTO command_log(
                command_log_id, session_id, transport, command_class, command_text_redacted,
                allowlist_id, confirmation_id, policy_decision_id, return_code
            ) VALUES ('cmd1', 's1', 'gcli', 'game_action', 'attack redacted', 'allow-game', 'c1', 'p1', 0)
            """
        )
        connection.execute(
            """
            UPDATE action_confirmations
            SET status = 'consumed', consumed_at = CURRENT_TIMESTAMP, consumed_by_command_log_id = 'cmd1'
            WHERE confirmation_id = 'c1'
            """
        )

        consumed = connection.execute(
            "SELECT action_hash, arguments_hash, mode_hash, state_binding_hash, consumed_by_command_log_id FROM action_confirmations"
        ).fetchone()
        assert tuple(consumed) == ("action-hash", "args-hash", "mode-hash", "state-hash", "cmd1")

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO command_log(
                    command_log_id, session_id, transport, command_class, command_text_redacted,
                    allowlist_id, confirmation_id, policy_decision_id
                ) VALUES ('cmd2', 's1', 'gcli', 'game_action', 'attack redacted', 'allow-game', 'c1', 'p1')
                """
            )


def test_rag_fts5_fallback_is_present_without_mandatory_sqlite_vec(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        fts = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'documents_fts'"
        ).fetchone()[0]
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8").lower()

        assert "using fts5" in fts.lower()
        assert "using vec" not in schema_sql
        assert "chromadb" not in schema_sql


def test_shadow_q_tables_are_inert_and_do_not_drive_policy_authority(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        assert {"q_states", "q_actions", "q_values", "rewards"} <= {
            row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

        policy_columns = _table_columns(connection, "policy_decisions")
        command_columns = _table_columns(connection, "command_log")
        policy_fks = _foreign_keys(connection, "policy_decisions")
        command_fks = _foreign_keys(connection, "command_log")

        assert not any(column.startswith("q_") for column in policy_columns | command_columns)
        assert not any(target.startswith("q_") for _, target, _ in policy_fks | command_fks)


def test_schema_exposes_no_raw_command_session_or_document_body_columns(tmp_path: Path) -> None:
    with _connect_schema(tmp_path) as connection:
        assert {"command", "stdout", "stderr"}.isdisjoint(_table_columns(connection, "command_log"))
        assert "line" not in _table_columns(connection, "session_events")
        assert "body" not in _table_columns(connection, "documents")

        assert {"command_text_redacted", "command_hash", "stdout_hash", "stderr_hash"} <= _table_columns(
            connection, "command_log"
        )
        assert {"message_redacted", "message_hash"} <= _table_columns(connection, "session_events")
        assert {"body_redacted", "body_hash"} <= _table_columns(connection, "documents")


def test_command_and_session_persistence_store_hashes_not_raw_text(tmp_path: Path) -> None:
    from kolmafa.bridge import CommandResult, log_command, parse_kolmafa_user_line, persist_session_event

    with _connect_schema(tmp_path) as connection:
        log_command(
            connection,
            CommandResult(
                command="status token=raw-command-secret",
                transport="fixture",
                return_code=0,
                stdout="cookie=raw-output-secret ok",
                stderr="pwd=raw-error-secret denied",
            ),
        )
        event = parse_kolmafa_user_line(
            "KOLMAFA_USER: hello token=raw-session-secret",
            player_name="player",
        )
        assert event is not None
        persist_session_event(connection, event)

        command_row = connection.execute(
            "SELECT command_text_redacted, command_hash, stdout_redacted, stdout_hash, stderr_redacted, stderr_hash "
            "FROM command_log"
        ).fetchone()
        session_row = connection.execute(
            "SELECT message_redacted, message_hash FROM session_events"
        ).fetchone()

    assert "raw-command-secret" not in "".join(str(value) for value in command_row)
    assert "raw-output-secret" not in "".join(str(value) for value in command_row)
    assert "raw-error-secret" not in "".join(str(value) for value in command_row)
    assert command_row["command_hash"]
    assert command_row["stdout_hash"]
    assert command_row["stderr_hash"]
    assert session_row["message_redacted"] == "hello token=<redacted>"
    assert session_row["message_hash"]
    assert "raw-session-secret" not in "".join(str(value) for value in session_row)


def test_fts_delete_and_update_paths_use_redacted_body_not_raw_body(tmp_path: Path) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8").lower()

    assert "old.body," not in schema_sql
    assert "new.body," not in schema_sql
    assert "body text not null" not in schema_sql

    with _connect_schema(tmp_path) as connection:
        connection.execute(
            """
            INSERT INTO documents(document_id, source_path, title, body_redacted, body_hash)
            VALUES ('doc1', '/safe/doc.txt', 'doc', 'safe redacted body', 'hash1')
            """
        )
        connection.execute(
            "UPDATE documents SET body_redacted = 'new redacted body', body_hash = 'hash2' WHERE document_id = 'doc1'"
        )
        connection.execute("DELETE FROM documents WHERE document_id = 'doc1'")


def test_redaction_guard_aborts_insert_with_unredacted_pwd_in_command_text(
    tmp_path: Path,
) -> None:
    with _connect_schema(tmp_path) as connection:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="command_log contains unredacted secret-like value",
        ):
            connection.execute(
                "INSERT INTO command_log(transport, command_text_redacted) "
                "VALUES ('test', 'pwd=raw')"
            )


def test_redaction_guard_aborts_insert_with_unredacted_cookie_in_stdout(
    tmp_path: Path,
) -> None:
    with _connect_schema(tmp_path) as connection:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="command_log contains unredacted secret-like value",
        ):
            connection.execute(
                "INSERT INTO command_log(transport, stdout_redacted) "
                "VALUES ('test', 'cookie=raw')"
            )


def test_redaction_guard_aborts_insert_with_unredacted_token_in_stderr(
    tmp_path: Path,
) -> None:
    with _connect_schema(tmp_path) as connection:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="command_log contains unredacted secret-like value",
        ):
            connection.execute(
                "INSERT INTO command_log(transport, stderr_redacted) "
                "VALUES ('test', 'token=raw')"
            )


def test_redaction_guard_aborts_update_with_unredacted_secret_like_value(
    tmp_path: Path,
) -> None:
    with _connect_schema(tmp_path) as connection:
        connection.execute(
            "INSERT INTO command_log(transport, command_text_redacted, stdout_redacted, stderr_redacted) "
            "VALUES ('test', 'safe', 'safe', 'safe')"
        )
        row = connection.execute(
            "SELECT id FROM command_log WHERE transport = 'test'"
        ).fetchone()
        cmd_id: int = row["id"]

        for column, raw_value in [
            ("command_text_redacted", "pwd=raw"),
            ("stdout_redacted", "cookie=raw"),
            ("stderr_redacted", "token=raw"),
        ]:
            with pytest.raises(
                sqlite3.IntegrityError,
                match="command_log contains unredacted secret-like value",
            ):
                connection.execute(
                    f"UPDATE command_log SET {column} = ? WHERE id = ?",
                    (raw_value, cmd_id),
                )
