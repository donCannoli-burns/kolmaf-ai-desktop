from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from kolmafa import bridge, db
from kolmafa.confirmations import ConfirmationProposal, ConfirmationStore, confirm_action
from kolmafa.policy import ActionClass


def _connection(tmp_path) -> sqlite3.Connection:  # noqa: ANN001
    path = tmp_path / "kolmafa.db"
    db.init_database(path)
    return db.connect(path)


def _confirmed_adventure(connection: sqlite3.Connection) -> ConfirmationProposal:
    proposal = ConfirmationProposal(
        confirmation_id="confirm-writer-fixture",
        policy_decision_id="policy-writer-fixture",
        actor_id="operator-fixture",
        actor_surface="cli",
        command_class=ActionClass.GAME_AFFECTING,
        transport=bridge.GCLI_DRY_RUN_TRANSPORT,
        action_text="adventure",
        arguments={"command": "adventure"},
        mode="normal",
        state_binding="mode:normal;turns:fixture",
        allowlist_id="relay-game-adventure",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    ConfirmationStore(connection).create_pending(proposal)
    confirm_action(connection, proposal.confirmation_id)
    return proposal


def test_read_only_dry_run_writer_send_is_policy_allowed_audited_and_redacted(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("dry-run writer gate must not execute external processes")

    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)
    with _connection(tmp_path) as connection:
        result = bridge.send_gcli_dry_run_command(
            "status",
            connection=connection,
            actor_id="operator-fixture",
        )
        row = connection.execute(
            """
            SELECT transport, command_class, command_text_redacted, return_code,
                   stdout_redacted, allowlist_id, policy_decision_id, confirmation_id
            FROM command_log
            """
        ).fetchone()

    assert result.return_code == 0
    assert result.transport == bridge.GCLI_DRY_RUN_TRANSPORT
    assert tuple(row) == (
        bridge.GCLI_DRY_RUN_TRANSPORT,
        "read_only",
        "status",
        0,
        result.stdout,
        "relay-read-status",
        row[6],
        None,
    )
    assert row[6]


def test_game_affecting_dry_run_writer_send_does_not_consume_confirmation(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """The dry-run path links the confirmation_id to the command audit but does
    not mark the confirmation as consumed.  The one-shot unique index on
    ``command_log.confirmation_id`` prevents replay, returning a denial on the
    second call."""

    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("dry-run writer gate must not execute external processes")

    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)
    with _connection(tmp_path) as connection:
        proposal = _confirmed_adventure(connection)

        first = bridge.send_gcli_dry_run_command(
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        replay = bridge.send_gcli_dry_run_command(
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        confirmation = connection.execute(
            "SELECT status, consumed_by_command_log_id FROM action_confirmations WHERE confirmation_id = ?",
            (proposal.confirmation_id,),
        ).fetchone()
        rows = connection.execute(
            "SELECT transport, command_class, return_code FROM command_log ORDER BY id"
        ).fetchall()

    assert first.return_code == 0
    assert replay.return_code == 2
    assert confirmation[0] == "confirmed"
    assert confirmation[1] is None
    assert [tuple(row) for row in rows] == [
        (bridge.GCLI_DRY_RUN_TRANSPORT, "game_affecting", 0),
        (bridge.SEND_GATE_TRANSPORT, "game_affecting", 2),
    ]


def test_dry_run_confirmation_skips_caller_validation_but_prevents_replay(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """Actor/action validation is removed from the dry-run path (it lives in
    the future live execute path).  The one-shot unique index on
    ``command_log.confirmation_id`` still prevents replay regardless of who
    calls."""

    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("dry-run writer gate must not execute external processes")

    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)
    with _connection(tmp_path) as connection:
        proposal = _confirmed_adventure(connection)

        first = bridge.send_gcli_dry_run_command(
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id="other-operator",
            state_binding=proposal.state_binding,
        )
        second = bridge.send_gcli_dry_run_command(
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        rows = connection.execute(
            "SELECT transport, return_code, confirmation_id, stderr_redacted FROM command_log ORDER BY id"
        ).fetchall()

    assert first.return_code == 0
    assert second.return_code == 2
    assert rows[0][0:3] == (bridge.GCLI_DRY_RUN_TRANSPORT, 0, proposal.confirmation_id)
    assert rows[1][0:3] == (bridge.SEND_GATE_TRANSPORT, 2, None)


def test_expired_dry_run_confirmation_denial_does_not_link_confirmation_id(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("expired confirmation must not reach dry-run writer")

    monkeypatch.setattr(bridge.DryRunGcliWriter, "write", fail_if_called)
    with _connection(tmp_path) as connection:
        proposal = ConfirmationProposal(
            confirmation_id="expired-writer-fixture",
            policy_decision_id="expired-policy-fixture",
            actor_id="operator-fixture",
            actor_surface="cli",
            command_class=ActionClass.GAME_AFFECTING,
            transport=bridge.GCLI_DRY_RUN_TRANSPORT,
            action_text="adventure",
            arguments={"command": "adventure"},
            mode="normal",
            state_binding="mode:normal;turns:fixture",
            allowlist_id="relay-game-adventure",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        ConfirmationStore(connection).create_pending(proposal)
        confirm_action(connection, proposal.confirmation_id)

        result = bridge.send_gcli_dry_run_command(
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        row = connection.execute(
            "SELECT return_code, confirmation_id, stderr_redacted FROM command_log"
        ).fetchone()

    assert result.return_code == 2
    assert row[0:2] == (2, None)
    assert "expired" in row[2]


def test_dry_run_policy_denial_with_confirmation_id_does_not_poison_later_valid_attempt(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("policy denial must not reach dry-run writer")

    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)
    with _connection(tmp_path) as connection:
        proposal = _confirmed_adventure(connection)

        denied = bridge.send_gcli_dry_run_command(
            "freeform relay send",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        valid = bridge.send_gcli_dry_run_command(
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        rows = connection.execute(
            "SELECT transport, return_code, confirmation_id, stderr_redacted FROM command_log ORDER BY id"
        ).fetchall()

    assert denied.return_code == 2
    assert valid.return_code == 0
    assert rows[0][0:3] == (bridge.SEND_GATE_TRANSPORT, 2, None)
    assert "policy denied" in rows[0][3]
    assert rows[1][0:3] == (bridge.GCLI_DRY_RUN_TRANSPORT, 0, proposal.confirmation_id)


@pytest.mark.parametrize("command", ["freeform relay send", " STATUS ", "chat hello", "status pwd=<fixture-value>"])
def test_dry_run_writer_send_denies_unknown_noncanonical_social_or_secret_bearing_commands(
    monkeypatch,
    tmp_path,
    command: str,
) -> None:  # noqa: ANN001
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("policy denial must not reach dry-run writer")

    monkeypatch.setattr(bridge.DryRunGcliWriter, "write", fail_if_called)
    with _connection(tmp_path) as connection:
        result = bridge.send_gcli_dry_run_command(
            command,
            connection=connection,
            actor_id="operator-fixture",
        )
        row = connection.execute(
            "SELECT transport, command_class, command_text_redacted, return_code, stderr_redacted FROM command_log"
        ).fetchone()

    assert result.return_code == 2
    assert tuple(row[:4]) == (bridge.SEND_GATE_TRANSPORT, "unsafe_unknown", "<redacted>", 2)
    assert "policy denied" in row[4]
    assert "<fixture-value>" not in row[4]
