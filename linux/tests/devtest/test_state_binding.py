"""State binding tests for equip pre-state drift."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from kolmafa import db
from kolmafa.config import get_settings
from kolmafa.confirmations import confirm_action
from kolmafa.devtest.action_broker import ActionBroker
from kolmafa.bridge import CommandResult


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "dummy_pwd")
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "test_player")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    db.init_database(db_path)
    return db_path


def test_state_drift_denied_before_transport(isolated_db, monkeypatch):
    # Mock equipment_snapshot to return hat A at propose, hat B at execute
    # Sequence: first call (propose) -> hat 4614, second call (execute) -> hat 11565
    hats = ["4614", "11565"]

    def mock_snapshot():
        hat = hats.pop(0) if hats else "11565"
        return {
            "ok": True,
            "live": True,
            "equipment": {"hat_id": hat},
            "inventory": {"helmet_turtle_owned": False},
            "evidence_tier": "PROVEN LIVE STATE",
        }

    fake_writer = MagicMock()
    fake_writer.transport = "relay"
    fake_writer.write.return_value = CommandResult(command="equip", transport="relay", return_code=0, stdout="ok", stderr="")

    with patch("kolmafa.devtest.action_broker._get_current_hat_id", side_effect=lambda: mock_snapshot()["equipment"]["hat_id"]):
        # Actually patch _get_current_hat_id directly
        pass

    # Use patch for _get_current_hat_id
    with patch("kolmafa.devtest.action_broker._get_current_hat_id", side_effect=["4614", "11565"]):
        broker = ActionBroker(writer=fake_writer)
        prop = broker.propose("equip", {"id": "153", "slot": "hat", "item": "Ancient Saucehelm"})
        assert prop["ok"]
        pid = prop["proposal_id"]
        # confirm
        conn = db.connect(get_settings().database_path)
        confirm_action(conn, pid)
        conn.close()
        # Now live hat changed to 11565, execute should deny before transport
        out = broker.execute_approved(pid, expected_action="equip", expected_arguments={"id": "153", "slot": "hat", "item": "Ancient Saucehelm"})
        assert out["ok"] is False
        assert "state drift" in out["error"].lower() or "mismatch" in out["error"].lower() or "drift" in out["error"].lower()
        assert out["execution_performed"] is False
        # Writer must not have been called
        assert fake_writer.write.call_count == 0


def test_state_stable_may_reach_writer_once(isolated_db, monkeypatch):
    # Mock stable hat A both times
    fake_writer = MagicMock()
    fake_writer.transport = "relay"
    fake_writer.write.return_value = CommandResult(command="equip", transport="relay", return_code=0, stdout="ok equip", stderr="")

    with patch("kolmafa.devtest.action_broker._get_current_hat_id", return_value="10804"):
        broker = ActionBroker(writer=fake_writer)
        prop = broker.propose("equip", {"id": "153", "slot": "hat", "item": "Ancient Saucehelm"})
        assert prop["ok"]
        pid = prop["proposal_id"]
        conn = db.connect(get_settings().database_path)
        confirm_action(conn, pid)
        conn.close()
        out = broker.execute_approved(pid, expected_action="equip", expected_arguments={"id": "153", "slot": "hat", "item": "Ancient Saucehelm"})
        assert out["ok"] is True
        assert out["execution_performed"] is True  # live relay success
        assert fake_writer.write.call_count == 1
        # Replay should be denied (consumed) and no second call
        out2 = broker.execute_approved(pid, expected_action="equip", expected_arguments={"id": "153", "slot": "hat", "item": "Ancient Saucehelm"})
        assert out2["ok"] is False
        assert fake_writer.write.call_count == 1
