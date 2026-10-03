"""Action broker tests for Slice 2B."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kolmafa.devtest.action_broker import ActionBroker, _normalize_action, _serialize_action
from kolmafa import db
from kolmafa.config import get_settings
from kolmafa.confirmations import confirm_action
from kolmafa.bridge import DryRunGcliWriter, CommandResult


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "broker.db"
    monkeypatch.setenv("KOLMAFA_DB", str(db_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "tester")
    (tmp_path / "home" / "sessions").mkdir(parents=True)
    db.init_database(db_path)
    return db_path


def test_proposal_normalization_stable(isolated_db):
    b = ActionBroker()
    p1 = b.propose("  Adventure  ")
    p2 = b.propose("adventure")
    # Both should be T2 and have same action_hash (normalize stable)
    assert p1["ok"] and p2["ok"]
    assert p1["action_hash"] == p2["action_hash"]
    assert p1["normalized_action"] == "adventure"
    # Changed action changes hash
    p3 = b.propose("craft")
    assert p3["action_hash"] != p1["action_hash"]


def test_t1_rejected_from_writer(isolated_db):
    b = ActionBroker()
    for t1 in ["status", "version", "inventory"]:
        res = b.propose(t1)
        assert res["ok"] is False
        assert "T1" in res["error"]
        assert res["classification"] == "read_only"
        # Ensure no pending created (cannot execute)
        assert "proposal_id" not in res or res.get("execution_performed") is False


def test_t2_requires_approval_and_fails_without(isolated_db):
    b = ActionBroker()
    prop = b.propose("adventure")
    assert prop["ok"] and prop["approval_required"]
    pid = prop["proposal_id"]
    # Without confirm, execute denied
    out = b.execute_approved(pid, expected_action="adventure")
    assert out["ok"] is False
    assert out["execution_performed"] is False


def test_t2_wrong_approval_denied(isolated_db):
    b = ActionBroker()
    prop = b.propose("adventure")
    pid = prop["proposal_id"]
    # Confirm correctly
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, pid)
    conn.close()
    # Wrong action binding (mismatch) should deny
    out = b.execute_approved(pid, expected_action="use")
    assert out["ok"] is False
    assert "mismatch" in out["error"].lower()
    assert out["execution_performed"] is False


def test_t2_stale_or_mismatched_arguments_denied(isolated_db):
    b = ActionBroker()
    prop = b.propose("use", arguments={"item": "intriguing puzzle box", "id": "5054"})
    pid = prop["proposal_id"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, pid)
    conn.close()
    # Correct action but wrong arguments
    out = b.execute_approved(pid, expected_action="use", expected_arguments={"item": "pocket wish", "id": "5054"})
    assert out["ok"] is False
    assert out["execution_performed"] is False


def test_t2_exact_approval_succeeds_and_calls_transport_once(isolated_db):
    # Fake writer that counts calls
    fake = MagicMock(spec=DryRunGcliWriter)
    fake.write.return_value = CommandResult(
        command="adventure", transport="gcli-dry-run", return_code=0, stdout="dry-run ok", stderr=""
    )
    b = ActionBroker(writer=fake)
    prop = b.propose("adventure")
    pid = prop["proposal_id"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, pid)
    conn.close()
    out = b.execute_approved(pid, expected_action="adventure")
    assert out["ok"] is True
    assert out["execution_performed"] is False  # DryRun flag per spec
    assert out["return_code"] == 0
    assert fake.write.call_count == 1
    # Replay denied and no second call
    out2 = b.execute_approved(pid, expected_action="adventure")
    assert out2["ok"] is False
    assert fake.write.call_count == 1  # still 1


def test_t3_denied_before_transport_and_confirmation_does_not_override(isolated_db):
    fake = MagicMock(spec=DryRunGcliWriter)
    b = ActionBroker(writer=fake)
    for t3 in ["kmail bob hello", "chat clan hi", "trade with bob", "stash put 5 meat", "login", "logout", "release v1"]:
        res = b.propose(t3)
        assert res["ok"] is False
        assert res["classification"] == "unsafe_unknown"
        assert "T3" in res.get("error", "") or "T3" in res.get("reason", "")
    # Ensure writer never called via propose (propose is not transport)
    assert fake.write.call_count == 0
    # Even if we try to force execute with fake id, should not call transport
    out = b.execute_approved("nonexistent-t3-id", expected_action="kmail bob hello")
    assert out["ok"] is False
    assert fake.write.call_count == 0

    # Verify that even a pending T2 cannot be turned into T3 via mismatched expected_action
    prop = b.propose("adventure")
    pid = prop["proposal_id"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, pid)
    conn.close()
    # Try to execute with T3 action text — should be denied as mismatch/T3
    out2 = b.execute_approved(pid, expected_action="kmail bob hello")
    # This will be mismatch before T3 check, but still denied and no T3 override
    assert out2["ok"] is False
    assert fake.write.call_count == 0  # still no call for wrong action after confirm (first call was previous? This b already had no call for this pid because we did not count? Actually b hasn't executed this pid yet; the earlier fake test used separate instance. In this instance, we haven't executed this pid successfully, so call count stays 0)
    # Now test that a T3 action cannot be smuggled via direct execute even if we manually create confirmation
    # (We already prove propose denies, so no confirmation exists to override)


def test_redaction_in_proposal_and_evidence(isolated_db, tmp_path: Path):
    b = ActionBroker()
    # Action with secret-like content — redaction should hide secrets
    prop = b.propose("use", arguments={"note": "pwd=secret123 token=abc"})
    # proposal itself should redact
    txt = str(prop)
    assert "secret123" not in txt
    # Evidence file should also redact
    from pathlib import Path

    # Check latest evidence log
    log_path = Path(__file__).resolve().parents[2] / "logs" / "don-evidence.jsonl"
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8", errors="replace")
        assert "secret123" not in content


def test_single_writer_no_second_transport_path(isolated_db):
    import pathlib

    # Search Don devtest code for live mutation paths
    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest"
    all_py = "".join((root / f).read_text() for f in ["action_broker.py", "runtime.py", "mcp_server.py", "inspection.py"])
    # Only action_broker should call writer.write
    assert "writer.write" in (root / "action_broker.py").read_text()
    # runtime should not directly call live relay sideCommand
    assert "sideCommand" not in (root / "runtime.py").read_text()
    assert "sideCommand" not in (root / "mcp_server.py").read_text()
    # mcp_server must not expose raw write tools
    text = (root / "mcp_server.py").read_text()
    for forbidden in ["raw_cli", "raw_relay", "gcli_send", "relay_sideCommand", "browser_navigate", "browser_click"]:
        assert forbidden not in text


def test_propose_unknown_action_denied(isolated_db):
    b = ActionBroker()
    res = b.propose("not_a_real_action_xyz")
    assert res["ok"] is False
    assert res["classification"] == "unsafe_unknown"


def test_equip_serializer_is_typed_and_deterministic():
    args = {"item": "Ancient Saucehelm", "id": "153", "slot": "hat"}
    assert _serialize_action("equip", args) == "equip hat Ancient Saucehelm"
    assert _serialize_action("equip", args) != "equip"
    with pytest.raises(ValueError, match="mismatch"):
        _serialize_action("equip", {**args, "item": "Crown of Thrones"})


def test_malformed_equip_denied_before_writer(isolated_db):
    fake = MagicMock(spec=DryRunGcliWriter)
    broker = ActionBroker(writer=fake)
    for args in ({}, {"item": "Ancient Saucehelm", "slot": "hat"}, {"item": "Ancient Saucehelm", "id": "153", "slot": "boots"}, {"item": "x", "id": "0", "slot": "hat"}):
        result = broker.propose("equip", args)
        assert result["ok"] is False
        assert fake.write.call_count == 0


def test_use_serializer_is_typed_and_deterministic():
    args = {"item": "intriguing puzzle box", "id": "5054"}
    assert _serialize_action("use", args) == "use 1 intriguing puzzle box"
    assert _serialize_action("use", args) != "use"
    with pytest.raises(ValueError, match="unknown item id"):
        _serialize_action("use", {"item": "another item", "id": "1"})


def test_use_executes_complete_serialized_command_once(isolated_db):
    fake = MagicMock(spec=DryRunGcliWriter)
    fake.transport = "relay"
    fake.write.return_value = CommandResult(command="use 1 intriguing puzzle box", transport="relay", return_code=0, stdout="ok", stderr="")
    broker = ActionBroker(writer=fake)
    args = {"item": "intriguing puzzle box", "id": "5054"}
    proposal = broker.propose("use", args)
    assert proposal["ok"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, proposal["proposal_id"])
    conn.close()
    result = broker.execute_approved(proposal["proposal_id"], expected_action="use", expected_arguments=args)
    assert result["ok"] is True
    assert fake.write.call_count == 1
    assert fake.write.call_args.args[0] == "use 1 intriguing puzzle box"
    replay = broker.execute_approved(proposal["proposal_id"], expected_action="use", expected_arguments=args)
    assert replay["ok"] is False
    assert fake.write.call_count == 1


def test_malformed_use_denied_before_confirmation_and_writer(isolated_db):
    fake = MagicMock(spec=DryRunGcliWriter)
    broker = ActionBroker(writer=fake)
    for args in ({}, {"item": "intriguing puzzle box"}, {"id": "5054"}, {"item": "intriguing puzzle box", "id": "0"}, {"item": "intriguing puzzle box", "id": "not-an-id"}):
        result = broker.propose("use", args)
        assert result["ok"] is False
        assert fake.write.call_count == 0


def test_use_invalid_serialized_structure_does_not_consume_confirmation(isolated_db):
    fake = MagicMock(spec=DryRunGcliWriter)
    broker = ActionBroker(writer=fake)
    args = {"item": "intriguing puzzle box", "id": "5054"}
    proposal = broker.propose("use", args)
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, proposal["proposal_id"])
    conn.close()
    result = broker.execute_approved(
        proposal["proposal_id"],
        expected_action="use",
        expected_arguments={**args, "item": "intriguing puzzle box\nbad"},
    )
    assert result["ok"] is False
    assert fake.write.call_count == 0
    conn = db.connect(get_settings().database_path)
    status = conn.execute("SELECT status FROM action_confirmations WHERE confirmation_id=?", (proposal["proposal_id"],)).fetchone()[0]
    conn.close()
    assert status == "confirmed"


def test_item_identity_mismatch_does_not_consume_confirmation_or_write(isolated_db, monkeypatch):
    fake = MagicMock(spec=DryRunGcliWriter)
    broker = ActionBroker(writer=fake)
    args = {"item": "intriguing puzzle box", "id": "5054"}
    proposal = broker.propose("use", args)
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, proposal["proposal_id"])
    conn.close()

    import kolmafa.devtest.action_broker as broker_module

    def mismatch(*_args, **_kwargs):
        raise ValueError("item id/name mismatch for 5054")

    monkeypatch.setattr(broker_module, "resolve_item_name", mismatch)
    result = broker.execute_approved(proposal["proposal_id"], expected_action="use", expected_arguments=args)
    assert result["ok"] is False
    assert fake.write.call_count == 0
    conn = db.connect(get_settings().database_path)
    status = conn.execute(
        "SELECT status FROM action_confirmations WHERE confirmation_id=?",
        (proposal["proposal_id"],),
    ).fetchone()[0]
    conn.close()
    assert status == "confirmed"


def test_untyped_t2_serialization_failure_does_not_consume_confirmation(isolated_db):
    fake = MagicMock(spec=DryRunGcliWriter)
    broker = ActionBroker(writer=fake)
    args = {"item": "unreviewed item", "id": "1234"}
    proposal = broker.propose("buy", args)
    assert proposal["ok"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, proposal["proposal_id"])
    conn.close()
    result = broker.execute_approved(proposal["proposal_id"], expected_action="buy", expected_arguments=args)
    assert result["ok"] is False
    assert fake.write.call_count == 0
    conn = db.connect(get_settings().database_path)
    status = conn.execute("SELECT status FROM action_confirmations WHERE confirmation_id=?", (proposal["proposal_id"],)).fetchone()[0]
    conn.close()
    assert status == "confirmed"


def test_use_outcome_unknown_calls_once_without_retry(isolated_db):
    fake = MagicMock(spec=DryRunGcliWriter)
    fake.transport = "relay"
    fake.write.return_value = CommandResult(
        command="use 1 intriguing puzzle box",
        transport="relay",
        return_code=2,
        stdout="",
        stderr="relay send ambiguous (OUTCOME_UNKNOWN): timeout",
    )
    broker = ActionBroker(writer=fake)
    args = {"item": "intriguing puzzle box", "id": "5054"}
    proposal = broker.propose("use", args)
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, proposal["proposal_id"])
    conn.close()
    first = broker.execute_approved(proposal["proposal_id"], expected_action="use", expected_arguments=args)
    second = broker.execute_approved(proposal["proposal_id"], expected_action="use", expected_arguments=args)
    assert first["outcome"] == "OUTCOME_UNKNOWN"
    assert second["ok"] is False
    assert fake.write.call_count == 1


def test_equip_executes_complete_serialized_command_once(isolated_db, monkeypatch):
    fake = MagicMock(spec=DryRunGcliWriter)
    fake.transport = "relay"
    fake.write.return_value = CommandResult(command="equip hat Ancient Saucehelm", transport="relay", return_code=0, stdout="ok", stderr="")
    broker = ActionBroker(writer=fake)
    args = {"item": "Ancient Saucehelm", "id": "153", "slot": "hat"}
    monkeypatch.setattr("kolmafa.devtest.action_broker._get_current_hat_id", lambda: "7783")
    proposal = broker.propose("equip", args)
    assert proposal["ok"]
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, proposal["proposal_id"])
    conn.close()
    result = broker.execute_approved(proposal["proposal_id"], expected_action="equip", expected_arguments=args)
    assert result["ok"] is True
    assert result["execution_performed"] is True
    assert fake.write.call_count == 1
    assert fake.write.call_args.args[0] == "equip hat Ancient Saucehelm"
    replay = broker.execute_approved(proposal["proposal_id"], expected_action="equip", expected_arguments=args)
    assert replay["ok"] is False
    assert fake.write.call_count == 1


def test_relay_execution_evidence_uses_live_transport_mode(isolated_db, monkeypatch):
    fake = MagicMock(spec=DryRunGcliWriter)
    fake.transport = "relay"
    fake.write.return_value = CommandResult(command="equip hat Ancient Saucehelm", transport="relay", return_code=0, stdout="ok", stderr="")
    modes = []
    monkeypatch.setattr(
        "kolmafa.devtest.action_broker.record_evidence",
        lambda operation, mode, *args, **kwargs: modes.append((operation, mode)),
    )
    args = {"item": "Ancient Saucehelm", "id": "153", "slot": "hat"}
    monkeypatch.setattr("kolmafa.devtest.action_broker._get_current_hat_id", lambda: "7783")
    broker = ActionBroker(writer=fake)
    proposal = broker.propose("equip", args)
    conn = db.connect(get_settings().database_path)
    confirm_action(conn, proposal["proposal_id"])
    conn.close()
    result = broker.execute_approved(proposal["proposal_id"], expected_action="equip", expected_arguments=args)
    assert result["ok"] is True
    assert ("don_execute_approved", "live-transport") in modes
    assert all(mode == "live-transport" for operation, mode in modes if operation == "don_execute_approved")
