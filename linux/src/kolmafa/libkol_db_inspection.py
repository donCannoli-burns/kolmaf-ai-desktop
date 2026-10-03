"""Deterministic offline inspector for explicit libkol SQLite databases."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import sqlite3 as _sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from kolmafa.source_catalog import SourceCatalogLoadRow


class _SQLiteModuleProxy:
    """Patch-isolated sqlite3 surface for tests without mutating global sqlite3."""

    connect = staticmethod(_sqlite3.connect)
    DatabaseError = _sqlite3.DatabaseError
    Row = _sqlite3.Row


sqlite3 = _SQLiteModuleProxy()


@dataclass(frozen=True, slots=True)
class LibkolInspectionError:
    """Structured fail-closed inspection error."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class LibkolColumnSummary:
    """SQLite column metadata safe for public output."""

    name: str
    type: str
    primary_key: bool
    not_null: bool


@dataclass(frozen=True, slots=True)
class LibkolIndexSummary:
    """SQLite index metadata safe for public output."""

    name: str
    unique: bool
    origin: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LibkolTableSummary:
    """Deterministic SQLite table summary."""

    name: str
    columns: tuple[LibkolColumnSummary, ...]
    indexes: tuple[LibkolIndexSummary, ...]
    row_count: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class LibkolInspectionResult:
    """Offline read-only libkol DB inspection result."""

    status: str
    summary: dict[str, Any]
    tables: tuple[LibkolTableSummary, ...] = ()
    errors: tuple[LibkolInspectionError, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether inspection succeeded."""

        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-serializable public output."""

        tables = [
            {
                "name": table.name,
                "columns": [asdict(column) for column in table.columns],
                "indexes": [asdict(index) for index in table.indexes],
                "row_count": table.row_count,
                "content_sha256": table.content_sha256,
            }
            for table in self.tables
        ]
        return {
            "ok": self.ok,
            "status": self.status,
            "offline": True,
            "read_only": True,
            "live_kol_mutation": False,
            "dependency_imported": False,
            "summary": self.summary,
            "tables": tables,
            "proposals": _proposal_rows(
                str(self.summary.get("path", "")),
                str(self.summary.get("sha256", "")),
                tables,
            ),
            "errors": [asdict(error) for error in self.errors],
        }


def inspect_database(database_path: Path) -> LibkolInspectionResult:
    """Inspect an explicit SQLite database without importing libkol or writing files."""

    path = Path(database_path)
    public_path = path.name
    if not path.exists():
        return _failure(public_path, "missing", "database path does not exist")
    if not path.is_file():
        return _failure(public_path, "not_file", "database path is not a file")

    file_sha256 = _file_sha256(path)
    try:
        with _connect_read_only(path) as connection:
            if not _is_sqlite_database(connection):
                return _failure(
                    public_path,
                    "not_sqlite",
                    "database path is not a readable SQLite database",
                    file_sha256=file_sha256,
                )
            tables = _table_summaries(connection)
    except sqlite3.DatabaseError:
        return _failure(
            public_path,
            "not_sqlite",
            "database path is not a readable SQLite database",
            file_sha256=file_sha256,
        )

    return LibkolInspectionResult(
        status="ok",
        summary={
            "path": public_path,
            "sha256": file_sha256,
            "table_count": len(tables),
            "row_count": sum(table.row_count for table in tables),
        },
        tables=tuple(tables),
    )


def result_to_json(result: LibkolInspectionResult) -> str:
    """Serialize inspection result deterministically."""

    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def _failure(
    public_path: str,
    code: str,
    message: str,
    *,
    file_sha256: str | None = None,
) -> LibkolInspectionResult:
    summary: dict[str, Any] = {"path": public_path, "table_count": 0, "row_count": 0}
    if file_sha256 is not None:
        summary["sha256"] = file_sha256
    return LibkolInspectionResult(
        status="failed",
        summary=summary,
        errors=(LibkolInspectionError(code=code, message=message),),
    )


def _connect_read_only(database_path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(database_path.resolve()), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _is_sqlite_database(connection: sqlite3.Connection) -> bool:
    connection.execute("PRAGMA schema_version").fetchone()
    return True


def _table_summaries(connection: sqlite3.Connection) -> list[LibkolTableSummary]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [_table_summary(connection, str(row["name"])) for row in rows]


def _table_summary(connection: sqlite3.Connection, table_name: str) -> LibkolTableSummary:
    columns = _column_summaries(connection, table_name)
    return LibkolTableSummary(
        name=table_name,
        columns=tuple(columns),
        indexes=tuple(_index_summaries(connection, table_name)),
        row_count=_table_row_count(connection, table_name),
        content_sha256=_table_content_sha256(connection, table_name, columns),
    )


def _column_summaries(connection: sqlite3.Connection, table_name: str) -> list[LibkolColumnSummary]:
    rows = connection.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    return [
        LibkolColumnSummary(
            name=str(row["name"]),
            type=str(row["type"]),
            primary_key=int(row["pk"]) > 0,
            not_null=bool(row["notnull"]),
        )
        for row in rows
    ]


def _index_summaries(connection: sqlite3.Connection, table_name: str) -> list[LibkolIndexSummary]:
    rows = connection.execute(f"PRAGMA index_list({_quote_identifier(table_name)})").fetchall()
    indexes: list[LibkolIndexSummary] = []
    for row in sorted(rows, key=lambda item: str(item["name"])):
        index_name = str(row["name"])
        column_rows = connection.execute(f"PRAGMA index_info({_quote_identifier(index_name)})").fetchall()
        indexes.append(
            LibkolIndexSummary(
                name=index_name,
                unique=bool(row["unique"]),
                origin=str(row["origin"]),
                columns=tuple(str(column_row["name"]) for column_row in column_rows),
            )
        )
    return indexes


def _table_row_count(connection: sqlite3.Connection, table_name: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {_quote_identifier(table_name)}").fetchone()
    return int(row["count"])


def _table_content_sha256(
    connection: sqlite3.Connection,
    table_name: str,
    columns: list[LibkolColumnSummary],
) -> str:
    if not columns:
        canonical = "[]"
    else:
        select_list = ", ".join(_quote_identifier(column.name) for column in columns)
        order_by = ", ".join(_quote_identifier(column.name) for column in columns)
        rows = connection.execute(
            f"SELECT {select_list} FROM {_quote_identifier(table_name)} ORDER BY {order_by}"
        ).fetchall()
        serializable_rows = [
            {column.name: _json_safe_value(row[column.name]) for column in columns}
            for row in rows
        ]
        canonical = json.dumps(
            serializable_rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _proposal_rows(
    public_path: str,
    input_sha256: str,
    tables: list[dict[str, Any]],
) -> dict[str, Any]:
    source_id = "don-libkol"
    source_content_hash = input_sha256
    provenance = {
        "authority_mutation": False,
        "classification": "proposal/advisory",
        "inspected_database": Path(public_path).name,
        "reference_label": "don-libkol",
        "write_mode": "proposal_only",
    }
    source_catalog = _source_catalog_proposals(
        source_id=source_id,
        input_sha256=input_sha256,
        provenance=provenance,
    )
    source_crosswalk = [
        _source_crosswalk_proposal(
            source_id=source_id,
            source_content_hash=source_content_hash,
            table=table,
            base_provenance=provenance,
        )
        for table in tables
    ]
    return {
        "write_mode": "proposal_only",
        "authority_mutation": False,
        "planned_rows": {
            "source_catalog": len(source_catalog) if public_path else 0,
            "source_crosswalk": len(source_crosswalk),
        },
        "source_catalog": source_catalog if public_path else [],
        "source_crosswalk": source_crosswalk,
    }


def _source_catalog_proposals(
    *,
    source_id: str,
    input_sha256: str,
    provenance: dict[str, object],
) -> list[dict[str, Any]]:
    source_line = "don-libkol|github.com/don/libkol|libkol.db|proposal_only"
    row = SourceCatalogLoadRow(
        source_id=source_id,
        name="don-libkol",
        title="don-libkol archived libkol.db reference",
        category="archived_external_reference",
        reference_kind="github_repository",
        canonical_reference="github.com/don/libkol#libkol.db",
        stack_language="Python/SQLite",
        trust="archived_reference_unverified",
        provenance={
            **provenance,
            "artifact": "inspect-libkol-db",
            "category": "archived_external_reference",
            "reference_kind": "github_repository",
        },
        input_sha256=input_sha256,
        source_line_sha256=hashlib.sha256(source_line.encode("utf-8")).hexdigest(),
        source_line_number=0,
        local_only=True,
        publishability="local_reference_redacted",
        recommendation="inspect_offline_only_before_authority_import",
    )
    return [row.to_public_dict()]


def _source_crosswalk_proposal(
    *,
    source_id: str,
    source_content_hash: str,
    table: dict[str, Any],
    base_provenance: dict[str, object],
) -> dict[str, Any]:
    graph_category = "KNOWLEDGE_BASE"
    graph_node_key = f"libkol.table.{table['name']}"
    relationship = "summarizes_table"
    evidence_content_hash = str(table["content_sha256"])
    return {
        "crosswalk_id": f"{source_id}:{graph_category}:{graph_node_key}:{relationship}",
        "source_id": source_id,
        "source_content_hash": source_content_hash,
        "graph_category": graph_category,
        "graph_node_key": graph_node_key,
        "relationship": relationship,
        "confidence": "proposal_advisory",
        "evidence_content_hash": evidence_content_hash,
        "provenance": {
            **base_provenance,
            "artifact": "inspect-libkol-db",
            "evidence_table": table["name"],
            "evidence_row_count": table["row_count"],
            "evidence_content_hash": evidence_content_hash,
        },
    }
