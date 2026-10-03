"""Redacted evidence journal for Don Edition.

Simple append-only JSONL plus in-memory buffer for tests.
All payloads pass through redaction.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kolmafa.redaction import redact_mapping, redact_text

DEFAULT_EVIDENCE_PATH = Path(__file__).resolve().parents[3] / "logs" / "don-evidence.jsonl"


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(v) for v in value)
    return value


def record_evidence(
    operation: str,
    mode: str,
    source_component: str,
    result_summary: str,
    *,
    extra: dict[str, Any] | None = None,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    """Append a redacted evidence event and return the event dict."""

    event: dict[str, Any] = {
        "event_id": uuid.uuid4().hex,
        "timestamp": datetime.now(UTC).isoformat(),
        "operation": redact_text(operation),
        "mode": redact_text(mode),
        "source_component": redact_text(source_component),
        "result_summary": redact_text(result_summary),
    }
    if extra:
        event["extra"] = _redact_value(extra)

    path = evidence_path or DEFAULT_EVIDENCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
    return event
