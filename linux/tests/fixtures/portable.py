"""Portable LinkBus/Matrix fixture helpers.

Repository-contained only: builds a kolmaf-registry/v1 registry from the
committed source manifests in integration/providers/, with every identity
path replaced by a non-filesystem placeholder and `exists` forced False.

Rationale: the source manifest carries the portable semantic identity
(provider id, kolmaf:// URIs, authority, relationships). The installed
target location (/home/... or ~/.kolmafia/...) is machine-local resolved
state and must not leak into portable tests. No network, no host probes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "integration"

if str(INTEGRATION) not in sys.path:
    sys.path.insert(0, str(INTEGRATION))

from linkbus import compile_registry as _compile  # noqa: E402
from linkbus import validate as _validate  # noqa: E402

PROVIDERS_DIR = INTEGRATION / "providers"
SCHEMAS_DIR = INTEGRATION / "schemas"

# SYNTHETIC minimal Matrix corpus (hand-authored; not copied from the
# installed corpus). See tests/fixtures/__init__.py.
MATRIX_FIXTURE_HOME = Path(__file__).resolve().parent / "matrix"

# Synthetic corpus contract (kept in sync with matrix/hyper-data.json).
FIXTURE_NODE_COUNT = 6
FIXTURE_ALIAS_GROUNDING = {
    "mem://fixture/0000#aa11": "fx:data-of-loathing",
    "mem://fixture/0001#bb22": "fx:data-loathers-service",
}

_PLACEHOLDER_PREFIX = "portable-fixture-no-host-path:"


def load_source_manifests() -> list[dict]:
    """Load the committed provider manifests; fail loud on any error."""
    docs, errors, _ = _validate.load_manifests(PROVIDERS_DIR)
    assert errors == [], errors
    return docs


def portable_registry() -> dict:
    """Registry built from committed manifests with host paths stripped.

    Every identity keeps its portable semantic identity (uri, provider,
    required, kind); the machine-local resolved path is replaced by a
    placeholder and `exists` is False because no installed target is probed.
    """
    registry = _compile.build_registry(load_source_manifests())
    for uri, entry in registry["identities"].items():
        entry["path"] = _PLACEHOLDER_PREFIX + str(uri)
        entry["exists"] = False
    for provider in registry["providers"]:
        for identity in provider["identities"]:
            identity["path"] = _PLACEHOLDER_PREFIX + str(identity["uri"])
            identity["exists"] = False
    return registry


def write_portable_registry(path: Path) -> Path:
    """Write the portable registry to `path` (typically under tmp_path)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(portable_registry(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(data)
    return path
