from __future__ import annotations

import os
from pathlib import Path

from kolmafa import db
from kolmafa.bridge import (
    build_kolmafa_output,
    observe_session_file,
    parse_kolmafa_user_line,
    persist_session_event,
)


def test_parse_accepts_only_deterministic_user_prefix_and_redacts_body() -> None:
    event = parse_kolmafa_user_line(
        "KOLMAFA_USER: hello pwd=redaction-marker-101\n",
        player_name="player",
        line_number=7,
    )

    assert event is not None
    assert event.message_redacted == "hello pwd=<redacted>"
    assert event.source_surface == "kolmafia-session-log"
    assert event.provenance["prefix"] == "KOLMAFA_USER:"
    assert event.provenance["line_number"] == 7
    assert "redaction-marker-101" not in event.message_redacted


def test_parse_accepts_kolmafia_gcli_prompt_prefixed_user_line() -> None:
    event = parse_kolmafa_user_line(
        "> KOLMAFA_USER: hello pwd=redaction-marker-105\n",
        player_name="player",
        line_number=8,
    )

    assert event is not None
    assert event.message_redacted == "hello pwd=<redacted>"
    assert event.source_surface == "kolmafia-session-log"
    assert event.provenance["prefix"] == "KOLMAFA_USER:"
    assert event.provenance["line_number"] == 8
    assert "redaction-marker-105" not in event.message_redacted


def test_parse_rejects_empty_malformed_self_output_and_oversized_lines() -> None:
    assert parse_kolmafa_user_line("KOLMAFA_USER:   ", player_name="player") is None
    assert parse_kolmafa_user_line("chat KOLMAFA_USER: hi", player_name="player") is None
    assert parse_kolmafa_user_line(">> KOLMAFA_USER: arbitrary", player_name="player") is None
    assert parse_kolmafa_user_line("KOLMAFA: assistant output", player_name="player") is None
    assert parse_kolmafa_user_line("KOLMAFA_USER: KOL-AI: loop", player_name="player") is None
    assert (
        parse_kolmafa_user_line(
            "KOLMAFA_USER: " + ("x" * 32),
            player_name="player",
            max_line_bytes=16,
        )
        is None
    )


def test_persist_session_event_redacts_and_dedupes(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    db.init_database(database_path)

    event = parse_kolmafa_user_line("KOLMAFA_USER: token=abc123 do thing", player_name="player")
    assert event is not None

    with db.connect(database_path) as connection:
        assert persist_session_event(connection, event) is True
        assert persist_session_event(connection, event) is False
        rows = connection.execute(
            "SELECT event_id, player_name, message_redacted, message_hash, source_surface, provenance_json "
            "FROM session_events"
        ).fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row["event_id"] == event.event_id
    assert row["player_name"] == "player"
    assert row["message_redacted"] == "token=<redacted> do thing"
    assert row["message_hash"]
    assert row["source_surface"] == "kolmafia-session-log"
    assert "KOLMAFA_USER" in row["provenance_json"]


def test_observe_session_file_handles_missing_new_file_and_duplicates(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    session_path = tmp_path / "sessions" / "player.txt"
    db.init_database(database_path)

    with db.connect(database_path) as connection:
        assert observe_session_file(session_path, "player", connection) == []

        session_path.parent.mkdir(parents=True)
        session_path.write_text("ignored\n", encoding="utf-8")
        assert observe_session_file(session_path, "player", connection) == []
        with session_path.open("a", encoding="utf-8") as file:
            file.write("KOLMAFA_USER: first\nKOLMAFA_USER: first\nKOLMAFA_USER: second\n")
        events = observe_session_file(session_path, "player", connection)
        count = connection.execute("SELECT count(*) FROM session_events").fetchone()[0]

    assert [event.message_redacted for event in events] == ["first", "first", "second"]
    assert count == 3


def test_listener_tails_appends_without_ingesting_existing_history(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    session_path = tmp_path / "sessions" / "player.txt"
    db.init_database(database_path)
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        "KOLMAFA_USER: old token=redaction-marker-102\nunprefixed fixture history\n",
        encoding="utf-8",
    )

    with db.connect(database_path) as connection:
        assert observe_session_file(session_path, "player", connection) == []
        session_path.write_text(
            session_path.read_text(encoding="utf-8")
            + "KOLMAFA_USER: new pwd=redaction-marker-103\nKOLMAFA: assistant output\n",
            encoding="utf-8",
        )
        events = observe_session_file(session_path, "player", connection)
        rows = connection.execute(
            "SELECT message_redacted, provenance_json FROM session_events ORDER BY id"
        ).fetchall()

    assert [event.message_redacted for event in events] == ["new pwd=<redacted>"]
    assert [row["message_redacted"] for row in rows] == ["new pwd=<redacted>"]
    assert "redaction-marker-103" not in rows[0]["message_redacted"]
    assert "byte_offset" in rows[0]["provenance_json"]


def test_listener_tails_appended_kolmafia_gcli_prompt_prefixed_user_line(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    session_path = tmp_path / "sessions" / "player.txt"
    db.init_database(database_path)
    session_path.parent.mkdir(parents=True)
    session_path.write_text("> KOLMAFA_USER: old pwd=redaction-marker-106\n", encoding="utf-8")

    with db.connect(database_path) as connection:
        assert observe_session_file(session_path, "player", connection) == []
        with session_path.open("a", encoding="utf-8") as file:
            file.write("> KOLMAFA_USER: new pwd=redaction-marker-107\n")
            file.write("chat KOLMAFA_USER: should-not-route\n")
            file.write(">> KOLMAFA_USER: should-not-route\n")
        events = observe_session_file(session_path, "player", connection)
        rows = connection.execute(
            "SELECT message_redacted, provenance_json FROM session_events ORDER BY id"
        ).fetchall()

    assert [event.message_redacted for event in events] == ["new pwd=<redacted>"]
    assert [row["message_redacted"] for row in rows] == ["new pwd=<redacted>"]
    assert "redaction-marker-106" not in rows[0]["message_redacted"]
    assert "redaction-marker-107" not in rows[0]["message_redacted"]


def test_listener_persists_cursor_identity_and_resumes_from_byte_offset(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    session_path = tmp_path / "sessions" / "player.txt"
    db.init_database(database_path)
    session_path.parent.mkdir(parents=True)
    session_path.write_text("boot\n", encoding="utf-8")

    with db.connect(database_path) as connection:
        assert observe_session_file(session_path, "player", connection) == []
        with session_path.open("a", encoding="utf-8") as file:
            file.write("KOLMAFA_USER: first\n")
        first = observe_session_file(session_path, "player", connection)
        second = observe_session_file(session_path, "player", connection)
        cursor = connection.execute(
            "SELECT file_device, file_inode, byte_offset, file_size, rotation_state "
            "FROM session_listener_cursors WHERE player_name = ?",
            ("player",),
        ).fetchone()

    assert [event.message_redacted for event in first] == ["first"]
    assert second == []
    assert cursor["file_device"] is not None
    assert cursor["file_inode"] is not None
    assert cursor["byte_offset"] == session_path.stat().st_size
    assert cursor["file_size"] == session_path.stat().st_size
    assert cursor["rotation_state"] == "steady"


def test_listener_ignores_same_inode_size_mtime_only_change(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    session_path = tmp_path / "sessions" / "player.txt"
    db.init_database(database_path)
    session_path.parent.mkdir(parents=True)
    session_path.write_text("boot\n", encoding="utf-8")

    with db.connect(database_path) as connection:
        assert observe_session_file(session_path, "player", connection) == []
        with session_path.open("a", encoding="utf-8") as file:
            file.write("KOLMAFA_USER: first\n")
        first = observe_session_file(session_path, "player", connection)
        consumed_offset = session_path.stat().st_size
        cursor_before_touch = connection.execute(
            "SELECT file_device, file_inode, byte_offset FROM session_listener_cursors WHERE player_name = ?",
            ("player",),
        ).fetchone()

        stat_before_touch = session_path.stat()
        os.utime(
            session_path,
            ns=(stat_before_touch.st_atime_ns + 10_000_000, stat_before_touch.st_mtime_ns + 10_000_000),
        )
        touched = observe_session_file(session_path, "player", connection)
        cursor_after_touch = connection.execute(
            "SELECT file_device, file_inode, byte_offset, rotation_state "
            "FROM session_listener_cursors WHERE player_name = ?",
            ("player",),
        ).fetchone()

        with session_path.open("a", encoding="utf-8") as file:
            file.write("KOLMAFA_USER: second\n")
        second = observe_session_file(session_path, "player", connection)
        rows = connection.execute(
            "SELECT event_id, message_redacted, provenance_json FROM session_events ORDER BY id"
        ).fetchall()

    assert [event.message_redacted for event in first] == ["first"]
    assert touched == []
    assert [event.message_redacted for event in second] == ["second"]
    assert cursor_after_touch["file_device"] == cursor_before_touch["file_device"]
    assert cursor_after_touch["file_inode"] == cursor_before_touch["file_inode"]
    assert cursor_after_touch["byte_offset"] == consumed_offset
    assert cursor_after_touch["rotation_state"] == "steady"
    assert [row["message_redacted"] for row in rows] == ["first", "second"]
    assert len({row["event_id"] for row in rows}) == 2
    assert "mtime" not in rows[0]["provenance_json"]


def test_listener_rotation_truncation_and_distinct_positions_are_safe(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    session_path = tmp_path / "sessions" / "player.txt"
    db.init_database(database_path)
    session_path.parent.mkdir(parents=True)
    session_path.write_text("preexisting\n", encoding="utf-8")

    with db.connect(database_path) as connection:
        assert observe_session_file(session_path, "player", connection) == []
        with session_path.open("a", encoding="utf-8") as file:
            file.write("KOLMAFA_USER: same\nKOLMAFA_USER: same\n")
        appended = observe_session_file(session_path, "player", connection)

        rotated_path = session_path.with_suffix(".old")
        session_path.rename(rotated_path)
        session_path.write_text("KOLMAFA_USER: after-rotation\n", encoding="utf-8")
        rotated = observe_session_file(session_path, "player", connection)

        session_path.write_text("KOLMAFA_USER: short\n", encoding="utf-8")
        truncated = observe_session_file(session_path, "player", connection)
        rows = connection.execute(
            "SELECT message_redacted, provenance_json FROM session_events ORDER BY id"
        ).fetchall()
        cursor = connection.execute(
            "SELECT rotation_state FROM session_listener_cursors WHERE player_name = ?",
            ("player",),
        ).fetchone()

    assert [event.message_redacted for event in appended] == ["same", "same"]
    assert [event.message_redacted for event in rotated] == ["after-rotation"]
    assert [event.message_redacted for event in truncated] == ["short"]
    assert [row["message_redacted"] for row in rows] == [
        "same",
        "same",
        "after-rotation",
        "short",
    ]
    assert cursor["rotation_state"] == "truncated"


def test_listener_rejects_oversized_and_untrusted_command_like_input(tmp_path: Path) -> None:
    database_path = tmp_path / "authority.db"
    session_path = tmp_path / "sessions" / "player.txt"
    db.init_database(database_path)
    session_path.parent.mkdir(parents=True)
    session_path.write_text("", encoding="utf-8")

    with db.connect(database_path) as connection:
        assert observe_session_file(session_path, "player", connection) == []
        with session_path.open("a", encoding="utf-8") as file:
            file.write("KOLMAFA_USER: " + ("x" * 120) + "\n")
            file.write("send KOLMAFA_USER: should-not-route\n")
            file.write("KOLMAFA_USER: /cli ash dangerous() token=secret\n")
        events = observe_session_file(session_path, "player", connection, max_line_bytes=96)
        session_count = connection.execute("SELECT count(*) FROM session_events").fetchone()[0]
        command_count = connection.execute("SELECT count(*) FROM command_log").fetchone()[0]

    assert [event.message_redacted for event in events] == ["/cli ash dangerous() token=<redacted>"]
    assert session_count == 1
    assert command_count == 0


def test_kolmafa_output_redacts_secrets_and_rejects_oversized_replies() -> None:
    output = build_kolmafa_output("ok pwd=redaction-marker-104")

    assert output == "KOL-AI: ok pwd=<redacted>"
    assert "redaction-marker-104" not in output
    assert build_kolmafa_output("x" * 64, max_output_bytes=16) is None
