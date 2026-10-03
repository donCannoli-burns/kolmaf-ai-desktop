from __future__ import annotations

import sqlite3
from pathlib import Path

from kolmafa import bridge, cli


def test_docker_free_fixture_mode_exercises_safe_bridge_without_live_dependencies(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    """Regression smoke test for the docker-free bridge acceptance path."""

    def fail_if_external_process_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("docker-free fixture mode must not call Docker, Java, or shell transports")

    def fail_if_live_relay_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("docker-free fixture mode must not contact a live KoLmafia relay")

    database_path = tmp_path / "kolmafa.db"
    kolmafia_home = tmp_path / "kolmafia"
    session_dir = kolmafia_home / "sessions"
    session_file = session_dir / "fixture_player.txt"
    fixture_secret = "<fixture-redaction-value>"
    session_dir.mkdir(parents=True)
    session_file.write_text("boot fixture line without private data\n", encoding="utf-8")

    monkeypatch.setenv("KOLMAFA_DB", str(database_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kolmafia_home))
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "fixture_player")
    monkeypatch.setattr(bridge.subprocess, "run", fail_if_external_process_called)
    monkeypatch.setattr(bridge, "urlopen", fail_if_live_relay_called, raising=False)

    assert cli.main(["doctor"]) == 0
    doctor_output = capsys.readouterr().out
    assert "docker_free_ready: True" in doctor_output
    assert "docker_available: False" in doctor_output

    assert cli.main(["observe", "fixture_player"]) == 0
    initial_observe_output = capsys.readouterr().out
    assert "observed 0 session events" in initial_observe_output

    with session_file.open("a", encoding="utf-8") as file:
        file.write(f"KOLMAFA_USER: plan next safe step token={fixture_secret}\n")

    assert cli.main(["listen", "fixture_player"]) == 0
    listen_output = capsys.readouterr().out
    assert "observed 1 session event" in listen_output
    assert "token=<redacted>" in listen_output
    assert fixture_secret not in listen_output

    assert cli.main(["propose", "status"]) == 0
    propose_output = capsys.readouterr().out
    assert "allowed: true" in propose_output
    assert "not executed" in propose_output

    assert cli.main(["dry-run", "status"]) == 0
    dry_run_output = capsys.readouterr().out
    assert "dry-run" in dry_run_output
    assert "not executed" in dry_run_output

    with sqlite3.connect(database_path) as connection:
        session_row = connection.execute(
            "SELECT message_redacted FROM session_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        command_row = connection.execute(
            "SELECT transport, command_class, command_text_redacted, return_code "
            "FROM command_log ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert session_row == ("plan next safe step token=<redacted>",)
    assert command_row == (bridge.GCLI_DRY_RUN_TRANSPORT, "read_only", "status", 0)
    assert fixture_secret not in " ".join(
        [doctor_output, initial_observe_output, listen_output, propose_output, dry_run_output]
    )
