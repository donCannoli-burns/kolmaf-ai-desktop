"""Regression tests for the public-portable commissioning checkpoint verifier.

These tests prove that the portable checkpoint is repository-only: it passes
from committed public content, fails cleanly on any drift, and never depends
on machine-local runtime state (installed helper, provider health, live
results, local bootstrap, or the receipt journal).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]  # linux/
VERIFIER = REPO_ROOT / "scripts" / "verify_native_can_equip_checkpoint.py"
ATTESTATION = REPO_ROOT / "docs" / "commissioning" / "native-can-equip-t1-public.json"
HELPER = REPO_ROOT / "src" / "kolmafa" / "devtest" / "relay" / "don_native_can_equip.ash"
REGISTRY = REPO_ROOT / "src" / "kolmafa" / "devtest" / "capability_registry.py"

EXPECTED_HELPER_SHA = "666c8abd92935cabd7d9099b45e2d92814e9dced0e2540ee6d97614d77648944"

# Portable mode must never reference machine-local or generated state.
FORBIDDEN_PORTABLE_TOKENS = (
    "agentflow/runtime",
    "data/capabilities/registry.json",
    "provider-health.json",
    "~/.kolmafia",
    "logs/don-evidence.jsonl",
)


def _copy_project(dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    shutil.copytree(
        REPO_ROOT / "src", dest / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(
        REPO_ROOT / "tests" / "devtest",
        dest / "tests" / "devtest",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (dest / "docs" / "commissioning").mkdir(parents=True)
    shutil.copy2(
        ATTESTATION, dest / "docs" / "commissioning" / "native-can-equip-t1-public.json"
    )
    shutil.copy2(REPO_ROOT / "IMPORT_PROVENANCE.md", dest / "IMPORT_PROVENANCE.md")
    return dest


@pytest.fixture(scope="session")
def base_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _copy_project(tmp_path_factory.mktemp("checkpoint-base") / "proj")


@pytest.fixture()
def project(tmp_path: Path, base_project: Path) -> Path:
    dest = tmp_path / "proj"
    shutil.copytree(base_project, dest)
    return dest


def run_verifier(
    project_root: Path,
    mode: str = "portable",
    env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(VERIFIER), "--mode", mode, "--project-root", str(project_root)]
    if extra_args:
        cmd += extra_args
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, env=run_env)


# ---------------------------------------------------------------------------
# Positive: portable mode passes from repository content only.
# ---------------------------------------------------------------------------


def test_portable_verifier_passes_on_repository() -> None:
    result = run_verifier(REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PORTABLE CHECKPOINT VALID" in result.stdout
    assert "FAIL" not in result.stdout


def test_portable_verifier_passes_on_clean_copy(project: Path) -> None:
    result = run_verifier(project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PORTABLE CHECKPOINT VALID" in result.stdout
    assert "FAIL" not in result.stdout


def test_portable_mode_needs_no_local_state(tmp_path: Path) -> None:
    # Empty HOME proves no ~/.kolmafia dependency; a nonexistent runtime root
    # proves no generated-runtime dependency. Portable mode must still pass and
    # must never assert local readiness claims.
    empty_home = tmp_path / "home"
    empty_home.mkdir()
    result = run_verifier(
        REPO_ROOT,
        env={
            "HOME": str(empty_home),
            "KOLMAF_RUNTIME_ROOT": str(tmp_path / "nonexistent-runtime"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PORTABLE CHECKPOINT VALID" in result.stdout
    # Portable mode must not assert provider READY, installed helper existence,
    # live SUCCESS, or local bootstrap READY.
    assert "READY" not in result.stdout
    assert "provider health" not in result.stdout
    assert "installed helper" not in result.stdout


# ---------------------------------------------------------------------------
# Negative: portable mode fails cleanly on any drift.
# ---------------------------------------------------------------------------


def test_missing_attestation_fails_cleanly(project: Path) -> None:
    (project / "docs" / "commissioning" / "native-can-equip-t1-public.json").unlink()
    result = run_verifier(project)
    assert result.returncode != 0
    assert "PORTABLE CHECKPOINT INVALID" in result.stdout
    assert "FAIL attestation parses" in result.stdout


def test_missing_canonical_helper_fails(project: Path) -> None:
    (project / "src" / "kolmafa" / "devtest" / "relay" / "don_native_can_equip.ash").unlink()
    result = run_verifier(project)
    assert result.returncode != 0
    assert "FAIL canonical helper exists" in result.stdout


def test_helper_hash_altered_fails(project: Path) -> None:
    helper = project / "src" / "kolmafa" / "devtest" / "relay" / "don_native_can_equip.ash"
    helper.write_text(helper.read_text(encoding="utf-8") + "\n// drift\n", encoding="utf-8")
    result = run_verifier(project)
    assert result.returncode != 0
    assert "FAIL canonical helper hash matches attestation" in result.stdout


def _mutate_registry(project: Path, old: str, new: str) -> None:
    path = project / "src" / "kolmafa" / "devtest" / "capability_registry.py"
    text = path.read_text(encoding="utf-8")
    assert old in text, f"mutation anchor not found: {old!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_capability_id_altered_fails(project: Path) -> None:
    _mutate_registry(
        project, 'NATIVE_CAN_EQUIP_ID = "native.can-equip"', 'NATIVE_CAN_EQUIP_ID = "native.can-equip-drifted"'
    )
    result = run_verifier(project)
    assert result.returncode != 0
    assert "FAIL registry NATIVE_CAN_EQUIP_ID" in result.stdout


def test_authority_altered_fails(project: Path) -> None:
    _mutate_registry(
        project,
        'OBSERVATION_AUTHORITY = "OBSERVATION_ONLY"',
        'OBSERVATION_AUTHORITY = "OBSERVATION_ONLY_DRIFTED"',
    )
    result = run_verifier(project)
    assert result.returncode != 0
    assert "FAIL registry OBSERVATION_AUTHORITY" in result.stdout


def test_transport_type_altered_fails(project: Path) -> None:
    _mutate_registry(project, '"type": "fixed-relay-get",', '"type": "fixed-relay-post",')
    result = run_verifier(project)
    assert result.returncode != 0
    assert "FAIL constructed entry transport type" in result.stdout


def test_transport_method_altered_fails(project: Path) -> None:
    _mutate_registry(project, '"method": "GET",', '"method": "POST",')
    result = run_verifier(project)
    assert result.returncode != 0
    assert "FAIL constructed entry transport method" in result.stdout


def test_caller_controls_altered_fails(project: Path) -> None:
    _mutate_registry(project, '"caller_controls_code": False,', '"caller_controls_code": True,')
    result = run_verifier(project)
    assert result.returncode != 0
    assert "FAIL constructed entry caller controls nothing" in result.stdout


def test_provenance_disagrees_fails(project: Path) -> None:
    attestation = project / "docs" / "commissioning" / "native-can-equip-t1-public.json"
    data = json.loads(attestation.read_text(encoding="utf-8"))
    data["source_snapshot"]["local_source_commit"] = "0" * 40
    attestation.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    result = run_verifier(project)
    assert result.returncode != 0
    assert "FAIL attestation source commit present" in result.stdout
    assert "FAIL attestation source commit matches provenance" in result.stdout


# ---------------------------------------------------------------------------
# Static: portable code never references forbidden machine-local state.
# ---------------------------------------------------------------------------


def test_portable_code_references_no_forbidden_paths() -> None:
    source = VERIFIER.read_text(encoding="utf-8")
    start = source.index("ATTESTATION_PATH = ")
    end = source.index("def local_checks")
    portable_region = source[start:end]
    for token in FORBIDDEN_PORTABLE_TOKENS:
        assert token not in portable_region, f"portable code references forbidden path: {token}"


# ---------------------------------------------------------------------------
# Attestation hygiene: public, sanitized, matches the canonical helper.
# ---------------------------------------------------------------------------


def test_attestation_is_well_formed_and_matches_helper() -> None:
    attestation = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    assert attestation["schema"] == "kolmaf-public-commissioning-attestation/v1"
    assert attestation["capability"] == "native.can-equip"
    assert attestation["commissioning_status"] == "COMMISSIONED"
    assert attestation["authority"] == "OBSERVATION_ONLY"
    assert attestation["mutation_scope"] == "none"
    assert attestation["native_owner"] == "KoLmafia"
    assert attestation["adapter_owner"] == "Don"
    assert attestation["transport"] == {
        "type": "fixed-relay-get",
        "method": "GET",
        "caller_controls_code": False,
        "caller_controls_destination": False,
        "caller_controls_function": False,
    }
    assert attestation["canonical_helper"]["path"] == (
        "src/kolmafa/devtest/relay/don_native_can_equip.ash"
    )
    assert attestation["canonical_helper"]["sha256"] == EXPECTED_HELPER_SHA
    assert attestation["source_snapshot"]["local_source_commit"] == (
        "a0299b8fbd5f41aaf8a2e1c09da47b109ba6c744"
    )
    assert attestation["scope"] == {
        "repository_only": True,
        "installed_runtime_verified": False,
        "provider_ready_verified": False,
        "live_freshness_verified": False,
    }
    actual = hashlib.sha256(HELPER.read_bytes()).hexdigest()
    assert actual == EXPECTED_HELPER_SHA
    assert attestation["canonical_helper"]["sha256"] == actual


def test_attestation_has_no_local_paths_or_secrets() -> None:
    text = ATTESTATION.read_text(encoding="utf-8")
    for forbidden in ("/home/", "/tmp/", "~/", "stickyricky", "doncannoli", "password", "token"):
        assert forbidden not in text, f"attestation contains forbidden content: {forbidden}"
