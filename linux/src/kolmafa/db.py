"""SQLite persistence helpers."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from kolmafa.redaction import redact_text


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    """Return whether a table or virtual table exists."""

    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual') AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    """Return column names for a SQLite table."""

    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})")}


def _prepare_legacy_tables(connection: sqlite3.Connection) -> None:
    """Move pre-v1 tables aside so schema.sql can create v1 contract tables."""

    if _table_exists(connection, "documents") and "document_id" not in _columns(
        connection, "documents"
    ):
        connection.executescript(
            """
            DROP TRIGGER IF EXISTS documents_ai;
            DROP TRIGGER IF EXISTS documents_ad;
            DROP TRIGGER IF EXISTS documents_au;
            DROP TABLE IF EXISTS documents_fts;
            ALTER TABLE documents RENAME TO documents_legacy_v0;
            """
        )

    if _table_exists(connection, "command_log") and "command_log_id" not in _columns(
        connection, "command_log"
    ):
        connection.execute("ALTER TABLE command_log RENAME TO command_log_legacy_v0")
    elif _table_exists(connection, "command_log"):
        _ensure_existing_command_log_columns(connection)


def _ensure_existing_command_log_columns(connection: sqlite3.Connection) -> None:
    """Add nullable v1 audit columns needed before schema indexes/triggers run."""

    columns = _columns(connection, "command_log")
    additions = {
        "session_id": "ALTER TABLE command_log ADD COLUMN session_id TEXT",
        "task_id": "ALTER TABLE command_log ADD COLUMN task_id TEXT",
        "command_class": "ALTER TABLE command_log ADD COLUMN command_class TEXT NOT NULL DEFAULT 'unknown'",
        "command_text_redacted": "ALTER TABLE command_log ADD COLUMN command_text_redacted TEXT",
        "command_hash": "ALTER TABLE command_log ADD COLUMN command_hash TEXT",
        "arguments_redacted_json": "ALTER TABLE command_log ADD COLUMN arguments_redacted_json TEXT NOT NULL DEFAULT '{}'",
        "allowlist_id": "ALTER TABLE command_log ADD COLUMN allowlist_id TEXT",
        "confirmation_id": "ALTER TABLE command_log ADD COLUMN confirmation_id TEXT",
        "policy_decision_id": "ALTER TABLE command_log ADD COLUMN policy_decision_id TEXT",
        "return_code": "ALTER TABLE command_log ADD COLUMN return_code INTEGER",
        "stdout_redacted": "ALTER TABLE command_log ADD COLUMN stdout_redacted TEXT",
        "stdout_hash": "ALTER TABLE command_log ADD COLUMN stdout_hash TEXT",
        "stderr_redacted": "ALTER TABLE command_log ADD COLUMN stderr_redacted TEXT",
        "stderr_hash": "ALTER TABLE command_log ADD COLUMN stderr_hash TEXT",
    }
    for column, statement in additions.items():
        if column not in columns:
            connection.execute(statement)


def _copy_legacy_rows(connection: sqlite3.Connection) -> None:
    """Copy rows from pre-v1 tables into the v1 schema, then remove staging tables."""

    if _table_exists(connection, "documents_legacy_v0"):
        rows = connection.execute(
            "SELECT id, source_path, title, body, created_at FROM documents_legacy_v0 ORDER BY id"
        ).fetchall()
        for row in rows:
            body = redact_text(row["body"])
            body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            document_id = hashlib.sha256(
                f"legacy\0{row['id']}\0{row['source_path']}\0{body_hash}".encode("utf-8")
            ).hexdigest()
            connection.execute(
                """
                INSERT OR IGNORE INTO documents(
                    id, document_id, source_id, source_label, source_uri_label, source_path,
                    title, body_redacted, body_hash, created_at, updated_at, quality_class
                ) VALUES (?, ?, 'legacy-local-file', ?, ?, ?, ?, ?, ?, ?, ?, 'unknown')
                """,
                (
                    row["id"],
                    document_id,
                    row["title"],
                    row["source_path"],
                    row["source_path"],
                    row["title"],
                    body,
                    body_hash,
                    row["created_at"],
                    row["created_at"],
                ),
            )
        connection.execute("DROP TABLE documents_legacy_v0")

    if _table_exists(connection, "command_log_legacy_v0"):
        rows = connection.execute(
            "SELECT id, command, transport, return_code, stdout, stderr, created_at FROM command_log_legacy_v0 ORDER BY id"
        ).fetchall()
        for row in rows:
            command_log_id = hashlib.sha256(f"legacy-command\0{row['id']}".encode("utf-8")).hexdigest()
            connection.execute(
                """
                INSERT OR IGNORE INTO command_log(
                    id, command_log_id, transport, command_class,
                    command_text_redacted, command_hash, return_code,
                    stdout_redacted, stdout_hash, stderr_redacted, stderr_hash, created_at
                ) VALUES (?, ?, ?, 'unknown', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    command_log_id,
                    row["transport"],
                    redact_text(row["command"]),
                    _hash_redacted(redact_text(row["command"])),
                    row["return_code"],
                    redact_text(row["stdout"] or ""),
                    _hash_redacted(redact_text(row["stdout"] or "")),
                    redact_text(row["stderr"] or ""),
                    _hash_redacted(redact_text(row["stderr"] or "")),
                    row["created_at"],
                ),
            )
        connection.execute("DROP TABLE command_log_legacy_v0")


def _ensure_session_events_columns(connection: sqlite3.Connection) -> None:
    """Add v1 session event observer columns to existing databases."""

    if not _table_exists(connection, "session_events"):
        return

    columns = _columns(connection, "session_events")
    additions = {
        "event_id": "ALTER TABLE session_events ADD COLUMN event_id TEXT",
        "message_redacted": "ALTER TABLE session_events ADD COLUMN message_redacted TEXT",
        "message_hash": "ALTER TABLE session_events ADD COLUMN message_hash TEXT",
        "source_surface": (
            "ALTER TABLE session_events ADD COLUMN source_surface TEXT "
            "NOT NULL DEFAULT 'kolmafia-session-log'"
        ),
        "provenance_json": "ALTER TABLE session_events ADD COLUMN provenance_json TEXT NOT NULL DEFAULT '{}'",
    }
    for column, statement in additions.items():
        if column not in columns:
            connection.execute(statement)

    connection.execute("UPDATE session_events SET event_id = lower(hex(randomblob(16))) WHERE event_id IS NULL")
    if "line" in columns:
        for row in connection.execute("SELECT id, line FROM session_events WHERE message_redacted IS NULL").fetchall():
            connection.execute(
                "UPDATE session_events SET message_redacted = ? WHERE id = ?",
                (redact_text(row["line"]), row["id"]),
            )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_session_events_event_id ON session_events(event_id)"
    )


def _ensure_session_listener_cursors_table(connection: sqlite3.Connection) -> None:
    """Create durable session listener cursor state for existing databases."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS session_listener_cursors (
            cursor_id TEXT PRIMARY KEY,
            player_name TEXT NOT NULL,
            source_path TEXT NOT NULL,
            file_device INTEGER,
            file_inode INTEGER,
            file_mtime_ns INTEGER,
            byte_offset INTEGER NOT NULL DEFAULT 0 CHECK (byte_offset >= 0),
            file_size INTEGER NOT NULL DEFAULT 0 CHECK (file_size >= 0),
            rotation_state TEXT NOT NULL DEFAULT 'initialized' CHECK (rotation_state IN ('initialized', 'steady', 'missing', 'rotated', 'truncated')),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (player_name, source_path)
        );
        CREATE INDEX IF NOT EXISTS idx_session_listener_cursors_player
        ON session_listener_cursors(player_name, updated_at);
        """
    )
    if "file_mtime_ns" not in _columns(connection, "session_listener_cursors"):
        connection.execute("ALTER TABLE session_listener_cursors ADD COLUMN file_mtime_ns INTEGER")


def _ensure_documents_columns(connection: sqlite3.Connection) -> None:
    """Add quality_class column to existing documents tables."""

    if not _table_exists(connection, "documents"):
        return
    if "quality_class" not in _columns(connection, "documents"):
        connection.execute(
            "ALTER TABLE documents ADD COLUMN quality_class TEXT NOT NULL DEFAULT 'unknown'"
        )


def _ensure_source_catalog_columns(connection: sqlite3.Connection) -> None:
    """Add source catalog load/provenance columns to existing databases."""

    if _table_exists(connection, "source_catalog"):
        columns = _columns(connection, "source_catalog")
        additions = {
            "source_load_status": (
                "ALTER TABLE source_catalog ADD COLUMN source_load_status TEXT "
                "NOT NULL DEFAULT 'declared' CHECK (source_load_status IN "
                "('declared', 'loaded', 'conflict', 'rejected'))"
            ),
            "load_manifest_id": "ALTER TABLE source_catalog ADD COLUMN load_manifest_id TEXT NOT NULL DEFAULT ''",
            "source_version": "ALTER TABLE source_catalog ADD COLUMN source_version TEXT NOT NULL DEFAULT ''",
            "source_content_hash": "ALTER TABLE source_catalog ADD COLUMN source_content_hash TEXT NOT NULL DEFAULT ''",
            "source_metadata_hash": "ALTER TABLE source_catalog ADD COLUMN source_metadata_hash TEXT NOT NULL DEFAULT ''",
        }
        for column, statement in additions.items():
            if column not in columns:
                connection.execute(statement)

    if _table_exists(connection, "source_crosswalk"):
        columns = _columns(connection, "source_crosswalk")
        additions = {
            "source_content_hash": "ALTER TABLE source_crosswalk ADD COLUMN source_content_hash TEXT NOT NULL DEFAULT ''",
            "evidence_content_hash": "ALTER TABLE source_crosswalk ADD COLUMN evidence_content_hash TEXT NOT NULL DEFAULT ''",
        }
        for column, statement in additions.items():
            if column not in columns:
                connection.execute(statement)


def _drop_column_if_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> None:
    """Drop an internal legacy column when SQLite supports the operation."""

    if column_name in _columns(connection, table_name):
        connection.execute(f"ALTER TABLE {table_name} DROP COLUMN {column_name}")


def _harden_raw_persistence_surfaces(connection: sqlite3.Connection) -> None:
    """Remove legacy raw command/session/document columns from existing v1 databases."""

    if _table_exists(connection, "command_log"):
        columns = _columns(connection, "command_log")
        additions = {
            "command_hash": "ALTER TABLE command_log ADD COLUMN command_hash TEXT",
            "stdout_hash": "ALTER TABLE command_log ADD COLUMN stdout_hash TEXT",
        "stderr_hash": "ALTER TABLE command_log ADD COLUMN stderr_hash TEXT",
        "result_marker_json": "ALTER TABLE command_log ADD COLUMN result_marker_json TEXT NOT NULL DEFAULT '{}'",

        }
        for column, statement in additions.items():
            if column not in columns:
                connection.execute(statement)
        refreshed_columns = _columns(connection, "command_log")
        has_raw_command = "command" in refreshed_columns
        has_raw_stdout = "stdout" in refreshed_columns
        has_raw_stderr = "stderr" in refreshed_columns
        selected_columns = ["id", "command_text_redacted", "stdout_redacted", "stderr_redacted"]
        if has_raw_command:
            selected_columns.append("command")
        if has_raw_stdout:
            selected_columns.append("stdout")
        if has_raw_stderr:
            selected_columns.append("stderr")
        for row in connection.execute(f"SELECT {', '.join(selected_columns)} FROM command_log").fetchall():
            command_redacted = redact_text(
                row["command_text_redacted"] if row["command_text_redacted"] is not None else row["command"] if has_raw_command else ""
            )
            stdout_redacted = redact_text(
                row["stdout_redacted"] if row["stdout_redacted"] is not None else row["stdout"] if has_raw_stdout else ""
            )
            stderr_redacted = redact_text(
                row["stderr_redacted"] if row["stderr_redacted"] is not None else row["stderr"] if has_raw_stderr else ""
            )
            connection.execute(
                "UPDATE command_log SET command_text_redacted = ?, command_hash = ?, "
                "stdout_redacted = ?, stdout_hash = ?, stderr_redacted = ?, stderr_hash = ? WHERE id = ?",
                (
                    command_redacted,
                    _hash_redacted(command_redacted),
                    stdout_redacted,
                    _hash_redacted(stdout_redacted),
                    stderr_redacted,
                    _hash_redacted(stderr_redacted),
                    row["id"],
                ),
            )
        for column in ("command", "stdout", "stderr"):
            _drop_column_if_exists(connection, "command_log", column)

    if _table_exists(connection, "session_events"):
        if "message_hash" not in _columns(connection, "session_events"):
            connection.execute("ALTER TABLE session_events ADD COLUMN message_hash TEXT")
        for row in connection.execute("SELECT id, message_redacted FROM session_events").fetchall():
            message_redacted = redact_text(row["message_redacted"] or "")
            connection.execute(
                "UPDATE session_events SET message_redacted = ?, message_hash = ? WHERE id = ?",
                (message_redacted, _hash_redacted(message_redacted), row["id"]),
            )
        _drop_column_if_exists(connection, "session_events", "line")

    if _table_exists(connection, "documents"):
        connection.executescript(
            """
            DROP TRIGGER IF EXISTS documents_ai;
            DROP TRIGGER IF EXISTS documents_ad;
            DROP TRIGGER IF EXISTS documents_au;
            DROP TABLE IF EXISTS documents_fts;
            """
        )
        _drop_column_if_exists(connection, "documents", "body")


def _rebuild_documents_fts(connection: sqlite3.Connection) -> None:
    """Populate FTS from redacted document text after schema creation/migration."""

    if not (_table_exists(connection, "documents") and _table_exists(connection, "documents_fts")):
        return
    connection.execute("DELETE FROM documents_fts")
    connection.execute(
        """
        INSERT INTO documents_fts(rowid, title, body, source_path, document_id)
        SELECT id, title, body_redacted, source_path, document_id
        FROM documents
        WHERE deleted_at IS NULL
        """
    )


def _hash_redacted(value: str | None) -> str | None:
    """Hash already-redacted persistence text for review correlation."""

    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def connect(database_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with pragmatic defaults."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_database(database_path: Path) -> None:
    """Initialize database schema."""

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = connect(database_path)
    try:
        _prepare_legacy_tables(connection)
        _ensure_source_catalog_columns(connection)
        connection.executescript(schema)
        _ensure_session_events_columns(connection)
        _ensure_session_listener_cursors_table(connection)
        _ensure_documents_columns(connection)
        _ensure_source_catalog_columns(connection)
        _copy_legacy_rows(connection)
        _harden_raw_persistence_surfaces(connection)
        connection.executescript(schema)
        _ensure_session_events_columns(connection)
        _ensure_session_listener_cursors_table(connection)
        _ensure_documents_columns(connection)
        _ensure_source_catalog_columns(connection)
        _rebuild_documents_fts(connection)
    finally:
        # Close explicitly: a leaked read-write connection keeps the WAL
        # uncheckpointed and a later garbage-collection-time close rewrites the
        # main database file header nondeterministically.
        connection.close()
