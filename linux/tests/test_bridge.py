from pathlib import Path

import pytest

from kolmafa import bridge, db
from kolmafa.bridge import session_file


def test_session_file_uses_player_txt() -> None:
    assert session_file(Path("/kol"), "player") == Path("/kol/sessions/player.txt")


@pytest.mark.parametrize("player_name", ["../secret", "bad/player", "bad\\player", "player.txt"])
def test_session_file_rejects_unsafe_player_names(player_name: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        session_file(Path("/kol"), player_name)

    assert "KOLMAFA_PLAYER_NAME" in str(exc_info.value)
    assert player_name not in str(exc_info.value)


def test_follow_session_missing_file_fails_without_creating_directories(tmp_path: Path) -> None:
    session_path = tmp_path / "kolmafia" / "sessions" / "player.txt"

    with pytest.raises(bridge.BridgeError):
        bridge.follow_session(session_path)

    assert not session_path.parent.exists()


def test_send_command_is_kill_switched_by_default(monkeypatch) -> None:
    """send_command was moved to kolmafa.live.gcli during T02/SR2 quarantine.

    The MVP bridge module no longer exposes a live send entry point.  Import
    from the quarantined location to verify the function still exists and
    returns a kill-switched denial.
    """
    raw_command = "ash print('pwd=<fixture-value>')"

    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("send gate must not launch a CLI transport")

    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)

    from kolmafa.live import gcli as live_gcli

    result = live_gcli.send_command("kolmafia --cli", raw_command)

    assert result.return_code == 2
    assert result.command == "<redacted>"
    assert result.transport == "send-gate"
    assert "disabled by default" in result.stderr
    assert "<fixture-value>" not in result.stderr
    assert "pwd=" not in result.stderr


def test_dry_run_gcli_writer_returns_redacted_audit_safe_shape(monkeypatch) -> None:
    raw_command = "ash print('pwd=<fixture-value>')"

    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("dry-run writer must not execute external processes")

    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)

    result = bridge.DryRunGcliWriter().write(raw_command)

    assert result.return_code == 0
    assert result.transport == "gcli-dry-run"
    assert "pwd=<redacted>" in result.command
    assert "dry-run" in result.stdout
    assert result.stderr == ""
    assert "<fixture-value>" not in result.command
    assert "<fixture-value>" not in result.stdout


def test_default_gcli_writer_is_dry_run_and_does_not_launch_second_instance(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("default dry-run writer must not launch KoLmafia")

    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)

    result = bridge.default_gcli_writer().write("status")

    assert result.return_code == 0
    assert result.transport == "gcli-dry-run"
    assert "not executed" in result.stdout


def test_second_instance_gcli_writer_is_refused_before_dry_run(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("second-instance fallback must not be probed or launched")

    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)

    result = bridge.default_gcli_writer("kolmafia-gcli-docker.sh").write("status")

    assert result.return_code == 2
    assert result.transport == "send-gate"
    assert result.command == "<redacted>"
    assert "second KoLmafia Java process" in result.stderr


def test_dry_run_gcli_writer_result_is_compatible_with_command_audit(tmp_path: Path) -> None:
    database_path = tmp_path / "kolmafa.db"
    db.init_database(database_path)
    result = bridge.DryRunGcliWriter().write("ash pwd=<fixture-value>")

    with db.connect(database_path) as connection:
        bridge.log_command(connection, result)
        row = connection.execute(
            "SELECT transport, command_text_redacted, command_hash, return_code, stdout_redacted FROM command_log"
        ).fetchone()

    assert row[0] == "gcli-dry-run"
    assert row[1] == "ash pwd=<redacted>"
    assert row[2]
    assert row[3:] == (0, result.stdout)
