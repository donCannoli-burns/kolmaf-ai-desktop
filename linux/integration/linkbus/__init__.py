"""LinkBus: provider manifests -> canonical kolmaf:// identities -> registry.

Slice 2 only. Read-only against installed plugin surfaces (existence checks);
writes only the generated registry tree. No network, no gameplay, no relay.
Stdlib only; imports nothing from kolmafa.
"""

from .validate import (
    AUTHORITY,
    EXPECTED_PROVIDER_IDS,
    FRESHNESS,
    RELATIONSHIPS,
    URI_RE,
    check_duplicates,
    check_expected,
    check_relationship_targets,
    check_targets_exist,
    collect_registered_uris,
    expand_target_path,
    load_manifests,
    resolve,
    validate_all,
    validate_manifest_structure,
)
from .compile_registry import (
    build_registry,
    compile_all,
    mark_exists,
    write_json_deterministic,
)

__all__ = [
    "AUTHORITY",
    "EXPECTED_PROVIDER_IDS",
    "FRESHNESS",
    "RELATIONSHIPS",
    "URI_RE",
    "build_registry",
    "check_duplicates",
    "check_expected",
    "check_relationship_targets",
    "check_targets_exist",
    "collect_registered_uris",
    "compile_all",
    "expand_target_path",
    "load_manifests",
    "mark_exists",
    "resolve",
    "validate_all",
    "validate_manifest_structure",
    "write_json_deterministic",
]
