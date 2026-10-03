"""Pure item identity catalog and resolver tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kolmafa.devtest import item_identity
from kolmafa.devtest.item_identity import resolve_item_id, resolve_item_name


CATALOG = Path(__file__).resolve().parents[2] / "data" / "item_identity.json"


def test_catalog_has_provenance_and_required_identities():
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert payload["schema"] == "kolmafa-item-identity-v1"
    assert payload["source"]["kind"] == "kolmafia-canonical-item-data"
    assert payload["source"]["sha256"]
    assert payload["source"]["kolmafia_revision"]
    assert payload["source"]["items_version"] == 1
    assert payload["items"] == {
        "153": "Ancient Saucehelm",
        "5054": "intriguing puzzle box",
    }


def test_resolves_frozen_identities():
    assert resolve_item_id(153).canonical_name == "Ancient Saucehelm"
    assert resolve_item_id(5054).canonical_name == "intriguing puzzle box"
    assert resolve_item_name("153", "Ancient Saucehelm").id == 153
    assert resolve_item_name("5054", "intriguing puzzle box").id == 5054


@pytest.mark.parametrize("item_id", [0, -1, "not-an-id", True, None])
def test_malformed_or_unknown_ids_fail_closed(item_id):
    with pytest.raises(ValueError):
        resolve_item_id(item_id)


def test_unknown_positive_id_fails_closed():
    with pytest.raises(ValueError, match="unknown item id"):
        resolve_item_id(999999)


def test_name_mismatch_fails_closed():
    with pytest.raises(ValueError, match="mismatch"):
        resolve_item_name("5054", "pocket wish")
    with pytest.raises(ValueError, match="mismatch"):
        resolve_item_name("153", "giant yellow hat")


def test_case_normalization_is_allowed_but_command_name_is_catalog_canonical():
    resolved = resolve_item_name("5054", "  Intriguing Puzzle Box  ")
    assert resolved.canonical_name == "intriguing puzzle box"


def test_missing_or_corrupt_catalog_fails_closed(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(item_identity, "CATALOG_PATH", missing)
    with pytest.raises(ValueError, match="unavailable or corrupt"):
        resolve_item_id(153)

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(item_identity, "CATALOG_PATH", corrupt)
    with pytest.raises(ValueError, match="unavailable or corrupt"):
        resolve_item_id(153)
