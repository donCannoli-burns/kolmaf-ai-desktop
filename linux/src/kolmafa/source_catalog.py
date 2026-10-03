"""Deterministic offline parser for KOL_Master source catalog dumps."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import unquote

from kolmafa import db


PRIVATE_LOCAL_START_LINE = 95
_CATEGORY_RE = re.compile(r"^-{3}([A-Za-z0-9/_ -]+)-{2,}$")
_GITHUB_RE = re.compile(r"\bg-h/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")
_PATH_RE = re.compile(r"^\s*PATH\s+(?:-+\s*)?(?P<path>.+?)\s*$", re.IGNORECASE)
_URL_RE = re.compile(r"\b((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}[^\s,)]*/[^\s,)]*)")


@dataclass(frozen=True, slots=True)
class SourceCatalogError:
    """Structured source dump validation error."""

    line_number: int | None
    message: str


@dataclass(frozen=True, slots=True)
class SourceCatalogRecord:
    """Parsed source dump row with internal raw reference retained."""

    source_id: str
    line_number: int
    category: str
    reference_kind: str
    canonical_reference: str
    raw_reference: str
    name: str
    title: str
    stack_language: str
    trust: str
    source_line_sha256: str
    provenance: dict[str, object]
    local_only: bool
    publishability: str
    recommendation: str

    def to_public_dict(self) -> dict[str, Any]:
        """Return redaction-safe deterministic public record data."""

        data = asdict(self)
        if self.local_only:
            data["canonical_reference"] = "[redacted-local-path]"
            data["raw_reference"] = "[redacted-local-path]"
            data["provenance"] = {
                "artifact": self.provenance["artifact"],
                "line_number": self.line_number,
                "category": self.category,
                "reference_summary": "local-path-redacted",
            }
        return data


@dataclass(frozen=True, slots=True)
class SourceCatalogLoadRow:
    """Load-ready source_catalog row with no raw local path material."""

    source_id: str
    name: str
    title: str
    category: str
    reference_kind: str
    canonical_reference: str
    stack_language: str
    trust: str
    provenance: dict[str, object]
    input_sha256: str
    source_line_sha256: str
    source_line_number: int
    local_only: bool
    publishability: str
    recommendation: str

    def to_public_dict(self) -> dict[str, Any]:
        """Return deterministic public row data suitable for JSON serialization."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceCrosswalkLoadRow:
    """Load-ready source_crosswalk row from an offline normalized proposal."""

    crosswalk_id: str
    source_id: str
    source_content_hash: str
    graph_category: str
    graph_node_key: str
    relationship: str
    confidence: str
    evidence_content_hash: str
    provenance: dict[str, object]

    def to_public_dict(self) -> dict[str, Any]:
        """Return deterministic public row data suitable for JSON serialization."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceCatalogLoadError:
    """Structured fail-closed source catalog load error."""

    artifact: str
    row_id: str | None
    message: str


@dataclass(frozen=True, slots=True)
class SourceCatalogLoadResult:
    """Transactional offline source catalog load result."""

    status: str
    mode: str
    inserted: int = 0
    unchanged: int = 0
    conflicts: int = 0
    source_catalog_rows: int = 0
    source_crosswalk_rows: int = 0
    manifest_id: str = ""
    artifacts: tuple[dict[str, Any], ...] = ()
    errors: tuple[SourceCatalogLoadError, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether the offline load succeeded."""

        return self.status == "ok"

    def to_public_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-serializable public load data."""

        return {
            "status": self.status,
            "mode": self.mode,
            "counts": {
                "inserted": self.inserted,
                "unchanged": self.unchanged,
                "conflicts": self.conflicts,
                "source_catalog": self.source_catalog_rows,
                "source_crosswalk": self.source_crosswalk_rows,
            },
            "manifest_id": self.manifest_id,
            "artifacts": list(self.artifacts),
            "errors": [asdict(error) for error in self.errors],
            "offline": True,
            "live_kol_mutation": False,
        }


@dataclass(frozen=True, slots=True)
class SourceCatalogSummary:
    """Deterministic summary of one source dump artifact."""

    path: str
    sha256: str
    line_count: int
    row_count: int
    category_counts: dict[str, int]
    local_only_count: int

    def to_public_dict(self) -> dict[str, Any]:
        """Return redaction-safe deterministic public summary data."""

        data = asdict(self)
        if self.path != "<memory>":
            data["path"] = Path(self.path).name
        return data


@dataclass(frozen=True, slots=True)
class SourceCatalogValidationResult:
    """Read-only source catalog validation result."""

    ok: bool
    summary: SourceCatalogSummary
    records: tuple[SourceCatalogRecord, ...] = ()
    errors: tuple[SourceCatalogError, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        """Return redaction-safe deterministic JSON-serializable data."""

        return {
            "ok": self.ok,
            "summary": self.summary.to_public_dict(),
            "records": [record.to_public_dict() for record in self.records],
            "errors": [asdict(error) for error in self.errors],
            "offline": True,
            "live_kol_mutation": False,
        }


def parse_source_dump_file(path: Path) -> tuple[SourceCatalogRecord, ...]:
    """Parse a source dump file without network or persistence side effects."""

    return parse_source_dump_text(path.read_text(encoding="utf-8"))


def parse_source_dump_text(text: str) -> tuple[SourceCatalogRecord, ...]:
    """Parse source dump text and raise ValueError on malformed rows."""

    records, errors = _parse_source_dump_text(text)
    if errors:
        first = errors[0]
        raise ValueError(f"line {first.line_number}: {first.message}")
    return records


def normalized_load_rows_from_file(path: Path) -> tuple[SourceCatalogLoadRow, ...]:
    """Parse a dump file into source_catalog insertion rows without side effects."""

    return normalized_load_rows_from_text(path.read_text(encoding="utf-8"), path=path)


def normalized_load_rows_from_text(
    text: str,
    *,
    path: Path | None = None,
) -> tuple[SourceCatalogLoadRow, ...]:
    """Parse source dump text into deterministic load-ready source_catalog rows.

    Raises:
        ValueError: If parsing finds malformed, duplicate, or conflicting rows.
    """

    result = validate_source_dump_text(text, path=path)
    if not result.ok:
        first = result.errors[0]
        line = "" if first.line_number is None else f"line {first.line_number}: "
        raise ValueError(f"{line}{first.message}")
    return tuple(_load_row_from_record(record, result.summary.sha256) for record in result.records)


def validate_source_dump_file(path: Path) -> SourceCatalogValidationResult:
    """Validate a source dump file without fetching or persisting source rows."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return SourceCatalogValidationResult(
            ok=False,
            summary=SourceCatalogSummary(
                path=str(path),
                sha256="",
                line_count=0,
                row_count=0,
                category_counts={},
                local_only_count=0,
            ),
            errors=(SourceCatalogError(None, f"unable to read source dump: {exc.strerror}"),),
        )
    return validate_source_dump_text(text, path=path)


def result_to_json(result: SourceCatalogValidationResult) -> str:
    """Return deterministic redaction-safe JSON for a validation result."""

    return json.dumps(result.to_public_dict(), sort_keys=True, separators=(",", ":"))


def load_result_to_json(result: SourceCatalogLoadResult) -> str:
    """Return deterministic redaction-safe JSON for a load result."""

    return json.dumps(result.to_public_dict(), sort_keys=True, separators=(",", ":"))


def load_source_catalog_rows(
    database_path: Path,
    *,
    source_dump_paths: tuple[Path, ...] = (),
    libkol_inspection_json_paths: tuple[Path, ...] = (),
) -> SourceCatalogLoadResult:
    """Load normalized source catalog/crosswalk rows into explicit SQLite DB.

    This is an explicit, offline-only, transactional load path. It reads only the
    supplied artifacts and writes only source_catalog/source_crosswalk rows in the
    supplied SQLite database. Any conflict fails closed before partial writes are
    committed.
    """

    if not source_dump_paths and not libkol_inspection_json_paths:
        return SourceCatalogLoadResult(
            status="failed",
            mode="merge",
            errors=(SourceCatalogLoadError("<none>", None, "at least one explicit source input is required"),),
        )

    source_rows: list[SourceCatalogLoadRow] = []
    crosswalk_rows: list[SourceCrosswalkLoadRow] = []
    artifacts: list[dict[str, Any]] = []
    errors: list[SourceCatalogLoadError] = []

    for path in source_dump_paths:
        try:
            rows = normalized_load_rows_from_file(path)
        except OSError as exc:
            errors.append(SourceCatalogLoadError(path.name, None, _load_os_error_message("source dump", exc)))
            continue
        except ValueError as exc:
            errors.append(SourceCatalogLoadError(path.name, None, str(exc)))
            continue
        source_rows.extend(rows)
        artifacts.append(_artifact_summary(path, "source_dump", len(rows)))

    for path in libkol_inspection_json_paths:
        try:
            parsed_source_rows, parsed_crosswalk_rows = _load_rows_from_libkol_inspection_json(path)
        except OSError as exc:
            errors.append(SourceCatalogLoadError(path.name, None, _load_os_error_message("libkol inspection JSON", exc)))
            continue
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(SourceCatalogLoadError(path.name, None, str(exc)))
            continue
        source_rows.extend(parsed_source_rows)
        crosswalk_rows.extend(parsed_crosswalk_rows)
        artifacts.append(
            _artifact_summary(
                path,
                "libkol_inspection_json",
                len(parsed_source_rows) + len(parsed_crosswalk_rows),
            )
        )

    errors.extend(_duplicate_load_row_errors(source_rows, crosswalk_rows))
    manifest_id = _load_manifest_id(source_rows, crosswalk_rows)
    if errors:
        return SourceCatalogLoadResult(
            status="failed",
            mode="merge",
            conflicts=len(errors),
            source_catalog_rows=len(source_rows),
            source_crosswalk_rows=len(crosswalk_rows),
            manifest_id=manifest_id,
            artifacts=tuple(artifacts),
            errors=tuple(errors),
        )

    db.init_database(database_path)
    try:
        with db.connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                counts = _merge_load_rows(connection, source_rows, crosswalk_rows, manifest_id)
            except sqlite3.Error:
                connection.rollback()
                raise
            if counts["conflicts"]:
                connection.rollback()
                return SourceCatalogLoadResult(
                    status="failed",
                    mode="merge",
                    inserted=counts["inserted"],
                    unchanged=counts["unchanged"],
                    conflicts=counts["conflicts"],
                    source_catalog_rows=len(source_rows),
                    source_crosswalk_rows=len(crosswalk_rows),
                    manifest_id=manifest_id,
                    artifacts=tuple(artifacts),
                    errors=tuple(counts["errors"]),
                )
            connection.commit()
    except sqlite3.Error as exc:
        return SourceCatalogLoadResult(
            status="failed",
            mode="merge",
            source_catalog_rows=len(source_rows),
            source_crosswalk_rows=len(crosswalk_rows),
            manifest_id=manifest_id,
            artifacts=tuple(artifacts),
            errors=(
                SourceCatalogLoadError(
                    "sqlite",
                    None,
                    f"SQLite source catalog load failed and was rolled back: {exc}",
                ),
            ),
        )

    return SourceCatalogLoadResult(
        status="ok",
        mode="merge",
        inserted=counts["inserted"],
        unchanged=counts["unchanged"],
        conflicts=0,
        source_catalog_rows=len(source_rows),
        source_crosswalk_rows=len(crosswalk_rows),
        manifest_id=manifest_id,
        artifacts=tuple(artifacts),
    )


def result_to_text_lines(result: SourceCatalogValidationResult) -> tuple[str, ...]:
    """Return deterministic public text lines for a validation result."""

    status = "ok" if result.ok else "failed"
    summary = result.summary.to_public_dict()
    lines = [
        f"source_catalog_validation: {status}",
        f"path: {summary['path']}",
        f"sha256: {result.summary.sha256}",
        f"line_count: {result.summary.line_count}",
        f"row_count: {result.summary.row_count}",
        f"local_only_count: {result.summary.local_only_count}",
    ]
    for category, count in result.summary.category_counts.items():
        lines.append(f"category: {category} rows={count}")
    for error in result.errors:
        line_number = "" if error.line_number is None else f":{error.line_number}"
        lines.append(f"error{line_number}: {error.message}")
    lines.append("offline-only: no live KoL/network behavior")
    lines.append("local-only references redacted from public output")
    lines.append("not executed: validation is read-only and does not mutate runtime or DB state")
    return tuple(lines)


def validate_source_dump_text(text: str, *, path: Path | None = None) -> SourceCatalogValidationResult:
    """Validate source dump text and return stable public/private metadata."""

    records, errors = _parse_source_dump_text(text)
    duplicate_errors = _duplicate_source_id_errors(records)
    all_errors = tuple([*errors, *duplicate_errors])
    return SourceCatalogValidationResult(
        ok=not all_errors,
        summary=_summary(text, records, path),
        records=() if all_errors else records,
        errors=all_errors,
    )


def _load_row_from_record(record: SourceCatalogRecord, input_sha256: str) -> SourceCatalogLoadRow:
    return SourceCatalogLoadRow(
        source_id=record.source_id,
        name=record.name,
        title=record.title,
        category=record.category,
        reference_kind=record.reference_kind,
        canonical_reference=record.canonical_reference,
        stack_language=record.stack_language,
        trust=record.trust,
        provenance={
            "artifact": record.provenance["artifact"],
            "line_number": record.line_number,
            "category": record.category,
            "reference_kind": record.reference_kind,
        },
        input_sha256=input_sha256,
        source_line_sha256=record.source_line_sha256,
        source_line_number=record.line_number,
        local_only=record.local_only,
        publishability=record.publishability,
        recommendation=record.recommendation,
    )


def _load_rows_from_libkol_inspection_json(
    path: Path,
) -> tuple[tuple[SourceCatalogLoadRow, ...], tuple[SourceCrosswalkLoadRow, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("libkol inspection JSON must be an object")
    if payload.get("ok") is not True:
        raise ValueError("libkol inspection JSON must be an ok inspection result")
    proposals = payload.get("proposals")
    if not isinstance(proposals, dict):
        raise ValueError("libkol inspection JSON missing proposals object")
    if proposals.get("write_mode") != "proposal_only" or proposals.get("authority_mutation") is not False:
        raise ValueError("libkol proposals must be proposal_only with authority_mutation=false")

    source_rows = tuple(
        _source_catalog_load_row_from_mapping(row)
        for row in _list_field(proposals, "source_catalog")
    )
    crosswalk_rows = tuple(
        _source_crosswalk_load_row_from_mapping(row)
        for row in _list_field(proposals, "source_crosswalk")
    )
    return source_rows, crosswalk_rows


def _load_os_error_message(artifact_label: str, exc: OSError) -> str:
    """Return path-free public text for source catalog load file errors."""

    reason = exc.strerror or "unable to read artifact"
    return f"unable to read {artifact_label}: {reason}"


def _list_field(mapping: dict[str, Any], field_name: str) -> list[Any]:
    value = mapping.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f"libkol proposals missing list field: {field_name}")
    return value


def _source_catalog_load_row_from_mapping(row: Any) -> SourceCatalogLoadRow:
    if not isinstance(row, dict):
        raise ValueError("source_catalog proposal row must be an object")
    required = tuple(SourceCatalogLoadRow.__dataclass_fields__)
    missing = [field for field in required if field not in row]
    if missing:
        raise ValueError(f"source_catalog proposal row missing fields: {', '.join(missing)}")
    provenance = row["provenance"]
    if not isinstance(provenance, dict):
        raise ValueError("source_catalog provenance must be an object")
    return SourceCatalogLoadRow(
        source_id=str(row["source_id"]),
        name=str(row["name"]),
        title=str(row["title"]),
        category=str(row["category"]),
        reference_kind=str(row["reference_kind"]),
        canonical_reference=str(row["canonical_reference"]),
        stack_language=str(row["stack_language"]),
        trust=str(row["trust"]),
        provenance=provenance,
        input_sha256=str(row["input_sha256"]),
        source_line_sha256=str(row["source_line_sha256"]),
        source_line_number=int(row["source_line_number"]),
        local_only=bool(row["local_only"]),
        publishability=str(row["publishability"]),
        recommendation=str(row["recommendation"]),
    )


def _source_crosswalk_load_row_from_mapping(row: Any) -> SourceCrosswalkLoadRow:
    if not isinstance(row, dict):
        raise ValueError("source_crosswalk proposal row must be an object")
    required = tuple(SourceCrosswalkLoadRow.__dataclass_fields__)
    missing = [field for field in required if field not in row]
    if missing:
        raise ValueError(f"source_crosswalk proposal row missing fields: {', '.join(missing)}")
    provenance = row["provenance"]
    if not isinstance(provenance, dict):
        raise ValueError("source_crosswalk provenance must be an object")
    return SourceCrosswalkLoadRow(
        crosswalk_id=str(row["crosswalk_id"]),
        source_id=str(row["source_id"]),
        source_content_hash=str(row["source_content_hash"]),
        graph_category=str(row["graph_category"]),
        graph_node_key=str(row["graph_node_key"]),
        relationship=str(row["relationship"]),
        confidence=str(row["confidence"]),
        evidence_content_hash=str(row["evidence_content_hash"]),
        provenance=provenance,
    )


def _artifact_summary(path: Path, artifact_type: str, row_count: int) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "path": path.name,
        "artifact_type": artifact_type,
        "sha256": hashlib.sha256(content).hexdigest(),
        "row_count": row_count,
    }


def _duplicate_load_row_errors(
    source_rows: list[SourceCatalogLoadRow],
    crosswalk_rows: list[SourceCrosswalkLoadRow],
) -> tuple[SourceCatalogLoadError, ...]:
    errors: list[SourceCatalogLoadError] = []
    seen_sources: dict[str, str] = {}
    for row in source_rows:
        fingerprint = _source_catalog_fingerprint(row)
        previous = seen_sources.get(row.source_id)
        if previous is not None and previous != fingerprint:
            errors.append(SourceCatalogLoadError("source_catalog", row.source_id, "conflicting duplicate source_catalog row"))
        else:
            seen_sources[row.source_id] = fingerprint
    seen_crosswalks: dict[str, str] = {}
    for row in crosswalk_rows:
        fingerprint = _source_crosswalk_fingerprint(row)
        previous = seen_crosswalks.get(row.crosswalk_id)
        if previous is not None and previous != fingerprint:
            errors.append(SourceCatalogLoadError("source_crosswalk", row.crosswalk_id, "conflicting duplicate source_crosswalk row"))
        else:
            seen_crosswalks[row.crosswalk_id] = fingerprint
        if row.source_id not in seen_sources:
            errors.append(SourceCatalogLoadError("source_crosswalk", row.crosswalk_id, "crosswalk references missing source_id"))
    return tuple(errors)


def _load_manifest_id(
    source_rows: list[SourceCatalogLoadRow],
    crosswalk_rows: list[SourceCrosswalkLoadRow],
) -> str:
    payload = {
        "source_catalog": [row.to_public_dict() for row in sorted(source_rows, key=lambda item: item.source_id)],
        "source_crosswalk": [row.to_public_dict() for row in sorted(crosswalk_rows, key=lambda item: item.crosswalk_id)],
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _merge_load_rows(
    connection: sqlite3.Connection,
    source_rows: list[SourceCatalogLoadRow],
    crosswalk_rows: list[SourceCrosswalkLoadRow],
    manifest_id: str,
) -> dict[str, Any]:
    counts: dict[str, Any] = {"inserted": 0, "unchanged": 0, "conflicts": 0, "errors": []}
    for row in sorted(source_rows, key=lambda item: item.source_id):
        _merge_source_catalog_row(connection, row, manifest_id, counts)
    if counts["conflicts"]:
        return counts
    for row in sorted(crosswalk_rows, key=lambda item: item.crosswalk_id):
        _merge_source_crosswalk_row(connection, row, counts)
    return counts


def _merge_source_catalog_row(
    connection: sqlite3.Connection,
    row: SourceCatalogLoadRow,
    manifest_id: str,
    counts: dict[str, Any],
) -> None:
    db_values = _source_catalog_db_values(row, manifest_id)
    existing = connection.execute(
        """
        SELECT source_id, title, source_name, source_uri, source_path, source_category,
               stack_language, trust_level, source_load_status, source_version,
               source_content_hash, source_metadata_hash, provenance_json, local_only,
               publishable, recommendation
        FROM source_catalog
        WHERE source_id = ?
        """,
        (row.source_id,),
    ).fetchone()
    if existing is not None:
        if _existing_source_catalog_matches(existing, db_values):
            counts["unchanged"] += 1
            return
        counts["conflicts"] += 1
        counts["errors"].append(
            SourceCatalogLoadError("source_catalog", row.source_id, "existing source_catalog row differs")
        )
        return
    connection.execute(
        """
        INSERT INTO source_catalog(
            source_id, title, source_name, source_uri, source_path, source_category,
            stack_language, kol_relevance, trust_level, source_load_status,
            load_manifest_id, source_version, source_content_hash,
            source_metadata_hash, provenance_json, local_only, publishable, recommendation
        ) VALUES (
            :source_id, :title, :source_name, :source_uri, :source_path, :source_category,
            :stack_language, :kol_relevance, :trust_level, :source_load_status,
            :load_manifest_id, :source_version, :source_content_hash,
            :source_metadata_hash, :provenance_json, :local_only, :publishable, :recommendation
        )
        """,
        db_values,
    )
    counts["inserted"] += 1


def _merge_source_crosswalk_row(
    connection: sqlite3.Connection,
    row: SourceCrosswalkLoadRow,
    counts: dict[str, Any],
) -> None:
    db_values = _source_crosswalk_db_values(row)
    existing = connection.execute(
        """
        SELECT crosswalk_id, source_id, source_content_hash, graph_category,
               graph_node_key, relationship, confidence, evidence_content_hash,
               provenance_json
        FROM source_crosswalk
        WHERE crosswalk_id = ?
        """,
        (row.crosswalk_id,),
    ).fetchone()
    if existing is not None:
        if _existing_source_crosswalk_matches(existing, db_values):
            counts["unchanged"] += 1
            return
        counts["conflicts"] += 1
        counts["errors"].append(
            SourceCatalogLoadError("source_crosswalk", row.crosswalk_id, "existing source_crosswalk row differs")
        )
        return
    connection.execute(
        """
        INSERT INTO source_crosswalk(
            crosswalk_id, source_id, source_content_hash, graph_category,
            graph_node_key, relationship, confidence, evidence_content_hash,
            provenance_json
        ) VALUES (
            :crosswalk_id, :source_id, :source_content_hash, :graph_category,
            :graph_node_key, :relationship, :confidence, :evidence_content_hash,
            :provenance_json
        )
        """,
        db_values,
    )
    counts["inserted"] += 1


def _source_catalog_db_values(row: SourceCatalogLoadRow, manifest_id: str) -> dict[str, Any]:
    source_uri = row.canonical_reference if row.reference_kind != "path" else None
    source_path = row.canonical_reference if row.reference_kind == "path" else None
    provenance_json = _canonical_json(row.provenance)
    metadata_payload = {
        "reference_kind": row.reference_kind,
        "publishability": row.publishability,
        "source_line_number": row.source_line_number,
        "source_line_sha256": row.source_line_sha256,
    }
    return {
        "source_id": row.source_id,
        "title": row.title,
        "source_name": row.name,
        "source_uri": source_uri,
        "source_path": source_path,
        "source_category": row.category,
        "stack_language": row.stack_language,
        "kol_relevance": row.recommendation,
        "trust_level": row.trust,
        "source_load_status": "loaded",
        "load_manifest_id": manifest_id,
        "source_version": str(row.source_line_number),
        "source_content_hash": row.input_sha256,
        "source_metadata_hash": _sha256_text(_canonical_json(metadata_payload)),
        "provenance_json": provenance_json,
        "local_only": int(row.local_only),
        "publishable": int(not row.local_only and row.publishability == "public_reference"),
        "recommendation": row.recommendation,
    }


def _source_crosswalk_db_values(row: SourceCrosswalkLoadRow) -> dict[str, Any]:
    return {
        "crosswalk_id": row.crosswalk_id,
        "source_id": row.source_id,
        "source_content_hash": row.source_content_hash,
        "graph_category": row.graph_category,
        "graph_node_key": row.graph_node_key,
        "relationship": row.relationship,
        "confidence": row.confidence,
        "evidence_content_hash": row.evidence_content_hash,
        "provenance_json": _canonical_json(row.provenance),
    }


def _existing_source_catalog_matches(existing: sqlite3.Row, db_values: dict[str, Any]) -> bool:
    for key in (
        "source_id",
        "title",
        "source_name",
        "source_uri",
        "source_path",
        "source_category",
        "stack_language",
        "trust_level",
        "source_load_status",
        "source_version",
        "source_content_hash",
        "source_metadata_hash",
        "provenance_json",
        "local_only",
        "publishable",
        "recommendation",
    ):
        if existing[key] != db_values[key]:
            return False
    return True


def _existing_source_crosswalk_matches(existing: sqlite3.Row, db_values: dict[str, Any]) -> bool:
    for key in (
        "crosswalk_id",
        "source_id",
        "source_content_hash",
        "graph_category",
        "graph_node_key",
        "relationship",
        "confidence",
        "evidence_content_hash",
        "provenance_json",
    ):
        if existing[key] != db_values[key]:
            return False
    return True


def _source_catalog_fingerprint(row: SourceCatalogLoadRow) -> str:
    return _sha256_text(_canonical_json(row.to_public_dict()))


def _source_crosswalk_fingerprint(row: SourceCrosswalkLoadRow) -> str:
    return _sha256_text(_canonical_json(row.to_public_dict()))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_source_dump_text(
    text: str,
) -> tuple[tuple[SourceCatalogRecord, ...], tuple[SourceCatalogError, ...]]:
    if not text.strip():
        return (), (SourceCatalogError(None, "source dump is empty"),)

    records: list[SourceCatalogRecord] = []
    errors: list[SourceCatalogError] = []
    category = "UNCATEGORIZED"
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        maybe_category = _category_from_line(stripped)
        if maybe_category is not None:
            category = maybe_category
            continue
        if not _looks_like_source_row(stripped):
            continue
        try:
            records.append(_record_from_line(line, line_number, category))
        except ValueError as error:
            errors.append(SourceCatalogError(line_number, str(error)))
    return tuple(records), tuple(errors)


def _category_from_line(stripped: str) -> str | None:
    match = _CATEGORY_RE.match(stripped)
    if match is None:
        return None
    category = match.group(1).strip("- ")
    if not category or category in {"KEY", ""}:
        return None
    return category


def _looks_like_source_row(stripped: str) -> bool:
    return (
        "g-h/" in stripped
        or _PATH_RE.search(stripped) is not None
        or bool(_URL_RE.search(stripped))
        or stripped in {"- -", "-  - -"}
    )


def _record_from_line(line: str, line_number: int, category: str) -> SourceCatalogRecord:
    stripped = line.strip()
    github_match = _GITHUB_RE.search(stripped)
    if "g-h/" in stripped and github_match is None:
        raise ValueError("malformed github shorthand")
    path_match = _PATH_RE.search(stripped)
    if path_match is not None:
        if line_number < PRIVATE_LOCAL_START_LINE:
            raise ValueError("local PATH row before private section")
        raw_reference = path_match.group("path").strip()
        return _build_record(
            source_line=line,
            line_number=line_number,
            category=category,
            reference_kind="path",
            canonical_reference=_local_path_reference(raw_reference),
            raw_reference=raw_reference,
            local_only=True,
        )
    if github_match is not None:
        repo = github_match.group(1)
        return _build_record(
            source_line=line,
            line_number=line_number,
            category=category,
            reference_kind="github",
            canonical_reference=f"github.com/{repo}",
            raw_reference=f"g-h/{repo}",
            local_only=False,
        )
    url_match = _URL_RE.search(stripped)
    if url_match is not None:
        url = url_match.group(1).rstrip(".\\")
        return _build_record(
            source_line=line,
            line_number=line_number,
            category=category,
            reference_kind="url",
            canonical_reference=url,
            raw_reference=url,
            local_only=False,
        )
    raise ValueError("malformed source row")


def _build_record(
    *,
    source_line: str,
    line_number: int,
    category: str,
    reference_kind: str,
    canonical_reference: str,
    raw_reference: str,
    local_only: bool,
) -> SourceCatalogRecord:
    trust = "private_local_reference" if local_only else _public_trust(reference_kind)
    name = _name_from_reference(reference_kind, canonical_reference)
    return SourceCatalogRecord(
        source_id=_source_id(reference_kind, canonical_reference),
        line_number=line_number,
        category=category,
        reference_kind=reference_kind,
        canonical_reference=canonical_reference,
        raw_reference=raw_reference,
        name=name,
        title=_title_from_source_line(source_line, raw_reference, name),
        stack_language=_stack_language(category),
        trust=trust,
        source_line_sha256=hashlib.sha256(source_line.encode("utf-8")).hexdigest(),
        provenance={
            "artifact": "KOL_Master/kol_master_additions",
            "line_number": line_number,
            "category": category,
        },
        local_only=local_only,
        publishability="private_local_summary_only" if local_only else "public_reference",
        recommendation=_recommendation(reference_kind, local_only),
    )


def _source_id(reference_kind: str, canonical_reference: str) -> str:
    digest = hashlib.sha256(f"{reference_kind}\0{canonical_reference.lower()}".encode("utf-8"))
    return f"src_{digest.hexdigest()[:16]}"


def _local_path_reference(raw_reference: str) -> str:
    digest = hashlib.sha256(raw_reference.encode("utf-8")).hexdigest()[:16]
    return f"local-path:{digest}"


def _name_from_reference(reference_kind: str, canonical_reference: str) -> str:
    if reference_kind == "github":
        return unquote(canonical_reference.rstrip("/").split("/")[-1])
    if reference_kind == "path":
        return canonical_reference.replace(":", "-")
    cleaned = canonical_reference.rstrip("/")
    return unquote(cleaned.rsplit("/", maxsplit=1)[-1] or cleaned)


def _title_from_source_line(source_line: str, raw_reference: str, fallback: str) -> str:
    stripped = source_line.strip()
    reference_index = stripped.find(raw_reference)
    if reference_index == -1:
        return fallback
    trailing = stripped[reference_index + len(raw_reference) :]
    title = _clean_title(trailing)
    return title or fallback


def _clean_title(value: str) -> str:
    title = unquote(value).strip()
    title = re.sub(r"^(?:[-:–—]|\s)+", "", title).strip()
    return re.sub(r"\s+", " ", title)


def _public_trust(reference_kind: str) -> str:
    if reference_kind == "github":
        return "github_shorthand_unfetched"
    return "public_web_reference_unfetched"


def _recommendation(reference_kind: str, local_only: bool) -> str:
    if local_only:
        return "summarize_private_local_reference"
    if reference_kind == "github":
        return "review_public_repository_metadata_offline"
    return "review_public_web_reference_offline"


def _stack_language(category: str) -> str:
    upper = category.upper()
    if "PY" in upper or "PYTHON" in upper:
        return "Python"
    if "TS" in upper or "TYPESCRIPT" in upper:
        return "TypeScript"
    if "JS" in upper:
        return "JavaScript"
    if "GO" in upper:
        return "Go"
    if "JAVA" in upper:
        return "Java"
    if upper == "C" or upper.startswith("C/"):
        return "C"
    if "MOBILE" in upper:
        return "Mobile"
    if "BOT" in upper:
        return "Bot"
    if "LLM" in upper:
        return "LLM"
    return "Unspecified"


def _duplicate_source_id_errors(records: tuple[SourceCatalogRecord, ...]) -> tuple[SourceCatalogError, ...]:
    seen: dict[str, SourceCatalogRecord] = {}
    errors: list[SourceCatalogError] = []
    for record in records:
        previous = seen.get(record.source_id)
        if previous is not None:
            issue = "duplicate" if previous.category == record.category else "conflicting"
            errors.append(
                SourceCatalogError(
                    record.line_number,
                    f"{issue} source_id: {record.source_id} "
                    f"first seen on line {previous.line_number} "
                    f"category={previous.category!r} current_category={record.category!r}",
                )
            )
        else:
            seen[record.source_id] = record
    return tuple(errors)


def _summary(
    text: str,
    records: tuple[SourceCatalogRecord, ...],
    path: Path | None,
) -> SourceCatalogSummary:
    category_counts: dict[str, int] = {}
    for record in records:
        category_counts[record.category] = category_counts.get(record.category, 0) + 1
    return SourceCatalogSummary(
        path=str(path) if path is not None else "<memory>",
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        line_count=len(text.splitlines()),
        row_count=len(records),
        category_counts=dict(sorted(category_counts.items())),
        local_only_count=sum(1 for record in records if record.local_only),
    )
