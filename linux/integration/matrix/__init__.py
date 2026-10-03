"""Matrix overlay adapter package (Slice 3).

Re-exports the builder and validator. See build_overlay.py and
validate_overlay.py. Read-only against Matrix corpus + LinkBus registry;
writes only the generated Don-side overlay tree.
"""

from .build_overlay import (
    ALIAS_MATCH_STRINGS,
    CORPUS_FILES,
    MATRIX_BASELINE,
    OVERLAY_SCHEMA,
    ROOT_ID,
    ROOT_TITLE,
    adapt_matrix_node,
    adapt_overlay_node,
    build_aliases,
    build_overlay,
    compile_all,
    corpus_pointer_index,
    degraded_overlay,
    discovery_keywords,
    load_manifests_by_id,
    load_registry,
    matrix_home_from_registry,
    overlay_id_for,
    overlay_id_for_provider,
    overlay_id_for_uri,
    resolve_overlay,
    search_records,
    summarize_corpus,
)
from .validate_overlay import validate_overlay

__all__ = [
    "ALIAS_MATCH_STRINGS",
    "CORPUS_FILES",
    "MATRIX_BASELINE",
    "OVERLAY_SCHEMA",
    "ROOT_ID",
    "ROOT_TITLE",
    "adapt_matrix_node",
    "adapt_overlay_node",
    "build_aliases",
    "build_overlay",
    "compile_all",
    "corpus_pointer_index",
    "degraded_overlay",
    "discovery_keywords",
    "load_manifests_by_id",
    "load_registry",
    "matrix_home_from_registry",
    "overlay_id_for",
    "overlay_id_for_provider",
    "overlay_id_for_uri",
    "resolve_overlay",
    "search_records",
    "summarize_corpus",
    "validate_overlay",
]
