import sqlite3
from datetime import UTC, datetime, timedelta

from kolmafa import bridge, cli, db
from kolmafa.confirmations import ConfirmationProposal, ConfirmationStore, confirm_action
from kolmafa.policy import ActionClass


def test_cli_send_relay_fails_closed_and_redacts_output(monkeypatch, tmp_path, capsys) -> None:
    fixture_value = "<fixture-value>"

    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("send gate must not call relay sideCommand")

    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "kolmafa.db"))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", fixture_value)
    monkeypatch.setattr(bridge, "urlopen", fail_if_called, raising=False)

    return_code = cli.main(["send", f"ash print('{fixture_value}')"])
    output = capsys.readouterr().out

    assert return_code == 2
    assert "disabled by default" in output
    assert fixture_value not in output

    with sqlite3.connect(tmp_path / "kolmafa.db") as connection:
        row = connection.execute(
            "SELECT command_text_redacted, command_hash, transport, return_code, stderr_redacted FROM command_log"
        ).fetchone()
    assert row[0] == "<redacted>"
    assert row[1]
    assert row[2:] == ("send-gate", 2, output)


def test_cli_send_second_java_path_refuses_even_with_offline_ok(monkeypatch, tmp_path, capsys) -> None:
    fixture_value = "<fixture-value>"

    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("send gate must not launch a second Java process")

    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "kolmafa.db"))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "cli")
    monkeypatch.setenv("KOLMAFA_CLI_COMMAND", "kolmafia-gcli-docker.sh")
    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)

    return_code = cli.main(["send", f"ash print('{fixture_value}')", "--offline-ok"])
    output = capsys.readouterr().out

    assert return_code == 2
    assert "disabled by default" in output
    assert "second KoLmafia Java process" in output
    assert fixture_value not in output


def test_cli_send_docker_free_uses_policy_bound_dry_run_writer(monkeypatch, tmp_path, capsys) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("docker-free dry-run send must not launch external processes")

    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "kolmafa.db"))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)

    return_code = cli.main(["send", "status"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "dry-run" in output

    with sqlite3.connect(tmp_path / "kolmafa.db") as connection:
        row = connection.execute(
            "SELECT command_text_redacted, transport, command_class, return_code FROM command_log"
        ).fetchone()
    assert tuple(row) == ("status", bridge.GCLI_DRY_RUN_TRANSPORT, "read_only", 0)


def test_cli_dry_run_command_uses_policy_bound_writer_and_redacts(monkeypatch, tmp_path, capsys) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("explicit dry-run must not launch external processes")

    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "kolmafa.db"))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)

    return_code = cli.main(["dry-run", "status"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "dry-run" in output
    assert "not executed" in output

    with sqlite3.connect(tmp_path / "kolmafa.db") as connection:
        row = connection.execute(
            "SELECT command_text_redacted, transport, command_class, return_code FROM command_log"
        ).fetchone()
    assert tuple(row) == ("status", bridge.GCLI_DRY_RUN_TRANSPORT, "read_only", 0)


def test_cli_send_relay_transport_uses_dry_run_writer_not_live_relay_with_confirmation(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    database_path = tmp_path / "kolmafa.db"

    db.init_database(database_path)
    with db.connect(database_path) as connection:
        proposal = ConfirmationProposal(
            confirmation_id="confirm-cli-dry-run-fixture",
            policy_decision_id="policy-cli-dry-run-fixture",
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

    def fail_if_live_relay_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("T7 docker-free CLI path must not call live relay send")

    monkeypatch.setenv("KOLMAFA_DB", str(database_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "pwd-fixture")
    monkeypatch.setattr(bridge, "send_relay_command", fail_if_live_relay_called)

    return_code = cli.main(
        [
            "send",
            "adventure",
            "--confirmation-id",
            proposal.confirmation_id,
            "--actor-id",
            proposal.actor_id,
            "--state-binding",
            proposal.state_binding,
        ]
    )
    output = capsys.readouterr().out

    assert return_code == 0
    assert "dry-run" in output

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT transport, command_class, confirmation_id, return_code FROM command_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert tuple(row) == (bridge.GCLI_DRY_RUN_TRANSPORT, "game_affecting", proposal.confirmation_id, 0)
