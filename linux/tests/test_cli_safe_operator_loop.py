from __future__ import annotations

from pathlib import Path
import sqlite3

from kolmafa import bridge, cli, db


FIXED_RESPONSE_PROPOSAL = "KOL-AI: hello, I am online"


def _configure_response_loop_fixture(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    database_path = tmp_path / "kolmafa.db"
    kolmafia_home = tmp_path / "kolmafia"
    session_path = kolmafia_home / "sessions" / "player.txt"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        "historical private line token=redaction-marker-response-history\n"
        "KOLMAFA_USER: historical should not replay token=redaction-marker-response-old\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KOLMAFA_DB", str(database_path))
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kolmafia_home))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    return database_path, session_path


def _block_live_response_paths(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("response proposals must not invoke relay, subprocess, Docker, or writer paths")

    monkeypatch.setattr(bridge, "urlopen", fail_if_called, raising=False)
    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)
    # send_command was moved to kolmafa.live.gcli during T02/SR2 quarantine;
    # bridge.py no longer exposes the symbol, so the guard is removed here.
    monkeypatch.setattr(bridge, "send_gcli_dry_run_command", fail_if_called)
    monkeypatch.setattr(bridge, "default_gcli_writer", fail_if_called)


def _assert_response_output_is_safe(output: str) -> None:
    assert "response_event_id" in output
    assert "response_proposal" in output
    assert "response_status" in output
    assert FIXED_RESPONSE_PROPOSAL in output
    assert "redaction-marker-response" not in output
    assert "historical private line" not in output
    assert "historical should not replay" not in output
    assert "secret body" not in output
    assert "prompt body" not in output
    assert "KOLMAFA_USER:" not in output
    assert "> KOLMAFA_USER:" not in output


def _assert_no_response_proposal_persistence(database_path: Path) -> None:
    with db.connect(database_path) as connection:
        table_names = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        persisted_text = "\n".join(
            str(value)
            for table_name in table_names
            for row in connection.execute(f"SELECT * FROM {table_name}").fetchall()
            for value in tuple(row)
            if value is not None
        )

    assert not any("proposal" in table_name or "response" in table_name for table_name in table_names)
    assert FIXED_RESPONSE_PROPOSAL not in persisted_text


def test_observe_command_persists_redacted_session_events(monkeypatch, tmp_path, capsys) -> None:
    database_path = tmp_path / "kolmafa.db"
    kolmafia_home = tmp_path / "kolmafia"
    session_path = kolmafia_home / "sessions" / "player.txt"
    session_path.parent.mkdir(parents=True)
    session_path.write_text("ignored historical log\n", encoding="utf-8")
    monkeypatch.setenv("KOLMAFA_DB", str(database_path))
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kolmafia_home))

    assert cli.main(["observe", "player"]) == 0
    capsys.readouterr()
    with session_path.open("a", encoding="utf-8") as file:
        file.write("KOLMAFA_USER: hello pwd=redaction-marker-001\n")

    return_code = cli.main(["observe", "player"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "observed 1 session event" in output
    assert "hello pwd=<redacted>" in output
    assert "redaction-marker-001" not in output

    with db.connect(database_path) as connection:
        count = connection.execute("SELECT count(*) FROM session_events").fetchone()[0]
    assert count == 1


def test_propose_game_affecting_relay_command_requires_confirmation_and_no_send(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("proposal must not call relay sideCommand")

    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "kolmafa.db"))
    monkeypatch.setattr(bridge, "urlopen", fail_if_called, raising=False)

    return_code = cli.main(["propose", "adventure"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "proposal: adventure" in output
    assert "class: game_affecting" in output
    assert "requires_confirmation: true" in output
    assert "not executed" in output


def test_deep_thinking_repl_once_blocks_live_send_without_calling_transport(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("deep-thinking repl must not execute live sends")

    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "kolmafa.db"))
    monkeypatch.setenv("KOLMAFA_RELAY_PWD", "fixture-pwd")
    monkeypatch.setattr(bridge, "urlopen", fail_if_called, raising=False)

    return_code = cli.main(["repl", "--mode", "deep-thinking", "--once", "send adventure"])
    output = capsys.readouterr().out

    assert return_code == 2
    assert "deep-thinking mode is no-action by default" in output
    assert "not executed" in output


def test_repl_once_search_uses_safe_fts_fallback(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "kolmafa.db"))

    return_code = cli.main(["repl", "--once", "search nonexistent"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "no local FTS5 results" in output
    assert "not executed" in output


def test_cli_search_redacts_secret_like_title_path_and_snippet(monkeypatch, tmp_path: Path, capsys) -> None:
    database_path = tmp_path / "kolmafa.db"
    db.init_database(database_path)
    with db.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO documents(
                document_id, source_id, source_label, source_uri_label, source_path,
                title, body_redacted, body_hash, redaction_status, retention_class
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-search-redaction-fixture",
                "fixture",
                "Fixture docs",
                "fixture://docs/api_key=redaction-marker-002/relay.md",
                "/fixture/docs/api_key=redaction-marker-002/relay.md",
                "relay pwd=redaction-marker-002 guide",
                "relay setup token=redaction-marker-002 body",
                "fixture-body-hash",
                "redacted",
                "standard",
            ),
        )
        connection.commit()
    monkeypatch.setenv("KOLMAFA_DB", str(database_path))

    return_code = cli.main(["search", "relay"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "relay pwd=<redacted> guide" in output
    assert "api_key=<redacted>" in output
    assert "setup token=<redacted> body" in output
    assert "Fixture docs" in output
    assert "redaction-marker-002" not in output


def test_listen_alias_observes_appended_session_events_without_raw_log_dump(monkeypatch, tmp_path, capsys) -> None:
    database_path = tmp_path / "kolmafa.db"
    kolmafia_home = tmp_path / "kolmafia"
    session_path = kolmafia_home / "sessions" / "player.txt"
    session_path.parent.mkdir(parents=True)
    session_path.write_text("preexisting unprefixed fixture line pwd=redaction-marker-003\n", encoding="utf-8")
    monkeypatch.setenv("KOLMAFA_DB", str(database_path))
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kolmafia_home))

    assert cli.main(["listen", "player"]) == 0
    capsys.readouterr()
    with session_path.open("a", encoding="utf-8") as file:
        file.write("unprefixed fixture line pwd=redaction-marker-003\n")
        file.write("KOLMAFA_USER: status pwd=redaction-marker-003\n")

    return_code = cli.main(["listen", "player"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "status pwd=<redacted>" in output
    assert "unprefixed fixture" not in output
    assert "redaction-marker-003" not in output


def test_repl_dry_run_uses_writer_boundary_without_live_transport(monkeypatch, tmp_path, capsys) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("REPL dry-run must not execute live transports")

    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "kolmafa.db"))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setattr(bridge, "urlopen", fail_if_called, raising=False)
    monkeypatch.setattr(bridge.subprocess, "run", fail_if_called)

    return_code = cli.main(["repl", "--once", "dry-run status"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "dry-run" in output
    assert "not executed" in output


def test_tail_once_filters_to_redacted_prefixed_events(monkeypatch, tmp_path, capsys) -> None:
    kolmafia_home = tmp_path / "kolmafia"
    session_path = kolmafia_home / "sessions" / "player.txt"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        "raw unprefixed fixture line pwd=redaction-marker-004\n"
        "KOLMAFA_USER: hello pwd=redaction-marker-004\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kolmafia_home))

    return_code = cli.main(["tail", "--once", "player"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "hello pwd=<redacted>" in output
    assert "raw unprefixed fixture" not in output
    assert "redaction-marker-004" not in output


def test_respond_proposes_once_for_new_current_run_events_without_replay_or_echo(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    database_path, session_path = _configure_response_loop_fixture(monkeypatch, tmp_path)
    _block_live_response_paths(monkeypatch)

    assert cli.main(["respond", "player"]) == 0
    initialization_output = capsys.readouterr().out
    with session_path.open("a", encoding="utf-8") as file:
        file.write("KOLMAFA_USER: secret body token=redaction-marker-response-001\n")
        file.write("> KOLMAFA_USER: prompt body pwd=redaction-marker-response-002\n")
        file.write("private unprefixed line token=redaction-marker-response-003\n")

    return_code = cli.main(["respond", "player"])
    output = capsys.readouterr().out

    assert return_code == 0
    assert "response_proposal" not in initialization_output
    _assert_response_output_is_safe(output)
    assert output.count("response_event_id") == 2
    assert output.count(f"response_proposal: {FIXED_RESPONSE_PROPOSAL}") == 2
    assert "private unprefixed line" not in output
    _assert_no_response_proposal_persistence(database_path)

    with db.connect(database_path) as connection:
        event_ids = [
            row["event_id"]
            for row in connection.execute("SELECT event_id FROM session_events ORDER BY id").fetchall()
        ]
    assert len(event_ids) == 2
    assert all(event_id in output for event_id in event_ids)

    assert cli.main(["respond", "player"]) == 0
    no_new_output = capsys.readouterr().out

    assert "response_status" in no_new_output
    assert "response_event_id" not in no_new_output
    assert "response_proposal" not in no_new_output
    assert "redaction-marker-response" not in no_new_output


def test_repl_once_respond_matches_one_shot_dry_run_response_semantics(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    database_path, session_path = _configure_response_loop_fixture(monkeypatch, tmp_path)
    _block_live_response_paths(monkeypatch)

    assert cli.main(["repl", "--once", "respond player"]) == 0
    capsys.readouterr()
    with session_path.open("a", encoding="utf-8") as file:
        file.write("KOLMAFA_USER: secret body token=redaction-marker-response-004\n")

    return_code = cli.main(["repl", "--once", "respond player"])
    output = capsys.readouterr().out

    assert return_code == 0
    _assert_response_output_is_safe(output)
    assert output.count("response_event_id") == 1
    assert output.count(f"response_proposal: {FIXED_RESPONSE_PROPOSAL}") == 1
    _assert_no_response_proposal_persistence(database_path)

    assert cli.main(["repl", "--once", "respond player"]) == 0
    no_new_output = capsys.readouterr().out

    assert "response_status" in no_new_output
    assert "response_event_id" not in no_new_output
    assert "response_proposal" not in no_new_output


def test_respond_config_failure_returns_one_without_secret_echo(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("KOLMAFA_DB", str(tmp_path / "kolmafa.db"))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "relay-secret-redaction-marker-response-005")

    return_code = cli.main(["respond", "player"])
    output = capsys.readouterr().out

    assert return_code == 1
    assert "config_error" in output
    assert "redaction-marker-response-005" not in output


def test_respond_argparse_usage_errors_remain_two() -> None:
    try:
        cli.main(["respond"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - argparse should raise for usage errors.
        raise AssertionError("respond without PLAYER_NAME must remain an argparse usage error")
