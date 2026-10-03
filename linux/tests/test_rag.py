import sqlite3
from pathlib import Path

import pytest

from kolmafa import rag


def _connection(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript((Path(__file__).parents[1] / "sql" / "schema.sql").read_text())
    return connection


def test_ingest_and_search_allowed_opt_in_source(tmp_path) -> None:
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    doc = corpus / "note.md"
    doc.write_text("relay nobrowser starts the relay server", encoding="utf-8")

    assert rag.ingest_paths(
        connection,
        [doc],
        explicit_opt_in=True,
        allowed_roots=[corpus],
        source_id="docs",
        source_label="Operator docs",
        ingestion_reason="operator selected fixture",
        retention_class="standard",
        redaction_status="redacted",
    ) == 1
    rows = rag.search(connection, "relay", source_ids=["docs"])

    assert rows[0]["title"] == "note.md"
    assert rows[0]["document_id"]
    assert rows[0]["source_id"] == "docs"
    assert rows[0]["source_label"] == "Operator docs"
    assert rows[0]["redaction_status"] == "redacted"
    assert rows[0]["retention_class"] == "standard"
    assert rows[0]["permission_authority"] == 0


def test_ingest_refuses_without_explicit_opt_in(tmp_path) -> None:
    connection = _connection(tmp_path)
    doc = tmp_path / "note.md"
    doc.write_text("safe public note", encoding="utf-8")

    with pytest.raises(rag.RagIngestionRefused, match="explicit opt-in"):
        rag.ingest_paths(connection, [doc], allowed_roots=[tmp_path])


def test_ingest_refuses_unknown_directory_and_private_sources(tmp_path) -> None:
    connection = _connection(tmp_path)
    allowed = tmp_path / "allowed"
    private = tmp_path / "private-logs"
    allowed.mkdir()
    private.mkdir()
    unknown_doc = tmp_path / "outside.md"
    private_doc = private / "session.log"
    unknown_doc.write_text("outside corpus", encoding="utf-8")
    private_doc.write_text("private relay log", encoding="utf-8")

    # Outside-allowlist and private paths are now skipped with a warning
    count = rag.ingest_paths(connection, [unknown_doc], explicit_opt_in=True, allowed_roots=[allowed])
    assert count == 0

    count = rag.ingest_paths(connection, [private_doc], explicit_opt_in=True, allowed_roots=[private])
    assert count == 0


def test_ingest_refuses_unredacted_status_and_secret_like_content(tmp_path) -> None:
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    doc = corpus / "secrets.md"
    doc.write_text("relay pwd=unsafe", encoding="utf-8")

    with pytest.raises(rag.RagIngestionRefused, match="redacted"):
        rag.ingest_paths(
            connection,
            [doc],
            explicit_opt_in=True,
            allowed_roots=[corpus],
            redaction_status="unredacted",
        )

    # Secret-like content is now skipped with a warning instead of raising
    count = rag.ingest_paths(connection, [doc], explicit_opt_in=True, allowed_roots=[corpus])
    assert count == 0


def test_ingest_stores_chunk_provenance_and_dedupes_chunks(tmp_path) -> None:
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("same chunk text", encoding="utf-8")
    (corpus / "b.md").write_text("same chunk text", encoding="utf-8")

    assert rag.ingest_paths(connection, [corpus], explicit_opt_in=True, allowed_roots=[corpus]) == 2

    chunks = connection.execute("SELECT * FROM document_chunks").fetchall()
    assert len(chunks) == 1
    assert chunks[0]["text_hash"]
    assert chunks[0]["source_offset_start"] == 0
    assert chunks[0]["source_offset_end"] == len("same chunk text")


def test_search_fallbacks_to_no_corpus_when_fts_missing(tmp_path) -> None:
    connection = sqlite3.connect(tmp_path / "empty.db")
    connection.row_factory = sqlite3.Row

    assert rag.search(connection, "relay") == []


@pytest.mark.parametrize("query", ["", None, "relay OR", '"relay'])
def test_search_fails_closed_for_empty_or_malformed_queries(tmp_path, query) -> None:
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    doc = corpus / "note.md"
    doc.write_text("relay nobrowser starts the relay server", encoding="utf-8")
    rag.ingest_paths(connection, [doc], explicit_opt_in=True, allowed_roots=[corpus])

    assert rag.search(connection, query) == []


def test_search_does_not_hide_unrelated_database_errors(tmp_path) -> None:
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    doc = corpus / "note.md"
    doc.write_text("relay nobrowser starts the relay server", encoding="utf-8")
    rag.ingest_paths(connection, [doc], explicit_opt_in=True, allowed_roots=[corpus])
    connection.execute("DROP TABLE document_chunks")

    with pytest.raises(sqlite3.OperationalError, match="document_chunks"):
        rag.search(connection, "relay")
