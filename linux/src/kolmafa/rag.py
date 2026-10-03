"""Local SQLite FTS5 RAG helpers."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
from pathlib import Path
import sqlite3

from kolmafa.redaction import has_unredacted_secret, redact_text


TEXT_SUFFIXES = {".ash", ".cli", ".css", ".html", ".js", ".json", ".md", ".sql", ".txt", ".ts"}
_PRIVATE_PATH_MARKERS = frozenset(
    {
        ".cookies",
        ".secrets",
        "cookies",
        "credentials",
        "credential-store",
        "private-logs",
        "session-logs",
        "logs",
        "secrets",
        "tokens",
    }
)
_PRIVATE_FILE_SUFFIXES = frozenset({".cookie", ".cookies", ".key", ".log", ".pem"})


class RagIngestionRefused(ValueError):
    """Raised when a source fails the RAG corpus security policy."""


def iter_text_files(paths: Iterable[Path]) -> Iterable[Path]:
    """Yield text-like files from files or directories."""

    for path in paths:
        if path.is_dir():
            yield from (child for child in path.rglob("*") if child.is_file() and child.suffix in TEXT_SUFFIXES)
        elif path.is_file() and path.suffix in TEXT_SUFFIXES:
            yield path


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    """Return whether a SQLite table or virtual table exists."""

    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual') AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _resolve_roots(allowed_roots: Iterable[Path] | None) -> list[Path]:
    """Resolve allowlisted corpus roots."""

    return [root.resolve() for root in (allowed_roots or [])]


def _is_under_allowed_root(path: Path, allowed_roots: list[Path]) -> bool:
    """Return whether path is contained by an allowlisted root."""

    resolved = path.resolve()
    return any(resolved == root or resolved.is_relative_to(root) for root in allowed_roots)


def _looks_private(path: Path) -> bool:
    """Return whether a path is a private log, credential, cookie, or key source."""

    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & _PRIVATE_PATH_MARKERS) or path.suffix.lower() in _PRIVATE_FILE_SUFFIXES


def _validate_source_path(path: Path, allowed_roots: list[Path]) -> bool:
    """Validate a source path before traversal or ingestion. Return False to skip."""

    if not _is_under_allowed_root(path, allowed_roots):
        print(f"rag_warning: skipping {path} (outside allowlist)")
        return False
    if _looks_private(path):
        print(f"rag_warning: skipping {path} (private path)")
        return False
    return True


def _iter_allowed_text_files(paths: Iterable[Path], allowed_roots: list[Path]) -> Iterable[Path]:
    """Yield text files only after source allowlist/private-source checks."""

    for path in paths:
        if not _validate_source_path(path, allowed_roots):
            continue
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    if _validate_source_path(child, allowed_roots) and child.suffix in TEXT_SUFFIXES:
                        yield child
        elif path.is_file() and path.suffix in TEXT_SUFFIXES:
            yield path


def _hash_text(text: str) -> str:
    """Return a SHA-256 hex digest for text."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _insert_chunk(connection: sqlite3.Connection, document_id: str, text: str) -> None:
    """Insert a single deduped redacted document chunk."""

    text_hash = _hash_text(text)
    if connection.execute("SELECT 1 FROM document_chunks WHERE text_hash = ?", (text_hash,)).fetchone():
        return
    chunk_id = _hash_text(f"chunk\0{text_hash}")
    connection.execute(
        """
        INSERT INTO document_chunks(
            chunk_id, document_id, chunk_index, text_redacted, text_hash,
            token_count, source_offset_start, source_offset_end
        ) VALUES (?, ?, 0, ?, ?, ?, 0, ?)
        """,
        (chunk_id, document_id, text, text_hash, len(text.split()), len(text)),
    )


def ingest_paths(
    connection: sqlite3.Connection,
    paths: Iterable[Path],
    *,
    explicit_opt_in: bool = False,
    allowed_roots: Iterable[Path] | None = None,
    source_id: str = "local-file",
    source_label: str = "Local file",
    version_label: str = "v1",
    ingestion_reason: str = "operator_requested",
    redaction_status: str = "redacted",
    retention_class: str = "standard",
    quality_class: str = "unknown",
) -> int:
    """Ingest explicitly opted-in, allowlisted, redacted text documents into SQLite/FTS5."""

    path_list = list(paths)
    if not explicit_opt_in:
        raise RagIngestionRefused("RAG corpus ingestion requires explicit opt-in")
    if redaction_status != "redacted":
        raise RagIngestionRefused("RAG sources must have redacted redaction_status before ingestion")

    allowed = _resolve_roots(allowed_roots)
    if not allowed:
        raise RagIngestionRefused("RAG source allowlist must contain at least one root")

    count = 0
    for path in _iter_allowed_text_files(path_list, allowed):
        body = path.read_text(encoding="utf-8", errors="replace")
        if has_unredacted_secret(body):
            print(f"rag_warning: skipping {path} (unredacted secret-like content)")
            continue
        body_redacted = redact_text(body)
        body_hash = _hash_text(body_redacted)
        document_id = _hash_text(f"{path.resolve()}\0{body_hash}")
        cursor = connection.execute(
            """
            INSERT INTO documents(
                document_id, source_id, source_label, source_uri_label, source_path,
                title, body_redacted, body_hash, version_label, ingestion_reason,
                redaction_status, retention_class, quality_class
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO NOTHING
            """,
            (
                document_id,
                source_id,
                source_label,
                str(path),
                str(path),
                path.name,
                body_redacted,
                body_hash,
                version_label,
                ingestion_reason,
                redaction_status,
                retention_class,
                quality_class,
            ),
        )
        if cursor.rowcount:
            _insert_chunk(connection, document_id, body_redacted)
            count += 1
    connection.commit()
    return count


def _is_safe_search_fallback_error(error: sqlite3.OperationalError) -> bool:
    """Return whether an OperationalError is an expected FTS/no-corpus fallback."""

    message = str(error).lower()
    return (
        "no such table: documents_fts" in message
        or "no such module: fts5" in message
        or "no such module: sqlite_vec" in message
        or "fts5: syntax error" in message
        or "malformed match" in message
        or "unterminated string" in message
    )


def search(
    connection: sqlite3.Connection,
    query: str | None,
    limit: int = 10,
    *,
    source_ids: Iterable[str] | None = None,
) -> list[sqlite3.Row]:
    """Search ingested redacted documents with FTS5 and provenance-only authority."""

    if not isinstance(query, str) or not query.strip():
        return []

    if not _table_exists(connection, "documents_fts") or not _table_exists(connection, "documents"):
        return []

    source_list = list(source_ids or [])
    source_filter = ""
    params: list[object] = [query.strip()]
    if source_list:
        placeholders = ", ".join("?" for _ in source_list)
        source_filter = f"AND documents.source_id IN ({placeholders})"
        params.extend(source_list)
    params.append(limit)

    try:
        return list(
            connection.execute(
            """
            SELECT
                documents_fts.rowid,
                documents.title,
                documents.source_path,
                documents.document_id,
                documents.source_id,
                documents.source_label,
                documents.source_uri_label,
                documents.version_label,
                documents.ingestion_reason,
                documents.redaction_status,
                documents.retention_class,
                documents.quality_class,
                (
                    SELECT document_chunks.chunk_id
                    FROM document_chunks
                    WHERE document_chunks.document_id = documents.document_id
                    ORDER BY document_chunks.chunk_index
                    LIMIT 1
                ) AS chunk_id,
                snippet(documents_fts, 1, '[', ']', ' ... ', 20) AS snippet,
                bm25(documents_fts) AS score,
                0 AS permission_authority
            FROM documents_fts
            JOIN documents ON documents.id = documents_fts.rowid
            WHERE documents_fts MATCH ?
              AND documents.deleted_at IS NULL
              AND documents.redaction_status = 'redacted'
              {source_filter}
            ORDER BY bm25(documents_fts)
            LIMIT ?
            """.format(source_filter=source_filter),
            params,
            )
        )
    except sqlite3.OperationalError as exc:
        if _is_safe_search_fallback_error(exc):
            return []
        raise
