"""Read-only equipability preflight tests."""

from __future__ import annotations

from unittest.mock import patch

from kolmafa.devtest.inspection import equipability_preflight


def _grounded(*, equipped: str = "11565", count: int = 1, live: bool = True) -> dict:
    return {
        "ok": live,
        "equipment": {"hat": equipped},
        "legacy_inventory": {"sample_candidates": [{"id": "153", "name": "Ancient Saucehelm", "count": count}]},
    }


def test_preflight_is_unknown_without_native_equigibility_source() -> None:
    result = equipability_preflight(_grounded(), item_id=153, slot="hat")
    assert result["ok"] is True
    assert result["item"] == {"id": 153, "name": "Ancient Saucehelm"}
    assert result["owned"] is True
    assert result["available_count"] == 1
    assert result["currently_equipped"] is False
    assert result["can_equip"] is None
    assert result["result"] == "UNKNOWN"
    assert result["restriction_class"] == "UNKNOWN_RESTRICTION"
    assert result["mutation_capability"] is False


def test_preflight_already_equipped() -> None:
    result = equipability_preflight(_grounded(equipped="153"), item_id=153, slot="hat")
    assert result["result"] == "ALREADY_EQUIPPED"
    assert result["can_equip"] is False
    assert result["restriction_class"] == "NONE"


def test_preflight_item_not_owned() -> None:
    result = equipability_preflight(_grounded(count=0), item_id=153, slot="hat")
    assert result["result"] == "ITEM_NOT_OWNED"
    assert result["owned"] is False
    assert result["restriction_class"] == "ITEM_NOT_OWNED"


def test_preflight_invalid_item_and_slot_fail_closed() -> None:
    item = equipability_preflight(_grounded(), item_id=999999, slot="hat")
    assert item["result"] == "INVALID_ITEM"
    assert item["ok"] is False
    slot = equipability_preflight(_grounded(), item_id=153, slot="unknown")
    assert slot["result"] == "INVALID_SLOT"
    assert slot["ok"] is False


def test_preflight_stale_state_is_unknown() -> None:
    result = equipability_preflight(_grounded(live=False), item_id=153, slot="hat")
    assert result["ok"] is False
    assert result["result"] == "UNKNOWN"
    assert result["source"]["freshness"] == "UNAVAILABLE"


def test_preflight_cannot_invoke_writer() -> None:
    with patch("kolmafa.devtest.relay_writer.RelayWriter.write", side_effect=AssertionError("mutation attempted")):
        result = equipability_preflight(_grounded(), item_id=153, slot="hat")
    assert result["mutation_capability"] is False


def test_preflight_result_has_no_secret_fields() -> None:
    result = equipability_preflight(_grounded(), item_id=153, slot="hat")
    text = str(result).casefold()
    for forbidden in ("pwd", "password", "cookie", "authorization", "token", "secret", "raw"):
        assert forbidden not in text
