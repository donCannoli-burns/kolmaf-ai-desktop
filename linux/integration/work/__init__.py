"""Work records: parse, validate, index, project (Slice 4).

Markdown under docs/{tasks,escalations,decisions,architecture}/ stays
authoritative. Everything generated is a deterministic projection written
atomically (build-then-replace; failures leave previous outputs intact).
Offline only. Stdlib plus linkbus URI vocabulary (consumed, never extended).
"""

from .records import (
    RECORD_KINDS,
    SOURCE_DIRS,
    load_all,
    parse_record,
)
from .validate import (
    ARCH_STATUS,
    DECISION_STATUS,
    ESC_CLASS,
    ESC_STATUS,
    TASK_STATUS,
    validate_all,
    validate_record,
)
from .build_index import compile_all as compile_index
from .build_matrix_overlay import (
    WORK_OVERLAY_SCHEMA,
    adapt_work_record,
    build_work_overlay,
    compile_all as compile_work_overlay,
)

__all__ = [
    "ARCH_STATUS",
    "DECISION_STATUS",
    "ESC_CLASS",
    "ESC_STATUS",
    "RECORD_KINDS",
    "SOURCE_DIRS",
    "TASK_STATUS",
    "WORK_OVERLAY_SCHEMA",
    "adapt_work_record",
    "build_work_overlay",
    "compile_index",
    "compile_work_overlay",
    "load_all",
    "parse_record",
    "validate_all",
    "validate_record",
]
