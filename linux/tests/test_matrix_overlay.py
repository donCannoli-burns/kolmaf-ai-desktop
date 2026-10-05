"""Matrix overlay Slice-3 tests (offline only).

Taxonomy:
- Unmarked tests are PORTABLE_CONTRACT: overlay-compiler semantics run
  against a portable registry derived from the committed source manifests
  (tests/fixtures/portable.py) and a SYNTHETIC minimal Matrix corpus
  (tests/fixtures/matrix/). No installed corpus, no generated
  data/runtime registry, no host paths.
- `external_integration` tests assert the real provider constellation
  composition (7 provider roots, 37 identities, 44 URIs) from the committed
  manifests via the repository-contained semantic registry
  (tests/fixtures/portable.py) plus the SYNTHETIC Matrix corpus. They need
  no host state.
- `local_runtime` tests assert against the real installed Matrix corpus
  (~/.kolmafia via the generated data/runtime registry): exact real-corpus
  counts (665 nodes / 13 workflows / 29 usecases), real mem:// grounding,
  and real install pins. These are never faked; they run only on the
  operator host.

Preservation: corpus counts/IDs/mem refs/provenance/workflows unchanged and
untouched by the builder. Projection: provider roots, targets, URIs,
authority never promoted, deterministic. Search: one shared substring path
covers Matrix + overlay. Negative: unknown/dup/malformed/missing inputs fail
loud or degrade without harming the corpus.
"""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integration"

sys.path.insert(0, str(INTEGRATION))
sys.path.insert(0, str(ROOT / "tests"))

from linkbus.validate import AUTHORITY, FRESHNESS, RELATIONSHIPS  # noqa: E402
import importlib  # noqa: E402

importlib.import_module("matrix.build_overlay")
importlib.import_module("matrix.validate_overlay")
B = sys.modules["matrix.build_overlay"]
V = sys.modules["matrix.validate_overlay"]

from fixtures.portable import (  # noqa: E402
    FIXTURE_ALIAS_GROUNDING,
    FIXTURE_NODE_COUNT,
    MATRIX_FIXTURE_HOME,
    portable_registry,
    write_portable_registry,
)

REGISTRY_PATH = ROOT / "data" / "runtime" / "linkbus" / "registry.json"
MANIFESTS_DIR = INTEGRATION / "providers"
OUT_DIR = ROOT / "data" / "runtime" / "matrix"

EXPECTED_PROVIDERS = {
    "kolmaf://provider/sandbox",
    "kolmaf://provider/tokens",
    "kolmaf://provider/memory",
    "kolmaf://provider/skills",
    "kolmaf://provider/ash-it-down",
    "kolmaf://provider/goblin",
    "kolmaf://provider/matrix",
}

MEM_REF = "mem://doc-3df3b27b3c87/0000#2ce7d49e050b"


# --- real (host) inputs: generated registry + installed corpus ----------------


def _registry():
    registry, err = B.load_registry(REGISTRY_PATH)
    assert err is None
    return registry


def _matrix_home(registry):
    home = B.matrix_home_from_registry(registry)
    assert home is not None and (home / "hyper-data.json").is_file()
    return home


def _built_overlay_real(tmp_path):
    registry = _registry()
    home = _matrix_home(registry)
    code, _ = B.compile_all(home, REGISTRY_PATH, MANIFESTS_DIR, tmp_path)
    assert code == 0
    return json.loads((tmp_path / "kolmaf-overlay.json").read_text(encoding="utf-8"))


# --- portable inputs: derived registry + synthetic fixture corpus --------------


def _portable_registry_path(tmp_path):
    return write_portable_registry(tmp_path / "registry.json")


def _portable_registry(tmp_path):
    return json.loads(_portable_registry_path(tmp_path).read_text(encoding="utf-8"))


def _built_overlay(tmp_path):
    registry_path = _portable_registry_path(tmp_path)
    code, _ = B.compile_all(MATRIX_FIXTURE_HOME, registry_path, MANIFESTS_DIR, tmp_path / "out")
    assert code == 0
    return json.loads((tmp_path / "out" / "kolmaf-overlay.json").read_text(encoding="utf-8"))


def _corpus_hashes(home):
    return {
        name: hashlib.sha256((home / name).read_bytes()).hexdigest()
        for name in B.CORPUS_FILES
    }


# --- preservation: real installed corpus (local runtime) ------------------------


@pytest.mark.local_runtime
def test_corpus_baseline_matches():
    registry = _registry()
    summary, err = B.summarize_corpus(_matrix_home(registry))
    assert err is None
    assert summary is not None
    for key, value in B.MATRIX_BASELINE.items():
        assert summary[key] == value, key
    assert summary["distinct_mem_pointers"] == 665


@pytest.mark.local_runtime
def test_builder_does_not_touch_corpus(tmp_path):
    registry = _registry()
    home = _matrix_home(registry)
    before = _corpus_hashes(home)
    code, _ = B.compile_all(home, REGISTRY_PATH, MANIFESTS_DIR, tmp_path)
    assert code == 0
    assert _corpus_hashes(home) == before


@pytest.mark.local_runtime
def test_source_manifest_pins_intact():
    registry = _registry()
    home = _matrix_home(registry)
    manifest = json.loads((home / "source-manifest.json").read_text(encoding="utf-8"))
    matrix_sha = manifest["matrix"]["sha256"]
    agent_sha = manifest["agent_plane"]["hyper_data"]["sha256"]
    assert len(matrix_sha) == 64 and len(agent_sha) == 64


@pytest.mark.local_runtime
def test_real_corpus_pointer_grounding(tmp_path):
    overlay = _built_overlay_real(tmp_path)
    registry = _registry()
    home = _matrix_home(registry)
    pointers = B.corpus_pointer_index(home)
    assert pointers[MEM_REF] == "ash:src-packagecontrol"
    by_pointer = {a["mem_pointer"]: a for a in overlay["aliases"]}
    assert by_pointer["mem://doc-fdd0fc84c469/0023#91b7df967bf7"]["matrix_node_id"] == (
        "js:data-of-loathing"
    )
    assert by_pointer["mem://doc-fdd0fc84c469/0024#7e1ef8627fef"]["matrix_node_id"] == (
        "js:data-loathers-service"
    )


# --- preservation: portable fixture corpus ---------------------------------------


def test_fixture_corpus_summary_matches_fixture_contract():
    summary, err = B.summarize_corpus(MATRIX_FIXTURE_HOME)
    assert err is None
    assert summary is not None
    assert summary["nodes"] == FIXTURE_NODE_COUNT
    assert summary["unique_ids"] == FIXTURE_NODE_COUNT
    assert summary["mem_pointers"] == FIXTURE_NODE_COUNT
    assert summary["distinct_mem_pointers"] == FIXTURE_NODE_COUNT


def test_compile_does_not_touch_fixture_corpus(tmp_path):
    before = _corpus_hashes(MATRIX_FIXTURE_HOME)
    code, _ = B.compile_all(
        MATRIX_FIXTURE_HOME, _portable_registry_path(tmp_path), MANIFESTS_DIR, tmp_path / "out"
    )
    assert code == 0
    assert _corpus_hashes(MATRIX_FIXTURE_HOME) == before


def test_fixture_manifest_pins_shaped():
    manifest = json.loads(
        (MATRIX_FIXTURE_HOME / "source-manifest.json").read_text(encoding="utf-8")
    )
    matrix_sha = manifest["matrix"]["sha256"]
    agent_sha = manifest["agent_plane"]["hyper_data"]["sha256"]
    assert len(matrix_sha) == 64 and len(agent_sha) == 64


# --- projection: real provider constellation (integration profile) --------------
# Repository-contained: the 7-provider / 37-identity / 44-URI constellation
# is a property of the committed manifests (integration/providers) plus the
# synthetic Matrix corpus (tests/fixtures/matrix). These tests compile the
# overlay from write_portable_registry + MATRIX_FIXTURE_HOME so they validate
# the integration surface itself with zero dependency on host state.


@pytest.mark.external_integration
def test_seven_provider_roots(tmp_path):
    overlay = _built_overlay(tmp_path)
    assert overlay["schema"] == "kolmaf-overlay/v1"
    assert overlay["status"] == "active"
    assert overlay["root"]["overlay_id"] == "kolmaf-constellation"
    assert overlay["root"]["title"] == "KOLMAF-AI CONSTELLATION"
    assert overlay["root"]["uri"] is None
    assert {n["uri"] for n in overlay["providers"]} == EXPECTED_PROVIDERS
    assert len(overlay["root"]["children"]) == 7


@pytest.mark.external_integration
def test_37_targets_44_uris_resolvable(tmp_path):
    overlay = _built_overlay(tmp_path)
    assert overlay["counts"]["providers"] == 7
    assert overlay["counts"]["identities"] == 37
    registry = portable_registry()
    expected = set(registry["identities"]) | {p["uri"] for p in registry["providers"]}
    assert len(expected) == 44
    for uri in expected:
        node, err = B.resolve_overlay(overlay, uri)
        assert err is None, uri
        assert node is not None and node["uri"] == uri


def test_external_constellation_uses_repository_contained_inputs():
    """Mixed-evidence regression: constellation assertions stay portable.

    The two external_integration constellation tests must compile from the
    repository-contained semantic registry plus the synthetic Matrix corpus.
    They must not consume the host-runtime chain (REGISTRY_PATH /
    _built_overlay_real / _matrix_home / installed-corpus helpers) for the
    provider-constellation assertions. Host-runtime helpers remain for the
    local_runtime corpus tests only.
    """
    import inspect

    helper_src = inspect.getsource(_built_overlay)
    assert "MATRIX_FIXTURE_HOME" in helper_src
    assert "write_portable_registry" in helper_src or "_portable_registry_path" in helper_src
    assert "REGISTRY_PATH" not in helper_src
    assert "_matrix_home" not in helper_src
    for fn in (test_seven_provider_roots, test_37_targets_44_uris_resolvable):
        src = inspect.getsource(fn)
        cleaned = src.replace("_portable_registry", "").replace("portable_registry", "")
        assert "_built_overlay_real" not in src, fn.__name__
        assert "_matrix_home" not in src, fn.__name__
        assert "REGISTRY_PATH" not in src, fn.__name__
        assert "_registry" not in cleaned, fn.__name__
        assert "_built_overlay(" in src, fn.__name__


# --- projection: portable compiler semantics --------------------------------------


def test_overlay_shape_and_root(tmp_path):
    overlay = _built_overlay(tmp_path)
    assert overlay["schema"] == "kolmaf-overlay/v1"
    assert overlay["status"] == "active"
    assert overlay["root"]["overlay_id"] == "kolmaf-constellation"
    assert overlay["root"]["title"] == "KOLMAF-AI CONSTELLATION"
    assert overlay["root"]["uri"] is None
    assert len(overlay["root"]["children"]) == len(overlay["providers"])
    assert all(n["uri"].startswith("kolmaf://provider/") for n in overlay["providers"])


def test_all_registered_uris_resolvable(tmp_path):
    overlay = _built_overlay(tmp_path)
    registry = _portable_registry(tmp_path)
    expected = set(registry["identities"]) | {p["uri"] for p in registry["providers"]}
    assert overlay["counts"]["providers"] == len(registry["providers"])
    assert overlay["counts"]["identities"] == len(registry["identities"])
    for uri in expected:
        node, err = B.resolve_overlay(overlay, uri)
        assert err is None, uri
        assert node is not None and node["uri"] == uri


def test_no_duplicates_no_unknown_enums(tmp_path):
    overlay = _built_overlay(tmp_path)
    registry = _portable_registry(tmp_path)
    pointers = set(B.corpus_pointer_index(MATRIX_FIXTURE_HOME))
    assert V.validate_overlay(overlay, registry, pointers) == []
    for node in overlay["providers"] + overlay["identities"]:
        assert node["authority"] in AUTHORITY
        assert node["freshness"] in FRESHNESS
        for rel in node.get("relationships", []):
            assert rel["type"] in RELATIONSHIPS


def test_authority_never_promoted(tmp_path):
    overlay = _built_overlay(tmp_path)
    registry = _portable_registry(tmp_path)
    by_uri = {p["uri"]: p["authority"] for p in registry["providers"]}
    by_uri.update(
        {uri: next(p["authority"] for p in registry["providers"]
                   if p["id"] == e["provider"])
         for uri, e in registry["identities"].items()}
    )
    for node in overlay["providers"] + overlay["identities"]:
        assert node["authority"] == by_uri[node["uri"]], node["uri"]


def test_overlay_deterministic(tmp_path):
    first = _built_overlay(tmp_path / "a")
    second = _built_overlay(tmp_path / "b")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_representative_resolutions(tmp_path):
    overlay = _built_overlay(tmp_path)
    node, err = B.resolve_overlay(overlay, "kolmaf://provider/matrix")
    assert err is None and node["overlay_id"] == "kolmaf-provider-kol-html-matrix"
    assert node["authority"] == "NAVIGATION_ONLY"
    node, err = B.resolve_overlay(overlay, "kolmaf://tokens/item/153")
    assert err is None and node["provider"] == "tokens-of-loathing"
    node, err = B.resolve_overlay(overlay, "kolmaf://memory/runtime")
    assert err is None and node["provider"] == "kol-agent-memory"


def test_aliases_grounded(tmp_path):
    overlay = _built_overlay(tmp_path)
    registry = _portable_registry(tmp_path)
    registered = set(registry["identities"]) | {p["uri"] for p in registry["providers"]}
    pointers = set(B.corpus_pointer_index(MATRIX_FIXTURE_HOME))
    assert len(overlay["aliases"]) >= 2
    by_pointer = {a["mem_pointer"]: a for a in overlay["aliases"]}
    for mem_pointer, matrix_node_id in FIXTURE_ALIAS_GROUNDING.items():
        assert by_pointer[mem_pointer]["matrix_node_id"] == matrix_node_id
    for alias in overlay["aliases"]:
        assert alias["mem_pointer"] in pointers
        assert alias["kolmaf_uri"] in registered


# --- search / discovery ---------------------------------------------------------


def _combined_records(tmp_path):
    overlay = _built_overlay(tmp_path)
    records = [B.adapt_matrix_node(n) for n in B.load_corpus_nodes(MATRIX_FIXTURE_HOME)]
    records += [B.adapt_overlay_node(n) for n in overlay["providers"] + overlay["identities"]]
    return records


def test_discovery_queries(tmp_path):
    records = _combined_records(tmp_path)
    expectations = {
        "memory": "kolmaf://provider/memory",
        "sandbox": "kolmaf://provider/sandbox",
        "skills": "kolmaf://provider/skills",
        "tokens": "kolmaf://provider/tokens",
        "docs": "kolmaf://provider/goblin",
        "doc_edit": "kolmaf://provider/ash-it-down",
        "ash": "kolmaf://provider/ash-it-down",
    }
    for query, uri in expectations.items():
        hits = B.search_records(records, query)
        assert any(h["ref"] == uri for h in hits), query


def test_shared_path_covers_matrix_and_overlay(tmp_path):
    records = _combined_records(tmp_path)
    matrix_hits = B.search_records(records, "sublime")
    assert any(h["kind"] == "matrix" for h in matrix_hits)
    target_hits = B.search_records(records, "item/153")
    assert any(
        h["kind"] == "target" and h["ref"] == "kolmaf://tokens/item/153"
        for h in target_hits
    )
    both = B.search_records(records, "kolmaf")
    assert any(h["kind"] in ("provider", "target") for h in both)


# --- negative ---------------------------------------------------------------------


def test_unknown_uri_not_found(tmp_path):
    overlay = _built_overlay(tmp_path)
    node, err = B.resolve_overlay(overlay, "kolmaf://provider/ghost")
    assert node is None and err is not None and err["code"] == "NOT_FOUND"


def test_duplicate_overlay_uri_flagged(tmp_path):
    overlay = _built_overlay(tmp_path)
    registry = _portable_registry(tmp_path)
    dup = copy.deepcopy(overlay)
    dup["identities"].append(copy.deepcopy(dup["identities"][0]))
    errors = V.validate_overlay(dup, registry, set(B.corpus_pointer_index(MATRIX_FIXTURE_HOME)))
    assert any(e["code"] == "DUPLICATE_URI" for e in errors)


def test_registry_unknown_provider_refused(tmp_path):
    registry = _portable_registry(tmp_path)
    tampered = copy.deepcopy(registry)
    tampered["providers"][0]["relationships"].append(
        {"type": "REFERENCES", "target": "kolmaf://provider/ghost"}
    )
    tampered_path = tmp_path / "registry.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    code, result = B.compile_all(
        MATRIX_FIXTURE_HOME, tampered_path, MANIFESTS_DIR, tmp_path / "out"
    )
    assert code == 1
    assert any(e["code"] == "UNKNOWN_URI" for e in result["errors"])
    assert not (tmp_path / "out" / "kolmaf-overlay.json").exists()


def test_unknown_relation_type_refused(tmp_path):
    registry = _portable_registry(tmp_path)
    tampered = copy.deepcopy(registry)
    tampered["providers"][0]["relationships"].append(
        {"type": "FROBNICATES", "target": "kolmaf://provider/memory"}
    )
    tampered_path = tmp_path / "registry.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    code, result = B.compile_all(
        MATRIX_FIXTURE_HOME, tampered_path, MANIFESTS_DIR, tmp_path / "out"
    )
    assert code == 1
    assert any(e["code"] == "UNKNOWN_RELATIONSHIP" for e in result["errors"])


def test_malformed_registry_refused(tmp_path):
    bad = tmp_path / "registry.json"
    bad.write_text("{not json", encoding="utf-8")
    code, result = B.compile_all(MATRIX_FIXTURE_HOME, bad, MANIFESTS_DIR, tmp_path / "out")
    assert code == 1
    assert result["errors"][0]["code"] == "INVALID_REGISTRY"
    assert not (tmp_path / "out" / "kolmaf-overlay.json").exists()


def test_missing_registry_degraded_corpus_safe(tmp_path):
    before = _corpus_hashes(MATRIX_FIXTURE_HOME)
    missing = tmp_path / "no-registry.json"
    code, result = B.compile_all(MATRIX_FIXTURE_HOME, missing, MANIFESTS_DIR, tmp_path / "out")
    assert code == 3
    assert result["code"] == "REGISTRY_MISSING"
    degraded = json.loads((tmp_path / "out" / "kolmaf-overlay.json").read_text())
    assert degraded["status"] == "degraded" and degraded["providers"] == []
    assert _corpus_hashes(MATRIX_FIXTURE_HOME) == before
    summary, err = B.summarize_corpus(MATRIX_FIXTURE_HOME)
    assert err is None and summary["nodes"] == FIXTURE_NODE_COUNT


def test_overlay_isolation():
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
    secrets = ("service.token", "cookies", "password")
    import_pattern = re.compile(r"^\s*(import|from)\s+kolmafa", re.MULTILINE)
    for name in ("build_overlay.py", "validate_overlay.py", "__init__.py"):
        source = (INTEGRATION / "matrix" / name).read_text(encoding="utf-8")
        for token in banned + secrets:
            assert token not in source, f"{name} contains {token!r}"
        assert not import_pattern.search(source), f"{name} imports kolmafa"
