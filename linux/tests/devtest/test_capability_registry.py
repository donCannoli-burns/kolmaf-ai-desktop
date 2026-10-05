"""Portable capability reconciliation tests (offline, fixtures only).

Repository-contained inputs only: committed source, synthetic fixtures, and
``tmp_path``. No operator installation state, no machine-local paths, no
conditional skips. Machine-local installation checks live in
``test_capability_registry_local.py`` (``local_runtime`` marker).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kolmafa.devtest.capability_registry import (
    advertisement_for_bootstrap,
    build_registry_entry,
    check_native_health,
    route_intent,
)


SHA = "6" * 64


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_registry_entry_conforms_and_marks_live_ready() -> None:
    entry = build_registry_entry(
        helper_sha256=SHA,
        helper_canonical="/c/don_native_can_equip.ash",
        helper_installed="/i/don_native_can_equip.ash",
    )
    assert entry["id"] == "native.can-equip"
    assert entry["provider"] == "don-runtime"
    assert entry["authority"] == "OBSERVATION_ONLY"
    assert entry["native_owner"] == "KoLmafia"
    assert entry["adapter_owner"] == "Don"
    assert entry["transport"]["type"] == "fixed-relay-get"
    assert entry["transport"]["method"] == "GET"
    assert entry["transport"]["caller_controls_function"] is False
    with pytest.raises(ValueError):
        build_registry_entry(helper_sha256="xyz", helper_canonical="/c", helper_installed="/i")


def test_health_ready_only_with_intact_files() -> None:
    canonical = Path("/c/helper.ash")
    installed = Path("/i/helper.ash")
    assert check_native_health(canonical=canonical, installed=installed, expected_sha256=SHA)["status"] in (
        "DEGRADED",
        "UNAVAILABLE",
    )


def test_health_rejects_hash_drift_and_missing_helper(tmp_path: Path) -> None:
    canonical = _write(tmp_path / "c" / "helper.ash", b"canonical")
    installed = _write(tmp_path / "i" / "helper.ash", b"different")
    drifted = check_native_health(canonical=canonical, installed=installed, expected_sha256="0" * 64)
    assert drifted["status"] == "DEGRADED"
    assert drifted["checks"]["hash_matches"] is False

    missing = check_native_health(
        canonical=canonical, installed=tmp_path / "i" / "gone.ash", expected_sha256="0" * 64
    )
    assert missing["status"] == "DEGRADED"
    assert missing["checks"]["installed_exists"] is False

    gone_source = check_native_health(
        canonical=tmp_path / "c" / "gone.ash", installed=installed, expected_sha256="0" * 64
    )
    assert gone_source["status"] == "UNAVAILABLE"


def test_health_requires_recognized_live_schema(tmp_path: Path) -> None:
    import hashlib

    canonical = _write(tmp_path / "c" / "helper.ash", b"canonical")
    installed = _write(tmp_path / "i" / "helper.ash", b"canonical")
    digest = hashlib.sha256(b"canonical").hexdigest()
    malformed = check_native_health(
        canonical=canonical,
        installed=installed,
        expected_sha256=digest,
        live_result={"capability": "native.can-equip", "status": "SUCCESS", "result": "yes"},
    )
    assert malformed["status"] == "DEGRADED"
    good = check_native_health(
        canonical=canonical,
        installed=installed,
        expected_sha256=digest,
        live_result={"capability": "native.can-equip", "status": "SUCCESS", "result": True},
    )
    assert good["status"] == "READY"
    no_probe = check_native_health(canonical=canonical, installed=installed, expected_sha256=digest)
    assert no_probe["status"] == "READY"


def test_bootstrap_advertises_ready_only_when_health_passes() -> None:
    assert advertisement_for_bootstrap("READY") == {
        "native.can-equip": {"status": "READY", "authority": "OBSERVATION_ONLY", "freshness": "LIVE"}
    }
    assert advertisement_for_bootstrap("DEGRADED") is None
    assert advertisement_for_bootstrap("UNAVAILABLE") is None


def test_routing_recognizes_equipability_intent() -> None:
    for text in (
        "Can I equip item 153?",
        "Can my character wear this?",
        "Is this equipment usable right now?",
    ):
        routed = route_intent(text)
        assert routed["route"] == "native.can-equip"
        assert routed["authority"] == "OBSERVATION_ONLY"


def test_routing_never_converts_mutation_into_observation() -> None:
    for text in ("equip this", "put this on", "change my hat", "unequip my hat"):
        routed = route_intent(text)
        assert routed["route"] == "don.propose-action"
        assert routed["authority"] == "T2"
    assert route_intent("")["route"] == "none"


def test_unknown_capabilities_remain_unavailable() -> None:
    from kolmafa.devtest.native_query import NativeQueryError, get_spec

    with pytest.raises(NativeQueryError):
        get_spec("native.some-future-query")


def test_module_has_no_execution_surface() -> None:
    text = (Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest" / "capability_registry.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("ActionBroker", "RelayWriter", "urlopen", "subprocess", "socket", "confirm_action", "sideCommand"):
        assert forbidden not in text


def test_portable_file_has_no_machine_local_dependencies() -> None:
    """Taxonomy guard: this portable file must not regain machine-local deps.

    Machine-local installation checks belong to
    ``test_capability_registry_local.py`` (``local_runtime`` marker), never
    here. If a forbidden token appears, the file was re-coupled to operator
    installation state and must be split again. The guard's own source is
    excluded from the scan because its forbidden-token list necessarily
    mentions the tokens it forbids.
    """
    import inspect

    text = Path(__file__).read_text(encoding="utf-8")
    text = text.replace(inspect.getsource(test_portable_file_has_no_machine_local_dependencies), "")
    for forbidden in ("Path.home(", ".kolmafia", ".local/share/kolmaf-ai", "KOLMAF_AGENT_BUNDLE"):
        assert forbidden not in text, f"portable capability test regained machine-local dependency: {forbidden}"
