from datetime import UTC, datetime, timedelta
from io import BytesIO
import sqlite3
from unittest.mock import Mock

import pytest

from kolmafa import bridge, db
from kolmafa.confirmations import ConfirmationProposal, ConfirmationStore, confirm_action
from kolmafa.policy import ActionClass


def test_send_relay_command_requires_pwd() -> None:
    result = bridge.send_relay_command("http://localhost:60080", None, "version")

    assert result.return_code == 2
    assert "disabled by default" in result.stderr


def test_send_relay_command_is_kill_switched_and_redacted(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("send gate must not call relay sideCommand")

    monkeypatch.setattr(bridge, "urlopen", fail_if_called, raising=False)

    fixture_value = "<fixture-value>"

    result = bridge.send_relay_command("http://relay/", fixture_value, f"ash print('{fixture_value}')", 3.0)

    assert result.return_code == 2
    assert result.command == "<redacted>"
    assert result.transport == "send-gate"
    assert result.stdout == ""
    assert "disabled by default" in result.stderr
    assert fixture_value not in result.stderr


def test_send_relay_command_does_not_build_side_command_payload_by_default(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("default relay quarantine must not build or send sideCommand payloads")

    monkeypatch.setattr(bridge, "urlencode", fail_if_called)
    monkeypatch.setattr(bridge, "Request", fail_if_called)
    monkeypatch.setattr(bridge, "urlopen", fail_if_called)

    with _connection(tmp_path) as connection:
        result = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
            "status",
            connection=connection,
            actor_id="operator-fixture",
        )

    assert result.return_code == bridge.SEND_GATE_DENY_CODE
    assert result.transport == bridge.SEND_GATE_TRANSPORT
    assert "quarantined" in result.stderr


def test_check_status_includes_relay_settings(monkeypatch) -> None:
    monkeypatch.setattr(bridge.subprocess, "run", Mock(return_value=Mock(returncode=127, stdout="")))

    status = bridge.check_status(
        database_path=__import__("pathlib").Path("db.sqlite"),
        kolmafia_home=__import__("pathlib").Path("kol"),
        cli_command=None,
        transport="relay",
        relay_base_url="http://localhost:60080",
        relay_pwd="<fixture-value>",
    )

    assert status.transport == "relay"
    assert status.relay_base_url == "http://localhost:60080"
    assert status.relay_pwd_configured is True


class _RelayResponse(BytesIO):
    def __enter__(self):  # noqa: ANN001
        return self

    def __exit__(self, *args) -> None:  # noqa: ANN002, ANN003
        return None


def _connection(tmp_path) -> sqlite3.Connection:  # noqa: ANN001
    path = tmp_path / "kolmafa.db"
    db.init_database(path)
    return db.connect(path)


def test_read_only_relay_send_is_policy_allowed_audited_and_quarantined(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    fixture_value = "<fixture-value>"

    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("quarantined relay send must not contact sideCommand")

    monkeypatch.setattr(bridge, "urlopen", fail_if_called)
    with _connection(tmp_path) as connection:
        result = bridge.send_relay_command(
            "http://relay/",
            fixture_value,
            "status",
            connection=connection,
            actor_id="operator-fixture",
        )
        row = connection.execute(
            """
            SELECT command_hash, transport, command_class, command_text_redacted, stdout_redacted,
                   allowlist_id, policy_decision_id, confirmation_id
            FROM command_log
            """
        ).fetchone()

    assert result.return_code == 2
    assert result.transport == bridge.SEND_GATE_TRANSPORT
    assert fixture_value not in result.stderr
    assert row[0]
    assert row[1] == bridge.SEND_GATE_TRANSPORT
    assert row[2] == "read_only"
    assert row[3] == bridge.REDACTED_COMMAND
    assert row[4] == ""
    assert row[5] == "relay-read-status"
    assert row[6]
    assert row[7] is None


def test_game_affecting_relay_send_is_quarantined_without_consuming_confirmation(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    sent_commands = []

    def fake_urlopen(request, timeout):  # noqa: ANN001
        sent_commands.append(request.data.decode())
        return _RelayResponse(b"adventure accepted")

    monkeypatch.setattr(bridge, "urlopen", fake_urlopen)
    with _connection(tmp_path) as connection:
        store = ConfirmationStore(connection)
        proposal = ConfirmationProposal(
            confirmation_id="confirm-relay-fixture",
            policy_decision_id="policy-relay-fixture",
            actor_id="operator-fixture",
            actor_surface="cli",
            command_class=ActionClass.GAME_AFFECTING,
            transport="relay",
            action_text="adventure",
            arguments={"command": "adventure"},
            mode="normal",
            state_binding="mode:normal",
            allowlist_id="relay-game-adventure",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        store.create_pending(proposal)
        confirm_action(connection, proposal.confirmation_id)

        first = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        replay = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
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

    assert first.return_code == 2
    assert replay.return_code == 2
    assert sent_commands == []
    assert confirmation[0] == "confirmed"
    assert confirmation[1] is None


def test_failed_relay_confirmation_mismatch_does_not_poison_later_valid_attempt(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    sent_commands = []

    def fake_urlopen(request, timeout):  # noqa: ANN001
        sent_commands.append(request.data.decode())
        return _RelayResponse(b"adventure accepted")

    monkeypatch.setattr(bridge, "urlopen", fake_urlopen)
    with _connection(tmp_path) as connection:
        store = ConfirmationStore(connection)
        proposal = ConfirmationProposal(
            confirmation_id="confirm-relay-retry-fixture",
            policy_decision_id="policy-relay-retry-fixture",
            actor_id="operator-fixture",
            actor_surface="cli",
            command_class=ActionClass.GAME_AFFECTING,
            transport="relay",
            action_text="adventure",
            arguments={"command": "adventure"},
            mode="normal",
            state_binding="mode:normal",
            allowlist_id="relay-game-adventure",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        store.create_pending(proposal)
        confirm_action(connection, proposal.confirmation_id)

        mismatch = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id="other-operator",
            state_binding=proposal.state_binding,
        )
        valid = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        rows = connection.execute(
            "SELECT transport, return_code, confirmation_id, stderr_redacted FROM command_log ORDER BY id"
        ).fetchall()

    assert mismatch.return_code == 2
    assert valid.return_code == 2
    assert sent_commands == []
    assert rows[0][0:3] == (bridge.SEND_GATE_TRANSPORT, 2, None)
    assert "quarantined" in rows[0][3]
    assert rows[1][0:3] == (bridge.SEND_GATE_TRANSPORT, 2, None)
    assert "quarantined" in rows[1][3]


def test_missing_relay_pwd_denial_with_confirmation_id_does_not_poison_later_valid_attempt(
    monkeypatch,
    tmp_path,
) -> None:  # noqa: ANN001
    sent_commands = []

    def fake_urlopen(request, timeout):  # noqa: ANN001
        sent_commands.append(request.data.decode())
        return _RelayResponse(b"adventure accepted")

    monkeypatch.setattr(bridge, "urlopen", fake_urlopen)
    with _connection(tmp_path) as connection:
        store = ConfirmationStore(connection)
        proposal = ConfirmationProposal(
            confirmation_id="confirm-missing-pwd-retry-fixture",
            policy_decision_id="policy-missing-pwd-retry-fixture",
            actor_id="operator-fixture",
            actor_surface="cli",
            command_class=ActionClass.GAME_AFFECTING,
            transport="relay",
            action_text="adventure",
            arguments={"command": "adventure"},
            mode="normal",
            state_binding="mode:normal",
            allowlist_id="relay-game-adventure",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        store.create_pending(proposal)
        confirm_action(connection, proposal.confirmation_id)

        missing_pwd = bridge.send_relay_command(
            "http://relay/",
            None,
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        valid = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
            "adventure",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        rows = connection.execute(
            "SELECT transport, return_code, confirmation_id, stderr_redacted FROM command_log ORDER BY id"
        ).fetchall()

    assert missing_pwd.return_code == 2
    assert valid.return_code == 2
    assert sent_commands == []
    assert rows[0][0:3] == (bridge.SEND_GATE_TRANSPORT, 2, None)
    assert "quarantined" in rows[0][3]
    assert rows[1][0:3] == (bridge.SEND_GATE_TRANSPORT, 2, None)
    assert "quarantined" in rows[1][3]


def test_policy_denial_with_confirmation_id_does_not_poison_later_valid_attempt(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    sent_commands = []

    def fake_urlopen(request, timeout):  # noqa: ANN001
        sent_commands.append(request.data.decode())
        return _RelayResponse(b"adventure accepted")

    monkeypatch.setattr(bridge, "urlopen", fake_urlopen)
    with _connection(tmp_path) as connection:
        store = ConfirmationStore(connection)
        proposal = ConfirmationProposal(
            confirmation_id="confirm-policy-denial-retry-fixture",
            policy_decision_id="policy-policy-denial-retry-fixture",
            actor_id="operator-fixture",
            actor_surface="cli",
            command_class=ActionClass.GAME_AFFECTING,
            transport="relay",
            action_text="adventure",
            arguments={"command": "adventure"},
            mode="normal",
            state_binding="mode:normal",
            allowlist_id="relay-game-adventure",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        store.create_pending(proposal)
        confirm_action(connection, proposal.confirmation_id)

        denied = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
            "freeform relay send",
            connection=connection,
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            state_binding=proposal.state_binding,
        )
        valid = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
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
    assert valid.return_code == 2
    assert sent_commands == []
    assert rows[0][0:3] == (bridge.SEND_GATE_TRANSPORT, 2, None)
    assert "policy denied" in rows[0][3]
    assert rows[1][0:3] == (bridge.SEND_GATE_TRANSPORT, 2, None)
    assert "quarantined" in rows[1][3]


def test_relay_send_denies_unallowlisted_without_calling_relay(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("policy denial must not call relay")

    monkeypatch.setattr(bridge, "urlopen", fail_if_called)
    with _connection(tmp_path) as connection:
        result = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
            "freeform relay send",
            connection=connection,
            actor_id="operator-fixture",
        )

    assert result.return_code == 2
    assert "allowlist" in result.stderr


@pytest.mark.parametrize("command", ["status something", "version extra", "status pwd=<fixture-value>"])
def test_read_only_relay_allowlist_denies_argument_bearing_variants(monkeypatch, tmp_path, command: str) -> None:  # noqa: ANN001
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("argument-bearing read-only variant must not reach relay")

    monkeypatch.setattr(bridge, "urlopen", fail_if_called)
    with _connection(tmp_path) as connection:
        result = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
            command,
            connection=connection,
            actor_id="operator-fixture",
        )
        row = connection.execute(
            "SELECT transport, command_class, command_text_redacted, return_code FROM command_log"
        ).fetchone()

    assert result.return_code == 2
    assert "policy denied" in result.stderr
    assert tuple(row) == ("send-gate", "unsafe_unknown", "<redacted>", 2)


@pytest.mark.parametrize("command", [" STATUS ", "Version", " status pwd=<fixture-value> "])
def test_read_only_relay_allowlist_denies_noncanonical_raw_input(monkeypatch, tmp_path, command: str) -> None:  # noqa: ANN001
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("noncanonical raw command must not reach relay")

    monkeypatch.setattr(bridge, "urlopen", fail_if_called)
    with _connection(tmp_path) as connection:
        result = bridge.send_relay_command(
            "http://relay/",
            "pwd-fixture",
            command,
            connection=connection,
            actor_id="operator-fixture",
        )
        row = connection.execute(
            "SELECT transport, command_class, command_text_redacted, return_code FROM command_log"
        ).fetchone()

    assert result.return_code == 2
    assert "policy denied" in result.stderr
    assert tuple(row) == ("send-gate", "unsafe_unknown", "<redacted>", 2)


def test_relay_send_missing_pwd_is_audited_without_secret(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("missing relay pwd must not call relay")

    monkeypatch.setattr(bridge, "urlopen", fail_if_called)
    with _connection(tmp_path) as connection:
        result = bridge.send_relay_command(
            "http://relay/",
            None,
            "status",
            connection=connection,
            actor_id="operator-fixture",
        )
        row = connection.execute("SELECT command_text_redacted, stderr_redacted FROM command_log").fetchone()

    assert result.return_code == 2
    assert "quarantined" in result.stderr
    assert tuple(row) == (bridge.REDACTED_COMMAND, result.stderr)
