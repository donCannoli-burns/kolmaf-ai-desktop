"""Read-only CSV capability import validation and planning."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from kolmafa import db


EXPECTED_CAPABILITY_COLUMNS: tuple[str, ...] = (
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
)

BOOLEAN_COLUMNS: frozenset[str] = frozenset(
    {
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
    }
)

REQUIRED_TEXT_COLUMNS: frozenset[str] = frozenset(
    {
        "entry_id",
        "name",
        "entry_type",
        "language",
        "source_document",
        "source_location",
        "evidence_status",
        "read_or_mutate",
        "candidate_risk",
    }
)

ALLOWED_SOURCE_CORPORA: frozenset[str] = frozenset(
    {"kolmafia_capability_index.csv", "kolmafia_priority_flags.csv"}
)

EXPECTED_HASHTABLE_ARTIFACTS: frozenset[str] = frozenset(
    {"kolmafia_capability.hashtable.json", "agent_resource.hashtable.json"}
)
HASHTABLE_HASH_MARKER = "fnv1a_64"


@dataclass(frozen=True, slots=True)
class CsvArtifactSummary:
    """Deterministic summary of one input CSV artifact."""

    path: str
    source_corpus: str
    sha256: str
    row_count: int
    column_count: int


@dataclass(frozen=True, slots=True)
class ValidationErrorDetail:
    """Structured validation error for fail-closed reporting."""

    source_corpus: str
    row_number: int | None
    message: str


@dataclass(frozen=True, slots=True)
class PlannedCapabilityRow:
    """Read-only import plan row matching capability_records generated metadata."""

    values: dict[str, str | int]


@dataclass(frozen=True, slots=True)
class CapabilityImportValidationResult:
    """Read-only validator result."""

    ok: bool
    artifacts: tuple[CsvArtifactSummary, ...] = ()
    rows: tuple[PlannedCapabilityRow, ...] = ()
    errors: tuple[ValidationErrorDetail, ...] = ()

    @property
    def row_count(self) -> int:
        """Return total planned row count."""

        return len(self.rows)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable deterministic result data."""

        return {
            "ok": self.ok,
            "row_count": self.row_count,
            "artifacts": [asdict(artifact) for artifact in self.artifacts],
            "errors": [asdict(error) for error in self.errors],
        }


@dataclass(frozen=True, slots=True)
class CapabilityLoadResult:
    """Transactional offline capability authority load result."""

    status: str
    mode: str
    capability_count: int = 0
    annotation_count: int = 0
    artifacts: tuple[CsvArtifactSummary, ...] = ()
    drift: tuple[str, ...] = ()
    errors: tuple[ValidationErrorDetail, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether the offline load succeeded."""

        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-serializable load data."""

        return {
            "status": self.status,
            "mode": self.mode,
            "counts": {
                "capability_records": self.capability_count,
                "priority_annotations": self.annotation_count,
            },
            "artifact_checksums": [asdict(artifact) for artifact in self.artifacts],
            "annotation_count": self.annotation_count,
            "drift": list(self.drift),
            "errors": [asdict(error) for error in self.errors],
            "offline": True,
            "live_kol_mutation": False,
        }


@dataclass(frozen=True, slots=True)
class HashtableArtifactSummary:
    """Deterministic summary of one advisory frozen hashtable artifact."""

    path: str
    artifact_name: str
    sha256: str
    source: str
    provenance_entries: int
    capacity: int
    size: int
    slot_count: int
    hash_marker: str
    max_psl: int
    avg_psl: float
    empty_slots: int


@dataclass(frozen=True, slots=True)
class HashtableValidationResult:
    """Read-only advisory hashtable/provenance validation result."""

    ok: bool
    artifacts: tuple[HashtableArtifactSummary, ...] = ()
    errors: tuple[ValidationErrorDetail, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable deterministic result data."""

        return {
            "ok": self.ok,
            "artifacts": [asdict(artifact) for artifact in self.artifacts],
            "errors": [asdict(error) for error in self.errors],
        }


@dataclass(frozen=True, slots=True)
class AuthorityCsvDriftSummary:
    """Deterministic CSV-to-SQLite authority drift summary."""

    source_corpus: str
    supplied: bool
    status: str
    csv_row_count: int | None = None
    db_row_count: int | None = None
    csv_sha256: str | None = None
    csv_content_checksum: str | None = None
    db_content_checksum: str | None = None
    messages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthorityReportResult:
    """Read-only SQLite authority report result."""

    status: str
    database_path: str
    counts: dict[str, int]
    authority_checksums: dict[str, str]
    priority_annotation_summary: dict[str, Any]
    csv_drift: tuple[AuthorityCsvDriftSummary, ...] = ()
    hashtable_validation: HashtableValidationResult | None = None
    errors: tuple[ValidationErrorDetail, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether the read-only report succeeded without hard errors."""

        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-serializable report data."""

        return {
            "status": self.status,
            "database_path": self.database_path,
            "counts": self.counts,
            "authority_checksums": self.authority_checksums,
            "priority_annotation_summary": self.priority_annotation_summary,
            "csv_drift": [asdict(drift) for drift in self.csv_drift],
            "hashtable_validation": (
                self.hashtable_validation.to_dict() if self.hashtable_validation is not None else None
            ),
            "errors": [asdict(error) for error in self.errors],
            "offline": True,
            "read_only": True,
            "live_kol_mutation": False,
        }


@dataclass(slots=True)
class _ArtifactAccumulator:
    path: Path
    source_corpus: str
    sha256: str
    rows: list[PlannedCapabilityRow] = field(default_factory=list)

    def summary(self) -> CsvArtifactSummary:
        return CsvArtifactSummary(
            path=str(self.path),
            source_corpus=self.source_corpus,
            sha256=self.sha256,
            row_count=len(self.rows),
            column_count=len(EXPECTED_CAPABILITY_COLUMNS),
        )


def validate_capability_csv_files(
    paths: list[Path],
    *,
    expected_sha256: dict[str, str] | None = None,
) -> CapabilityImportValidationResult:
    """Validate canonical capability CSV artifacts without mutating runtime state."""

    artifacts: list[CsvArtifactSummary] = []
    rows: list[PlannedCapabilityRow] = []
    errors: list[ValidationErrorDetail] = []

    if not paths:
        errors.append(ValidationErrorDetail("<none>", None, "at least one CSV path is required"))
        return CapabilityImportValidationResult(ok=False, errors=tuple(errors))

    checksum_expectations = expected_sha256 or {}
    seen_entry_ids: dict[str, tuple[str, int]] = {}
    for path in paths:
        accumulator = _read_artifact(path, errors)
        if accumulator is not None:
            expected_checksum = checksum_expectations.get(accumulator.source_corpus)
            if expected_checksum is not None and expected_checksum != accumulator.sha256:
                errors.append(
                    ValidationErrorDetail(
                        accumulator.source_corpus,
                        None,
                        "CSV artifact SHA256 does not match expected checksum",
                    )
                )
            artifacts.append(accumulator.summary())
            for planned_row in accumulator.rows:
                entry_id = str(planned_row.values["entry_id"])
                source_row_number = int(planned_row.values["source_row_number"])
                if entry_id in seen_entry_ids:
                    first_source_corpus, first_row_number = seen_entry_ids[entry_id]
                    errors.append(
                        ValidationErrorDetail(
                            accumulator.source_corpus,
                            source_row_number,
                            "duplicate entry_id across capability CSV artifacts: "
                            f"{entry_id} first seen in {first_source_corpus} row {first_row_number}",
                        )
                    )
                    continue
                seen_entry_ids[entry_id] = (accumulator.source_corpus, source_row_number)
                rows.append(planned_row)

    return CapabilityImportValidationResult(
        ok=not errors,
        artifacts=tuple(artifacts),
        rows=tuple(rows) if not errors else (),
        errors=tuple(errors),
    )


def result_to_json(result: CapabilityImportValidationResult) -> str:
    """Serialize validation result deterministically."""

    return json.dumps(result.to_dict(), indent=2, sort_keys=True)


def load_result_to_json(result: CapabilityLoadResult) -> str:
    """Serialize load result deterministically."""

    return json.dumps(result.to_dict(), indent=2, sort_keys=True)


def authority_report_to_json(result: AuthorityReportResult) -> str:
    """Serialize authority report result deterministically."""

    return json.dumps(result.to_dict(), indent=2, sort_keys=True)


def build_authority_report(
    database_path: Path,
    *,
    capability_csv_path: Path | None = None,
    priority_csv_path: Path | None = None,
    hashtable_paths: list[Path] | None = None,
    provenance_path: Path | None = None,
) -> AuthorityReportResult:
    """Build a deterministic read-only report for an explicit SQLite authority DB.

    The report never initializes schemas, imports rows, deletes rows, updates rows,
    or contacts external services. CSV and hashtable inputs are optional comparison
    artifacts; SQLite remains the authority after import.
    """

    errors: list[ValidationErrorDetail] = []
    if not database_path.exists():
        return AuthorityReportResult(
            status="failed",
            database_path=str(database_path),
            counts=_empty_authority_counts(),
            authority_checksums={},
            priority_annotation_summary={},
            errors=(ValidationErrorDetail("sqlite", None, "explicit SQLite DB path does not exist"),),
        )
    if not database_path.is_file():
        return AuthorityReportResult(
            status="failed",
            database_path=str(database_path),
            counts=_empty_authority_counts(),
            authority_checksums={},
            priority_annotation_summary={},
            errors=(ValidationErrorDetail("sqlite", None, "explicit SQLite DB path is not a file"),),
        )

    try:
        with _connect_read_only(database_path) as connection:
            counts = _authority_counts(connection)
            checksums = _authority_checksums(connection)
            priority_summary = _priority_annotation_summary(connection)
            csv_drift = _csv_drift_summaries(connection, capability_csv_path, priority_csv_path)
    except sqlite3.Error as exc:
        errors.append(ValidationErrorDetail("sqlite", None, f"read-only SQLite authority report failed: {exc}"))
        return AuthorityReportResult(
            status="failed",
            database_path=str(database_path),
            counts=_empty_authority_counts(),
            authority_checksums={},
            priority_annotation_summary={},
            errors=tuple(errors),
        )

    hashtable_validation: HashtableValidationResult | None = None
    if hashtable_paths or provenance_path is not None:
        if provenance_path is None:
            hashtable_validation = HashtableValidationResult(
                ok=False,
                errors=(ValidationErrorDetail("<none>", None, "hashtable provenance path is required"),),
            )
        else:
            hashtable_validation = validate_hashtable_artifacts(
                hashtable_paths or [],
                provenance_path,
                canonical_capability_csv_path=capability_csv_path,
            )
            hashtable_validation = _with_db_hashtable_mismatch(
                hashtable_validation,
                counts["capability_records"],
            )

    return AuthorityReportResult(
        status="ok" if not errors else "failed",
        database_path=str(database_path),
        counts=counts,
        authority_checksums=checksums,
        priority_annotation_summary=priority_summary,
        csv_drift=csv_drift,
        hashtable_validation=hashtable_validation,
        errors=tuple(errors),
    )


def load_capability_authority(
    database_path: Path,
    capability_csv_path: Path,
    priority_csv_path: Path,
    *,
    expected_sha256: dict[str, str] | None = None,
) -> CapabilityLoadResult:
    """Replace capability authority tables from CSVs in one SQLite transaction.

    The capability CSV is authoritative for capability_records. The priority CSV
    is imported only as annotations referencing existing capability entry_id
    values. No live KoL process, transport, DAG executor, or network path is used.
    """

    capability_result = validate_capability_csv_files(
        [capability_csv_path],
        expected_sha256=expected_sha256,
    )
    priority_result = validate_capability_csv_files(
        [priority_csv_path],
        expected_sha256=expected_sha256,
    )

    artifacts = capability_result.artifacts + priority_result.artifacts
    errors = list(capability_result.errors) + list(priority_result.errors)
    if capability_csv_path.name != "kolmafia_capability_index.csv":
        errors.append(
            ValidationErrorDetail(
                capability_csv_path.name,
                None,
                "capability authority path must be kolmafia_capability_index.csv",
            )
        )
    if priority_csv_path.name != "kolmafia_priority_flags.csv":
        errors.append(
            ValidationErrorDetail(
                priority_csv_path.name,
                None,
                "priority annotation path must be kolmafia_priority_flags.csv",
            )
        )

    capability_entry_ids = {str(row.values["entry_id"]) for row in capability_result.rows}
    for priority_row in priority_result.rows:
        entry_id = str(priority_row.values["entry_id"])
        if entry_id not in capability_entry_ids:
            errors.append(
                ValidationErrorDetail(
                    "kolmafia_priority_flags.csv",
                    int(priority_row.values["source_row_number"]),
                    f"priority entry_id has no capability authority row: {entry_id}",
                )
            )

    if errors:
        return CapabilityLoadResult(
            status="failed",
            mode="replace",
            artifacts=artifacts,
            drift=(),
            errors=tuple(errors),
        )

    db.init_database(database_path)
    connection = None
    try:
        connection = db.connect(database_path)
        connection.execute("BEGIN IMMEDIATE")
        try:
            _replace_capability_rows(connection, capability_result.rows, priority_result.rows)
        except sqlite3.Error:
            connection.rollback()
            raise
        connection.commit()
        # Fold the WAL into the main database file before returning so the
        # on-disk artifact is stable: a later close of this connection (or of
        # any other) must not rewrite the main file header.
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        return CapabilityLoadResult(
            status="failed",
            mode="replace",
            artifacts=artifacts,
            errors=(
                ValidationErrorDetail(
                    "sqlite",
                    None,
                    f"SQLite capability import failed and was rolled back: {exc}",
                ),
            ),
        )
    finally:
        if connection is not None:
            connection.close()

    return CapabilityLoadResult(
        status="ok",
        mode="replace",
        capability_count=len(capability_result.rows),
        annotation_count=len(priority_result.rows),
        artifacts=artifacts,
    )


def hashtable_result_to_json(result: HashtableValidationResult) -> str:
    """Serialize hashtable validation result deterministically."""

    return json.dumps(result.to_dict(), indent=2, sort_keys=True)


def validate_hashtable_artifacts(
    table_paths: list[Path],
    provenance_path: Path,
    *,
    canonical_capability_csv_path: Path | None = None,
) -> HashtableValidationResult:
    """Validate advisory frozen hashtables against provenance and canonical CSV.

    The CSV remains the source of truth. Frozen hashtables are checked only as
    generated cache artifacts and are never thawed as authoritative data.
    """

    errors: list[ValidationErrorDetail] = []
    artifacts: list[HashtableArtifactSummary] = []
    provenance = _read_provenance(provenance_path, errors)
    expected_csv_rows: int | None = None

    if canonical_capability_csv_path is not None:
        csv_result = validate_capability_csv_files([canonical_capability_csv_path])
        if csv_result.ok:
            expected_csv_rows = csv_result.row_count
        else:
            for error in csv_result.errors:
                errors.append(
                    ValidationErrorDetail(
                        error.source_corpus,
                        error.row_number,
                        f"canonical CSV validation failed: {error.message}",
                    )
                )

    if not table_paths:
        errors.append(ValidationErrorDetail("<none>", None, "at least one hashtable path is required"))

    if provenance is not None:
        for artifact_name in sorted(EXPECTED_HASHTABLE_ARTIFACTS):
            if artifact_name not in provenance:
                errors.append(
                    ValidationErrorDetail(
                        artifact_name,
                        None,
                        "missing provenance entry for expected hashtable artifact",
                    )
                )

    for table_path in table_paths:
        summary = _validate_one_hashtable(
            table_path,
            provenance,
            expected_csv_rows,
            errors,
        )
        if summary is not None:
            artifacts.append(summary)

    return HashtableValidationResult(
        ok=not errors,
        artifacts=tuple(artifacts),
        errors=tuple(errors),
    )


def _connect_read_only(database_path: Path) -> sqlite3.Connection:
    """Open an existing SQLite database in read-only URI mode."""

    uri = f"file:{quote(str(database_path.resolve()), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _empty_authority_counts() -> dict[str, int]:
    return {
        "capability_records": 0,
        "agent_resource_records": 0,
        "capability_priority_annotations": 0,
    }


def _authority_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table_name: int(connection.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0])
        for table_name in (
            "capability_records",
            "agent_resource_records",
            "capability_priority_annotations",
        )
    }


def _authority_checksums(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        "capability_records": _query_checksum(
            connection,
            """
            SELECT entry_id, name, entry_type, language, signature_or_syntax, aliases,
                   source_document, source_location, evidence_status, read_or_mutate,
                   argument_dependent, domains_touched, reads_game_state, mutates_game_state,
                   reads_preferences, writes_preferences, reads_files, writes_files,
                   contacts_network, spends_turns, spends_meat, spends_items,
                   changes_inventory, changes_equipment, changes_choice_state,
                   social_or_kmail_output, authentication_effect, process_or_ui_effect,
                   nested_cli_execution, nested_ash_execution, script_execution,
                   deferred_execution, hook_or_lifecycle_surface, relay_or_url_surface,
                   candidate_risk, recursive_classification_required, fail_closed_if_unresolved,
                   native_or_runtime_surface, notes, source_corpus, source_row_number,
                   source_content_hash, provenance_json
            FROM capability_records
            ORDER BY entry_id
            """,
        ),
        "agent_resource_records": _query_checksum(
            connection,
            """
            SELECT resource_id, capability_entry_id, resource_kind, resource_name, access_mode,
                   authority_surface, source_corpus, source_entry_id, source_row_number,
                   source_content_hash, provenance_json
            FROM agent_resource_records
            ORDER BY resource_id
            """,
        ),
        "capability_priority_annotations": _query_checksum(
            connection,
            """
            SELECT entry_id, priority_candidate_risk, priority_recursive_classification_required,
                   priority_fail_closed_if_unresolved, priority_read_or_mutate,
                   priority_domains_touched, annotation_json, source_corpus, source_row_number,
                   source_content_hash, provenance_json
            FROM capability_priority_annotations
            ORDER BY entry_id
            """,
        ),
    }


def _query_checksum(connection: sqlite3.Connection, sql: str) -> str:
    rows = [dict(row) for row in connection.execute(sql).fetchall()]
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _priority_annotation_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    grouped_rows = connection.execute(
        """
        SELECT priority_candidate_risk AS risk,
               priority_fail_closed_if_unresolved AS fail_closed_if_unresolved,
               priority_recursive_classification_required AS recursive_classification_required,
               count(*) AS count
        FROM capability_priority_annotations
        GROUP BY risk, fail_closed_if_unresolved, recursive_classification_required
        ORDER BY risk, fail_closed_if_unresolved, recursive_classification_required
        """
    ).fetchall()
    fail_closed_count = int(
        connection.execute(
            "SELECT count(*) FROM capability_priority_annotations WHERE priority_fail_closed_if_unresolved = 1"
        ).fetchone()[0]
    )
    recursive_count = int(
        connection.execute(
            "SELECT count(*) FROM capability_priority_annotations WHERE priority_recursive_classification_required = 1"
        ).fetchone()[0]
    )
    return {
        "annotation_count": int(
            connection.execute("SELECT count(*) FROM capability_priority_annotations").fetchone()[0]
        ),
        "fail_closed_if_unresolved_count": fail_closed_count,
        "recursive_classification_required_count": recursive_count,
        "risk_fail_closed_groups": [dict(row) for row in grouped_rows],
    }


def _csv_drift_summaries(
    connection: sqlite3.Connection,
    capability_csv_path: Path | None,
    priority_csv_path: Path | None,
) -> tuple[AuthorityCsvDriftSummary, ...]:
    return (
        _csv_drift_summary(
            connection,
            "kolmafia_capability_index.csv",
            capability_csv_path,
            "capability_records",
        ),
        _csv_drift_summary(
            connection,
            "kolmafia_priority_flags.csv",
            priority_csv_path,
            "capability_priority_annotations",
        ),
    )


def _csv_drift_summary(
    connection: sqlite3.Connection,
    source_corpus: str,
    csv_path: Path | None,
    table_name: str,
) -> AuthorityCsvDriftSummary:
    db_hashes = _source_hashes(connection, table_name)
    db_checksum = _hash_list_checksum(db_hashes)
    if csv_path is None:
        return AuthorityCsvDriftSummary(
            source_corpus=source_corpus,
            supplied=False,
            status="not_checked",
            db_row_count=len(db_hashes),
            db_content_checksum=db_checksum,
        )

    validation = validate_capability_csv_files([csv_path])
    if not validation.ok:
        return AuthorityCsvDriftSummary(
            source_corpus=source_corpus,
            supplied=True,
            status="invalid_csv",
            db_row_count=len(db_hashes),
            db_content_checksum=db_checksum,
            messages=tuple(error.message for error in validation.errors),
        )

    artifact = validation.artifacts[0]
    csv_hashes = tuple(sorted(str(row.values["source_content_hash"]) for row in validation.rows))
    csv_checksum = _hash_list_checksum(csv_hashes)
    messages: list[str] = []
    if len(csv_hashes) != len(db_hashes):
        messages.append("row count drift")
    if csv_checksum != db_checksum:
        messages.append("content checksum drift")
    missing_in_db = sorted(set(csv_hashes) - set(db_hashes))
    missing_in_csv = sorted(set(db_hashes) - set(csv_hashes))
    if missing_in_db or missing_in_csv:
        messages.append("content set drift")
    return AuthorityCsvDriftSummary(
        source_corpus=source_corpus,
        supplied=True,
        status="drift" if messages else "match",
        csv_row_count=len(csv_hashes),
        db_row_count=len(db_hashes),
        csv_sha256=artifact.sha256,
        csv_content_checksum=csv_checksum,
        db_content_checksum=db_checksum,
        messages=tuple(messages),
    )


def _source_hashes(connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    rows = connection.execute(
        f"SELECT source_content_hash FROM {table_name} ORDER BY source_content_hash"
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _hash_list_checksum(values: tuple[str, ...]) -> str:
    canonical = json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _with_db_hashtable_mismatch(
    result: HashtableValidationResult,
    capability_count: int,
) -> HashtableValidationResult:
    errors = list(result.errors)
    for artifact in result.artifacts:
        if artifact.artifact_name == "kolmafia_capability.hashtable.json" and artifact.size != capability_count:
            errors.append(
                ValidationErrorDetail(
                    artifact.artifact_name,
                    None,
                    "SQLite capability authority row count differs from capability hashtable size",
                )
            )
    return HashtableValidationResult(
        ok=not errors,
        artifacts=result.artifacts,
        errors=tuple(errors),
    )


def _replace_capability_rows(
    connection: sqlite3.Connection,
    capability_rows: tuple[PlannedCapabilityRow, ...],
    priority_rows: tuple[PlannedCapabilityRow, ...],
) -> None:
    """Replace capability authority and priority annotations in one transaction."""

    connection.execute("DELETE FROM capability_priority_annotations")
    connection.execute("DELETE FROM capability_records")

    capability_insert_columns = EXPECTED_CAPABILITY_COLUMNS + (
        "source_corpus",
        "source_row_number",
        "source_content_hash",
        "provenance_json",
    )
    placeholders = ", ".join("?" for _ in capability_insert_columns)
    column_list = ", ".join(capability_insert_columns)
    capability_sql = f"INSERT INTO capability_records({column_list}) VALUES ({placeholders})"
    for row in capability_rows:
        connection.execute(
            capability_sql,
            tuple(_database_value(column, row.values[column]) for column in capability_insert_columns),
        )

    for row in priority_rows:
        values = row.values
        annotation_json = json.dumps(
            {
                column: values[column]
                for column in EXPECTED_CAPABILITY_COLUMNS
                if column != "entry_id"
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        connection.execute(
            """
            INSERT INTO capability_priority_annotations(
                entry_id,
                priority_candidate_risk,
                priority_recursive_classification_required,
                priority_fail_closed_if_unresolved,
                priority_read_or_mutate,
                priority_domains_touched,
                annotation_json,
                source_corpus,
                source_row_number,
                source_content_hash,
                provenance_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["entry_id"],
                values["candidate_risk"],
                _database_value("recursive_classification_required", values["recursive_classification_required"]),
                _database_value("fail_closed_if_unresolved", values["fail_closed_if_unresolved"]),
                values["read_or_mutate"],
                values["domains_touched"],
                annotation_json,
                values["source_corpus"],
                values["source_row_number"],
                values["source_content_hash"],
                values["provenance_json"],
            ),
        )


def _database_value(column: str, value: str | int) -> str | int:
    """Convert validated CSV values to SQLite storage values."""

    if column in BOOLEAN_COLUMNS:
        return 1 if value == "true" else 0
    return value


def _read_provenance(
    provenance_path: Path,
    errors: list[ValidationErrorDetail],
) -> dict[str, Any] | None:
    try:
        raw = json.loads(provenance_path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(
            ValidationErrorDetail(
                provenance_path.name,
                None,
                f"cannot read hashtable provenance: {exc}",
            )
        )
        return None
    except json.JSONDecodeError as exc:
        errors.append(
            ValidationErrorDetail(
                provenance_path.name,
                None,
                f"hashtable provenance is not valid JSON: {exc}",
            )
        )
        return None

    if not isinstance(raw, dict):
        errors.append(
            ValidationErrorDetail(provenance_path.name, None, "hashtable provenance root must be an object")
        )
        return None
    return raw


def _validate_one_hashtable(
    table_path: Path,
    provenance: dict[str, Any] | None,
    expected_csv_rows: int | None,
    errors: list[ValidationErrorDetail],
) -> HashtableArtifactSummary | None:
    artifact_name = table_path.name
    try:
        content = table_path.read_bytes()
    except OSError as exc:
        errors.append(ValidationErrorDetail(artifact_name, None, f"cannot read hashtable artifact: {exc}"))
        return None

    sha256 = hashlib.sha256(content).hexdigest()
    try:
        frozen = json.loads(content.decode("utf-8"))
    except UnicodeDecodeError as exc:
        errors.append(ValidationErrorDetail(artifact_name, None, f"hashtable artifact is not UTF-8: {exc}"))
        return None
    except json.JSONDecodeError as exc:
        errors.append(ValidationErrorDetail(artifact_name, None, f"hashtable artifact is not valid JSON: {exc}"))
        return None

    if not isinstance(frozen, dict):
        errors.append(ValidationErrorDetail(artifact_name, None, "hashtable artifact root must be an object"))
        return None

    stats = _validate_frozen_table_shape(artifact_name, frozen, errors)
    record = _validate_provenance_record(artifact_name, provenance, sha256, stats, errors)

    source = ""
    entries = 0
    if isinstance(record, dict):
        source_value = record.get("source")
        source = source_value if isinstance(source_value, str) else ""
        entries_value = record.get("entries")
        entries = entries_value if isinstance(entries_value, int) and not isinstance(entries_value, bool) else 0

    if (
        artifact_name == "kolmafia_capability.hashtable.json"
        and expected_csv_rows is not None
        and stats["size"] != expected_csv_rows
    ):
        errors.append(
            ValidationErrorDetail(
                artifact_name,
                None,
                "canonical CSV row count differs from capability hashtable size",
            )
        )

    return HashtableArtifactSummary(
        path=str(table_path),
        artifact_name=artifact_name,
        sha256=sha256,
        source=source,
        provenance_entries=entries,
        capacity=stats["capacity"],
        size=stats["size"],
        slot_count=stats["slot_count"],
        hash_marker=stats["hash_marker"],
        max_psl=stats["max_psl"],
        avg_psl=stats["avg_psl"],
        empty_slots=stats["empty_slots"],
    )


def _validate_frozen_table_shape(
    artifact_name: str,
    frozen: dict[str, Any],
    errors: list[ValidationErrorDetail],
) -> dict[str, Any]:
    capacity = _int_field(artifact_name, frozen, "capacity", errors)
    size = _int_field(artifact_name, frozen, "size", errors)
    hash_marker = frozen.get("hash")
    if hash_marker != HASHTABLE_HASH_MARKER:
        errors.append(ValidationErrorDetail(artifact_name, None, "hashtable hash marker is not fnv1a_64"))

    slots = frozen.get("slots")
    if not isinstance(slots, list):
        errors.append(ValidationErrorDetail(artifact_name, None, "hashtable slots must be a list"))
        slots = []

    if capacity <= 0:
        errors.append(ValidationErrorDetail(artifact_name, None, "hashtable capacity must be positive"))
    if len(slots) != capacity:
        errors.append(ValidationErrorDetail(artifact_name, None, "hashtable slot count must equal capacity"))

    psls: list[int] = []
    occupied_count = 0
    seen_keys: set[str] = set()
    for index, slot in enumerate(slots):
        if slot is None:
            continue
        occupied_count += 1
        if not isinstance(slot, dict):
            errors.append(ValidationErrorDetail(artifact_name, None, f"slot {index} must be object or null"))
            continue
        key = slot.get("key")
        psl = slot.get("psl")
        if not isinstance(key, str) or key == "":
            errors.append(ValidationErrorDetail(artifact_name, None, f"slot {index} key must be non-empty string"))
            continue
        if key in seen_keys:
            errors.append(ValidationErrorDetail(artifact_name, None, f"duplicate hashtable key: {key}"))
        seen_keys.add(key)
        if not isinstance(slot.get("value"), dict):
            errors.append(ValidationErrorDetail(artifact_name, None, f"slot {index} value must be an object"))
        if not isinstance(psl, int) or isinstance(psl, bool) or psl < 0:
            errors.append(ValidationErrorDetail(artifact_name, None, f"slot {index} PSL must be a non-negative integer"))
            continue
        psls.append(psl)
        if capacity > 0 and psl != (index - _fnv1a_64(key) % capacity) % capacity:
            errors.append(ValidationErrorDetail(artifact_name, None, f"slot {index} PSL invariant failed"))

    if occupied_count != size:
        errors.append(ValidationErrorDetail(artifact_name, None, "hashtable size must equal occupied slot count"))

    return {
        "capacity": capacity,
        "size": size,
        "slot_count": len(slots),
        "hash_marker": hash_marker if isinstance(hash_marker, str) else "",
        "max_psl": max(psls) if psls else 0,
        "avg_psl": round(sum(psls) / len(psls), 4) if psls else 0.0,
        "empty_slots": len(slots) - occupied_count,
    }


def _validate_provenance_record(
    artifact_name: str,
    provenance: dict[str, Any] | None,
    sha256: str,
    stats: dict[str, Any],
    errors: list[ValidationErrorDetail],
) -> dict[str, Any] | None:
    if provenance is None:
        return None
    record = provenance.get(artifact_name)
    if not isinstance(record, dict):
        errors.append(ValidationErrorDetail(artifact_name, None, "missing provenance record for hashtable"))
        return None

    if record.get("sha256") != sha256:
        errors.append(ValidationErrorDetail(artifact_name, None, "hashtable SHA256 does not match provenance"))
    entries = record.get("entries")
    if not isinstance(entries, int) or isinstance(entries, bool):
        errors.append(ValidationErrorDetail(artifact_name, None, "provenance entries must be an integer"))
    elif entries != stats["size"]:
        errors.append(ValidationErrorDetail(artifact_name, None, "provenance entries do not match table size"))
    if not isinstance(record.get("source"), str) or record.get("source") == "":
        errors.append(ValidationErrorDetail(artifact_name, None, "provenance source must be a non-empty string"))

    provenance_stats = record.get("stats")
    if not isinstance(provenance_stats, dict):
        errors.append(ValidationErrorDetail(artifact_name, None, "provenance stats must be an object"))
        return record
    for field_name in ("capacity", "size", "max_psl", "empty_slots"):
        if provenance_stats.get(field_name) != stats[field_name]:
            errors.append(
                ValidationErrorDetail(
                    artifact_name,
                    None,
                    f"provenance stats.{field_name} does not match table",
                )
            )
    for field_name in ("load_factor", "avg_psl"):
        if field_name == "load_factor":
            expected = round(stats["size"] / stats["capacity"], 4) if stats["capacity"] else 0.0
        else:
            expected = stats["avg_psl"]
        if provenance_stats.get(field_name) != expected:
            errors.append(
                ValidationErrorDetail(
                    artifact_name,
                    None,
                    f"provenance stats.{field_name} does not match table",
                )
            )
    return record


def _int_field(
    artifact_name: str,
    frozen: dict[str, Any],
    field_name: str,
    errors: list[ValidationErrorDetail],
) -> int:
    value = frozen.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(ValidationErrorDetail(artifact_name, None, f"hashtable {field_name} must be an integer"))
        return 0
    return value


def _fnv1a_64(key: str) -> int:
    value = 0xCBF29CE484222325
    for byte in key.encode("utf-8"):
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return value


def _read_artifact(
    path: Path,
    errors: list[ValidationErrorDetail],
) -> _ArtifactAccumulator | None:
    source_corpus = path.name
    if source_corpus not in ALLOWED_SOURCE_CORPORA:
        errors.append(
            ValidationErrorDetail(source_corpus, None, "unexpected capability CSV corpus name")
        )
        return None

    try:
        content = path.read_bytes()
    except OSError as exc:
        errors.append(ValidationErrorDetail(source_corpus, None, f"cannot read CSV artifact: {exc}"))
        return None

    sha256 = hashlib.sha256(content).hexdigest()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        errors.append(ValidationErrorDetail(source_corpus, None, f"CSV artifact is not UTF-8: {exc}"))
        return _ArtifactAccumulator(path=path, source_corpus=source_corpus, sha256=sha256)
    accumulator = _ArtifactAccumulator(path=path, source_corpus=source_corpus, sha256=sha256)

    reader = csv.DictReader(text.splitlines(), restkey="__extra_fields__", restval=None)
    if tuple(reader.fieldnames or ()) != EXPECTED_CAPABILITY_COLUMNS:
        errors.append(
            ValidationErrorDetail(
                source_corpus,
                1,
                "CSV header does not exactly match capability_records import contract",
            )
        )
        return accumulator

    seen_entry_ids: dict[str, int] = {}
    for row_number, row in enumerate(reader, start=2):
        row_errors = _validate_row_shape(source_corpus, row_number, row, seen_entry_ids)
        errors.extend(row_errors)
        if row_errors:
            continue
        entry_id = row["entry_id"] or ""
        seen_entry_ids[entry_id] = row_number
        accumulator.rows.append(_planned_row(source_corpus, row_number, row))

    return accumulator


def _validate_row_shape(
    source_corpus: str,
    row_number: int,
    row: dict[str, str | list[str] | None],
    seen_entry_ids: dict[str, int],
) -> list[ValidationErrorDetail]:
    errors: list[ValidationErrorDetail] = []
    if row.get("__extra_fields__"):
        errors.append(ValidationErrorDetail(source_corpus, row_number, "CSV row has extra fields"))

    for column in EXPECTED_CAPABILITY_COLUMNS:
        value = row.get(column)
        if value is None:
            errors.append(ValidationErrorDetail(source_corpus, row_number, f"missing field: {column}"))
            continue
        if column in REQUIRED_TEXT_COLUMNS and value.strip() == "":
            errors.append(ValidationErrorDetail(source_corpus, row_number, f"blank required field: {column}"))
        if column in BOOLEAN_COLUMNS and value not in {"true", "false"}:
            errors.append(
                ValidationErrorDetail(source_corpus, row_number, f"malformed boolean field: {column}")
            )

    entry_id = row.get("entry_id")
    if isinstance(entry_id, str) and entry_id in seen_entry_ids:
        first_row = seen_entry_ids[entry_id]
        errors.append(
            ValidationErrorDetail(
                source_corpus,
                row_number,
                f"duplicate entry_id: {entry_id} first seen on row {first_row}",
            )
        )
    return errors


def _planned_row(
    source_corpus: str,
    row_number: int,
    row: dict[str, str | list[str] | None],
) -> PlannedCapabilityRow:
    row_values = {column: str(row[column]) for column in EXPECTED_CAPABILITY_COLUMNS}
    source_content_hash = _row_content_hash(row_values)
    row_values.update(
        {
            "source_corpus": source_corpus,
            "source_row_number": row_number,
            "source_content_hash": source_content_hash,
            "provenance_json": json.dumps(
                {"validator": "kolmafa.capability_import", "source_corpus": source_corpus},
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    )
    return PlannedCapabilityRow(values=row_values)


def _row_content_hash(row_values: dict[str, str]) -> str:
    canonical = json.dumps(
        {column: row_values[column] for column in EXPECTED_CAPABILITY_COLUMNS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
