"""Local-runtime capability installation checks (LOCAL_RUNTIME).

Validates actual operator installation state: the portable agent-bundle
capability registry and the installed KoLmafia relay helper. These checks
are deselected from the public portable CI gate by the ``local_runtime``
marker and require an operator host with the agent bundle and the KoLmafia
relay helper installed. Missing installations skip precisely; present but
wrong installations fail.

Path configuration (see linux/README.md):
- ``KOLMAF_AGENT_BUNDLE_ROOT``: portable agent bundle root. The capability
  registry is read from ``<root>/data/capabilities/registry.json``.
  Fallback: ``~/.local/share/kolmaf-ai/agent-bundle``.
- ``KOLMAFA_KOLMAFIA_HOME``: KoLmafia home (established project variable,
  read by ``kolmafa.config``). The installed helper is read from
  ``<home>/relay/don_native_can_equip.ash``. Fallback: ``~/.kolmafia``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kolmafa.devtest.capability_registry import check_native_health
from kolmafa.devtest.native_relay import CANONICAL_HELPER_PATH, HELPER_FILENAME

pytestmark = pytest.mark.local_runtime

BUNDLE_ROOT_ENV = "KOLMAF_AGENT_BUNDLE_ROOT"
BUNDLE_ROOT_FALLBACK = Path(".local/share/kolmaf-ai/agent-bundle")
KOLMAFIA_HOME_ENV = "KOLMAFA_KOLMAFIA_HOME"
KOLMAFIA_HOME_FALLBACK = Path(".kolmafia")
REGISTRY_RELATIVE_PATH = Path("data/capabilities/registry.json")
ATTESTATION_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "commissioning" / "native-can-equip-t1-public.json"
)


def _bundle_root() -> Path:
    override = os.environ.get(BUNDLE_ROOT_ENV)
    if override:
        return Path(override)
    return Path.home() / BUNDLE_ROOT_FALLBACK


def _kolmafia_home() -> Path:
    override = os.environ.get(KOLMAFIA_HOME_ENV)
    if override:
        return Path(override)
    return Path.home() / KOLMAFIA_HOME_FALLBACK


def _expected_helper_sha256() -> str:
    """Derive the canonical helper pin from the public commissioning attestation."""
    attestation = json.loads(ATTESTATION_PATH.read_text(encoding="utf-8"))
    return attestation["canonical_helper"]["sha256"]


def test_real_bundle_registry_matches_don_advertisement() -> None:
    registry = _bundle_root() / REGISTRY_RELATIVE_PATH
    if not registry.is_file():
        pytest.skip("operator bundle registry not installed")
    entries = {c["id"]: c for c in json.loads(registry.read_text(encoding="utf-8"))["capabilities"]}
    assert "native.can-equip" in entries
    entry = entries["native.can-equip"]
    assert entry["authority"] == "OBSERVATION_ONLY"
    assert entry["provider"] == "don-runtime"
    transport = entry["transport"]
    assert transport["type"] == "fixed-relay-get"
    assert transport["method"] == "GET"
    assert transport["caller_controls_code"] is False
    assert transport["caller_controls_destination"] is False
    assert transport["caller_controls_function"] is False


def test_real_helper_health_is_ready() -> None:
    installed = _kolmafia_home() / "relay" / HELPER_FILENAME
    if not installed.is_file():
        pytest.skip("operator KoLmafia helper not installed")
    result = check_native_health(
        canonical=CANONICAL_HELPER_PATH,
        installed=installed,
        expected_sha256=_expected_helper_sha256(),
    )
    assert result["status"] == "READY"
