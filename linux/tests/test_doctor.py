from pathlib import Path
from unittest.mock import Mock

from kolmafa import bridge, cli
from kolmafa.config import Settings


def test_check_status_reports_docker_absent(monkeypatch) -> None:
    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return Mock(returncode=127, stdout="", stderr="")

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    status = bridge.check_status(Path("db.sqlite"), Path("kol"), None)

    assert status.docker_available is False
    assert status.container_running is None
    assert status.session_dir == Path("kol/sessions")


def test_docker_free_status_uses_session_path_without_docker_or_directory_creation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fail_if_docker_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("docker-free readiness must not require Docker")

    kolmafia_home = tmp_path / "kolmafia"
    sessions_dir = kolmafia_home / "sessions"
    session_log = sessions_dir / "player.txt"
    sessions_dir.mkdir(parents=True)
    session_log.write_text("", encoding="utf-8")
    missing_live_data = kolmafia_home / "data"
    monkeypatch.setattr(bridge.subprocess, "run", fail_if_docker_called)

    status = bridge.check_status(
        tmp_path / "kolmafa.db",
        kolmafia_home,
        None,
        transport="docker-free",
        player_name="player",
    )

    assert status.docker_available is False
    assert status.container_running is None
    assert status.session_dir == sessions_dir
    assert status.session_file == session_log
    assert status.docker_free_ready is True
    assert status.docker_free_problems == ()
    assert not missing_live_data.exists()


def test_docker_free_status_reports_missing_session_log_without_creation(tmp_path: Path) -> None:
    kolmafia_home = tmp_path / "kolmafia"

    status = bridge.check_status(
        tmp_path / "kolmafa.db",
        kolmafia_home,
        None,
        transport="docker-free",
        player_name="player",
    )

    assert status.docker_free_ready is False
    assert "kolmafia_home_missing" in status.docker_free_problems
    assert "session_dir_missing" in status.docker_free_problems
    assert "session_log_missing" in status.docker_free_problems
    assert not kolmafia_home.exists()


def test_settings_from_env_accepts_docker_free_player_and_path(monkeypatch, tmp_path: Path) -> None:
    kolmafia_home = tmp_path / "kolmafia"
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kolmafia_home))
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "player_1")

    settings = Settings.from_env()

    assert settings.transport == "docker-free"
    assert settings.kolmafia_home == kolmafia_home
    assert settings.player_name == "player_1"


def test_settings_from_env_rejects_unsafe_player_name(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(tmp_path / "kolmafia"))
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "../secret")

    try:
        Settings.from_env()
    except ValueError as exc:
        assert "KOLMAFA_PLAYER_NAME" in str(exc)
        assert "../secret" not in str(exc)
    else:  # pragma: no cover - clarity for fail-closed contract
        raise AssertionError("unsafe player name must fail closed")


def test_doctor_invalid_docker_free_config_returns_redacted_diagnostic(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    unsafe_home = tmp_path / "kolmafia\nunsafe-marker"
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(unsafe_home))
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", "bad/player")

    return_code = cli.main(["doctor"])
    output = capsys.readouterr().out

    assert return_code == 2
    assert "config_error:" in output
    assert "KOLMAFA_PLAYER_NAME" in output
    assert "bad/player" not in output
    assert "unsafe-marker" not in output


def test_doctor_redacts_secret_bearing_config_values(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "kolmafa.db"))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setenv("KOLMAFA_CLI_COMMAND", "wrapper --pwd=redaction-marker-201")
    monkeypatch.setenv("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080/game.php?pwd=redaction-marker-201")
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "redaction-marker-201")

    return_code = cli.main(["doctor"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "relay_pwd_configured: True" in output
    assert "pwd=<redacted>" in output
    assert "redaction-marker-201" not in output


def test_tail_rejects_unsafe_player_name_without_creating_session_dirs(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    kolmafia_home = tmp_path / "kolmafia"
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kolmafia_home))

    return_code = cli.main(["tail", "../unsafe-marker"])
    output = capsys.readouterr().out

    assert return_code == 2
    assert "tail_error:" in output
    assert "KOLMAFA_PLAYER_NAME" in output
    assert "../unsafe-marker" not in output
    assert not kolmafia_home.exists()


def test_tail_missing_valid_session_file_fails_without_creating_live_paths(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    kolmafia_home = tmp_path / "kolmafia"
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kolmafia_home))

    return_code = cli.main(["tail", "player"])
    output = capsys.readouterr().out

    assert return_code == 2
    assert "tail_error:" in output
    assert "session log is not an existing file" in output
    assert not kolmafia_home.exists()
