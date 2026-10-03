"""LinkBus Slice-2 contract tests (offline only).

Taxonomy:
- Unmarked tests are PORTABLE_CONTRACT: they read only committed repository
  source (integration/providers, integration/schemas) or synthetic tmp_path
  documents, and never probe installed targets.
- `external_integration` tests assert the real provider constellation
  composition (7 manifests, expected provider set, 7/37 registry counts).
- `local_runtime` tests probe machine-local installed provider targets
  (e.g. ~/.kolmafia); they cannot pass on a clean CI checkout.

Positive: manifests load, unique provider URIs, schemas/enums valid,
registry deterministic, resolution works. Negative: missing targets,
duplicates, malformed URIs, unknown enums/refs. Isolation: linkbus sources
touch no network/relay/gameplay surfaces.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integration"
PROVIDERS = INTEGRATION / "providers"
SCHEMAS = INTEGRATION / "schemas"

sys.path.insert(0, str(INTEGRATION))

from linkbus import compile_registry as C  # noqa: E402
from linkbus import validate as V  # noqa: E402


def _base_doc(target_file: Path, pid="test-provider", uri="kolmaf://provider/test"):
    target_file.write_text("x", encoding="utf-8")
    return {
        "schema": "kolmaf-provider/v1",
        "id": pid,
        "name": "Test",
        "uri": uri,
        "authority": "REFERENCE_ONLY",
        "targets": [
            {"uri": uri + "/surface", "path": str(target_file), "required": True}
        ],
        "relationships": [],
    }


def _codes(errors):
    return {e["code"] for e in errors}


# --- positive: real provider constellation (integration profile) ---------------


@pytest.mark.external_integration
def test_seven_manifests_load():
    docs, errors, files = V.load_manifests(PROVIDERS)
    assert errors == []
    assert len(docs) == 7
    assert files == sorted(files)


@pytest.mark.external_integration
def test_expected_ids_present():
    docs, errors, _ = V.load_manifests(PROVIDERS)
    assert V.check_expected(docs) == []
    assert errors == []


@pytest.mark.external_integration
def test_registry_deterministic(tmp_path):
    docs, errors, _ = V.load_manifests(PROVIDERS)
    assert errors == []
    first = C.mark_exists(C.build_registry(docs))
    second = C.mark_exists(C.build_registry(docs))
    assert C.write_json_deterministic(tmp_path / "a.json", first) == C.write_json_deterministic(
        tmp_path / "b.json", second
    )
    assert first["counts"] == {"providers": 7, "identities": 37}


# --- positive: portable contract (committed source only) -----------------------


def test_unique_canonical_provider_uris():
    docs, _, _ = V.load_manifests(PROVIDERS)
    uris = [d["uri"] for d in docs]
    assert len(set(uris)) == len(uris)
    assert V.check_duplicates(docs) == []


def test_schema_files_valid_and_cover_vocab():
    for name in ("provider-v1.schema.json", "registry-v1.schema.json"):
        schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
        assert schema["type"] == "object"
        assert "required" in schema
    provider_schema = json.loads((SCHEMAS / "provider-v1.schema.json").read_text())
    props = provider_schema["properties"]
    assert set(props["authority"]["enum"]) == set(V.AUTHORITY)
    assert set(props["freshness"]["enum"]) == set(V.FRESHNESS)
    rel_enum = props["relationships"]["items"]["properties"]["type"]["enum"]
    assert set(rel_enum) == set(V.RELATIONSHIPS)


def test_full_structural_validation_clean():
    _, errors, _ = V.validate_all(PROVIDERS)
    assert errors == []


def test_resolve_registered_uris():
    docs, _, _ = V.load_manifests(PROVIDERS)
    registry = C.mark_exists(C.build_registry(docs))
    entry, err = V.resolve("kolmaf://provider/matrix", registry)
    assert err is None
    assert entry["provider"] == "kol-html-matrix"
    entry, err = V.resolve("kolmaf://tokens/item/153", registry)
    assert err is None
    assert entry["provider"] == "tokens-of-loathing"


def test_registry_matches_schema_shape():
    docs, _, _ = V.load_manifests(PROVIDERS)
    registry = C.mark_exists(C.build_registry(docs))
    schema = json.loads((SCHEMAS / "registry-v1.schema.json").read_text(encoding="utf-8"))
    assert registry["schema"] == schema["properties"]["schema"]["const"]
    assert set(registry) >= set(schema["required"])
    for uri, entry in registry["identities"].items():
        assert uri.startswith("kolmaf://")
        assert set(entry) >= {"provider", "path", "required", "exists"}


# --- positive: installed-target probes (machine-local state) -------------------


@pytest.mark.local_runtime
def test_required_targets_resolve():
    docs, _, _ = V.load_manifests(PROVIDERS)
    for doc in docs:
        missing_required, _ = V.check_targets_exist(doc)
        assert missing_required == [], doc["id"]


@pytest.mark.local_runtime
def test_installed_target_exists_for_known_uri():
    docs, _, _ = V.load_manifests(PROVIDERS)
    registry = C.mark_exists(C.build_registry(docs))
    entry, err = V.resolve("kolmaf://tokens/item/153", registry)
    assert err is None
    assert entry["provider"] == "tokens-of-loathing"
    assert entry["exists"] is True


# --- negative: synthetic fixtures only --------------------------------------


def test_missing_required_target(tmp_path):
    doc = _base_doc(tmp_path / "present.txt")
    doc["targets"].append(
        {"uri": "kolmaf://provider/test/gone", "path": str(tmp_path / "gone.txt"),
         "required": True}
    )
    missing_required, _ = V.check_targets_exist(doc)
    assert len(missing_required) == 1
    assert missing_required[0]["uri"] == "kolmaf://provider/test/gone"


def test_duplicate_id(tmp_path):
    docs = [
        _base_doc(tmp_path / "a.txt", pid="dup", uri="kolmaf://provider/dup-a"),
        _base_doc(tmp_path / "b.txt", pid="dup", uri="kolmaf://provider/dup-b"),
    ]
    assert "DUPLICATE_ID" in _codes(V.check_duplicates(docs))


def test_duplicate_uri(tmp_path):
    docs = [
        _base_doc(tmp_path / "a.txt", pid="dup-a", uri="kolmaf://provider/dup"),
        _base_doc(tmp_path / "b.txt", pid="dup-b", uri="kolmaf://provider/dup"),
    ]
    assert "DUPLICATE_URI" in _codes(V.check_duplicates(docs))


def test_malformed_uris(tmp_path):
    doc = _base_doc(tmp_path / "t.txt")
    doc["uri"] = "http://provider/test"
    doc["targets"][0]["uri"] = "kolmaf:/bad"
    codes = _codes(V.validate_manifest_structure(doc, "t.json"))
    assert "INVALID_URI" in codes


def test_unknown_authority(tmp_path):
    doc = _base_doc(tmp_path / "t.txt")
    doc["authority"] = "GOD_MODE"
    assert "UNKNOWN_AUTHORITY" in _codes(V.validate_manifest_structure(doc, "t.json"))


def test_unknown_relationship_target(tmp_path):
    doc = _base_doc(tmp_path / "t.txt")
    doc["relationships"] = [{"type": "REFERENCES", "target": "kolmaf://provider/ghost"}]
    assert "UNKNOWN_URI" in _codes(V.check_relationship_targets([doc]))


def test_resolve_unknown_uri():
    entry, err = V.resolve("kolmaf://provider/ghost", {"identities": {}, "providers": []})
    assert entry is None
    assert err is not None
    assert err["code"] == "NOT_FOUND"


def test_linkbus_isolation():
    import re

    banned = (
        "socket",
        "urllib",
        "requests",
        "http.client",
        "subprocess",
        "RelayWriter",
        "sideCommand",
    )
    import_pattern = re.compile(r"^\s*(import|from)\s+kolmafa", re.MULTILINE)
    for name in ("validate.py", "compile_registry.py", "__init__.py"):
        source = (INTEGRATION / "linkbus" / name).read_text(encoding="utf-8")
        for token in banned:
            assert token not in source, f"{name} contains {token!r}"
        assert not import_pattern.search(source), f"{name} imports kolmafa"
