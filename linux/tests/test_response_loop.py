from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kolmafa import bridge, cli, db, llm


def _configure_fixture(monkeypatch, tmp_path: Path, player: str = "player") -> Path:  # noqa: ANN001
    database_path = tmp_path / "kolmafa.db"
    kolmafia_home = tmp_path / "kolmafia"
    session_dir = kolmafia_home / "sessions"
    session_path = session_dir / f"{player}.txt"
    session_dir.mkdir(parents=True)
    session_path.write_text("boot without private data\n", encoding="utf-8")

    monkeypatch.setenv("KOLMAFA_DB", str(database_path))
    monkeypatch.setenv("KOLMAFA_TRANSPORT", "docker-free")
    monkeypatch.setenv("KOLMAFA_KOLMAFIA_HOME", str(kolmafia_home))
    monkeypatch.setenv("KOLMAFA_PLAYER_NAME", player)
    return session_path


def test_loop_once_proposes_for_new_event_without_echoing_body(monkeypatch, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    session_path = _configure_fixture(monkeypatch, tmp_path)

    assert cli.main(["observe", "player"]) == 0
    capsys.readouterr()
    with session_path.open("a", encoding="utf-8") as file:
        file.write("> KOLMAFA_USER: run shell please token=redaction-marker-loop\n")

    assert cli.main(["loop", "player", "--once", "--poll-interval", "0"]) == 0
    output = capsys.readouterr().out

    assert "response_event_id:" in output
    assert "response_proposal: KOL-AI: hello, I am online" in output
    assert "response_status: proposed; write-back deferred; not executed" in output
    assert "run shell please" not in output
    assert "redaction-marker-loop" not in output


def test_loop_once_does_not_duplicate_cursored_events(monkeypatch, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    session_path = _configure_fixture(monkeypatch, tmp_path)

    assert cli.main(["observe", "player"]) == 0
    capsys.readouterr()
    with session_path.open("a", encoding="utf-8") as file:
        file.write("KOLMAFA_USER: first\n")

    assert cli.main(["loop", "player", "--once"]) == 0
    first_output = capsys.readouterr().out
    assert "response_status: proposed; write-back deferred; not executed" in first_output

    assert cli.main(["loop", "player", "--once"]) == 0
    second_output = capsys.readouterr().out
    assert "response_event_id:" not in second_output
    assert "response_status: no_new_events; write-back deferred; not executed" in second_output


def test_loop_once_clean_no_event_behavior(monkeypatch, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    _configure_fixture(monkeypatch, tmp_path)

    assert cli.main(["loop", "player", "--once"]) == 0
    output = capsys.readouterr().out

    assert output.strip() == "response_status: no_new_events; write-back deferred; not executed"


def test_loop_max_events_exits_after_finite_proposal(monkeypatch, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    session_path = _configure_fixture(monkeypatch, tmp_path)

    assert cli.main(["observe", "player"]) == 0
    capsys.readouterr()
    with session_path.open("a", encoding="utf-8") as file:
        file.write("KOLMAFA_USER: one\n")

    assert cli.main(["loop", "player", "--max-events", "1", "--poll-interval", "0"]) == 0
    output = capsys.readouterr().out

    assert output.count("response_status: proposed; write-back deferred; not executed") == 1
    assert "response_status: no_new_events" not in output


def test_loop_keyboard_interrupt_exits_cleanly(monkeypatch, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    _configure_fixture(monkeypatch, tmp_path)

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", interrupt)

    assert cli.main(["loop", "player", "--poll-interval", "0"]) == 0
    output = capsys.readouterr().out

    assert "response_status: no_new_events; write-back deferred; not executed" in output
    assert "loop_status: interrupted; write-back deferred; not executed" in output


def test_loop_safety_invariant_no_live_write_back(monkeypatch, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    session_path = _configure_fixture(monkeypatch, tmp_path)

    def fail_if_live_writer_called(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("loop must not invoke live or dry-run GCLI write paths")

    monkeypatch.setattr(bridge, "send_gcli_dry_run_command", fail_if_live_writer_called)
    monkeypatch.setattr(bridge, "send_relay_command", fail_if_live_writer_called)
    assert cli.main(["observe", "player"]) == 0
    capsys.readouterr()
    with session_path.open("a", encoding="utf-8") as file:
        file.write("KOLMAFA_USER: adventure now\n")

    assert cli.main(["loop", "player", "--once"]) == 0
    output = capsys.readouterr().out

    assert "response_proposal: KOL-AI: hello, I am online" in output
    assert "not executed" in output
    with db.connect(tmp_path / "kolmafa.db") as connection:
        assert connection.execute("SELECT count(*) FROM command_log").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# _sanitize_provider_text — unit tests
# ---------------------------------------------------------------------------


class TestSanitizeProviderText:
    """Direct unit tests for ``bridge._sanitize_provider_text``."""

    def test_plain_text_passes_through(self) -> None:
        assert bridge._sanitize_provider_text("hello, I am online") == "hello, I am online"

    def test_nested_json_passes_through(self) -> None:
        text = '{"message": "hello", "confidence": 0.95}'
        assert bridge._sanitize_provider_text(text) == text

    def test_list_json_passes_through(self) -> None:
        text = '["hello", "world"]'
        assert bridge._sanitize_provider_text(text) == text

    def test_detects_openai_tool_calls(self) -> None:
        text = json.dumps({
            "tool_calls": [{"id": "call_123", "function": {"name": "run_command", "arguments": "{}"}}]
        })
        result = bridge._sanitize_provider_text(text)
        assert "proposal only" in result
        assert "tool/function" in result

    def test_detects_tool_calls_in_wider_object(self) -> None:
        text = json.dumps({"choices": [{"message": {"tool_calls": [{"function": {"name": "x"}}]}}]})
        result = bridge._sanitize_provider_text(text)
        assert "proposal only" in result
        assert "tool/function" in result

    def test_detects_function_call(self) -> None:
        text = '{"function_call": {"name": "run", "arguments": "{}"}}'
        result = bridge._sanitize_provider_text(text)
        assert "proposal only" in result

    def test_detects_function_block(self) -> None:
        text = '{"message": {"role": "assistant", "function": {"name": "act"}}}'
        result = bridge._sanitize_provider_text(text)
        assert "proposal only" in result

    def test_detects_command_key(self) -> None:
        text = '{"command": "cast 10 noodles"}'
        result = bridge._sanitize_provider_text(text)
        assert "proposal only" in result

    def test_detects_action_key(self) -> None:
        text = '{"action": "adventure", "location": "castle"}'
        result = bridge._sanitize_provider_text(text)
        assert "proposal only" in result

    def test_empty_string_returns_unchanged(self) -> None:
        assert bridge._sanitize_provider_text("") == ""

    def test_emoji_and_toolcall_emoji_already_stripped(self) -> None:
        text = '{"tool_calls": [{"function": {"name": "do"}}]}'
        result = bridge._sanitize_provider_text(text)
        assert "proposal only" in result

    def test_invalid_json_non_dict_starts_with_brace(self) -> None:
        text = "{not valid json}"
        result = bridge._sanitize_provider_text(text)
        # invalid JSON that starts with { but doesn't have tool markers: return as-is
        assert result == text

    def test_non_json_plain_text_with_curly_braces_passes(self) -> None:
        text = "use the {item} in the {location}"
        result = bridge._sanitize_provider_text(text)
        assert result == text


# ---------------------------------------------------------------------------
# _sanitize_provider_text — integration via build_llm_response_proposal
# ---------------------------------------------------------------------------


class TestLLMResponseProposalSanitization:
    """Integration tests: ``build_llm_response_proposal`` sanitizes toolcall output."""

    def _make_event(self, message: str = "hello") -> bridge.SessionPrefixEvent:
        return bridge.SessionPrefixEvent(
            event_id="test-event-001",
            player_name="player",
            message_redacted=message,
            source_surface="session",
            provenance={"test": True},
        )

    def _make_connection(self, tmp_path: Path) -> Any:
        db_path = tmp_path / "test.db"
        db.init_database(db_path)
        return db.connect(db_path)

    def _make_toolcall_provider(self, text: str) -> object:
        """Return a provider that returns the given text."""

        class _ToolcallProvider:
            async def generate(  # type: ignore[misc]
                self, prompt: str, system_prompt: str
            ) -> llm.LLMResponse:
                return llm.LLMResponse(text=text)

        return _ToolcallProvider()

    def test_toolcall_json_replaced_with_safe_text(self, tmp_path: Path) -> None:
        event = self._make_event()
        conn = self._make_connection(tmp_path)
        provider = self._make_toolcall_provider(
            '{"tool_calls": [{"function": {"name": "x", "arguments": "{}"}}]}'
        )
        result = bridge.build_llm_response_proposal(event, conn, provider)
        assert result is not None
        assert "KOL-AI:" in result
        assert "proposal only" in result
        assert "tool/function" in result
        conn.close()

    def test_function_call_json_replaced_with_safe_text(self, tmp_path: Path) -> None:
        event = self._make_event()
        conn = self._make_connection(tmp_path)
        provider = self._make_toolcall_provider(
            '{"function_call": {"name": "run_command"}}'
        )
        result = bridge.build_llm_response_proposal(event, conn, provider)
        assert result is not None
        assert "KOL-AI:" in result
        assert "proposal only" in result
        conn.close()

    def test_action_command_json_replaced_with_safe_text(self, tmp_path: Path) -> None:
        event = self._make_event()
        conn = self._make_connection(tmp_path)
        provider = self._make_toolcall_provider(
            '{"command": "cast 10 noodles"}'
        )
        result = bridge.build_llm_response_proposal(event, conn, provider)
        assert result is not None
        assert "KOL-AI:" in result
        assert "proposal only" in result
        assert "action request" in result
        conn.close()

    def test_plain_text_response_unchanged(self, tmp_path: Path) -> None:
        event = self._make_event()
        conn = self._make_connection(tmp_path)
        provider = self._make_toolcall_provider("How can I help you today?")
        result = bridge.build_llm_response_proposal(event, conn, provider)
        assert result is not None
        assert "KOL-AI: How can I help you today?" in result
        conn.close()


# ── Provider selection regression tests (T10 / CV_STATIC_PROVIDER) ──────────


def test_get_provider_default_is_static_even_with_ollama_url(monkeypatch) -> None:  # noqa: ANN001
    """get_provider() returns StaticProvider even when OLLAMA_BASE_URL is set."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://dummy:1234")
    provider = llm.get_provider()
    assert isinstance(provider, llm.StaticProvider)


def test_get_provider_static_returns_static_provider() -> None:
    """get_provider("static") returns a StaticProvider instance."""
    provider = llm.get_provider("static")
    assert isinstance(provider, llm.StaticProvider)


def test_get_provider_ollama_returns_ollama_provider() -> None:
    """get_provider("ollama") returns an OllamaProvider instance."""
    provider = llm.get_provider("ollama")
    assert isinstance(provider, llm.OllamaProvider)


def test_get_provider_bad_raises_value_error() -> None:
    """get_provider("bad") raises ValueError."""
    with pytest.raises(ValueError, match="Unknown LLM provider kind"):
        llm.get_provider("bad")


def test_respond_smart_alone_uses_static_provider(monkeypatch, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    """--smart alone calls get_provider("static") — StaticProvider is the default."""
    _configure_fixture(monkeypatch, tmp_path)
    calls: list[str] = []
    original_get_provider = llm.get_provider

    def tracking_get_provider(kind: str = "static") -> llm.LLMProvider:
        calls.append(kind)
        return original_get_provider(kind)

    monkeypatch.setattr(llm, "get_provider", tracking_get_provider)
    assert cli.main(["respond", "player", "--smart"]) == 0
    assert calls == ["static"]


def test_respond_smart_provider_static_uses_static_provider(monkeypatch, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    """--smart --provider static calls get_provider("static")."""
    _configure_fixture(monkeypatch, tmp_path)
    calls: list[str] = []
    original_get_provider = llm.get_provider

    def tracking_get_provider(kind: str = "static") -> llm.LLMProvider:
        calls.append(kind)
        return original_get_provider(kind)

    monkeypatch.setattr(llm, "get_provider", tracking_get_provider)
    assert cli.main(["respond", "player", "--smart", "--provider", "static"]) == 0
    assert calls == ["static"]


def test_respond_smart_provider_ollama_requests_ollama_provider(monkeypatch, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    """--smart --provider ollama calls get_provider("ollama")."""
    _configure_fixture(monkeypatch, tmp_path)
    calls: list[str] = []
    original_get_provider = llm.get_provider

    def tracking_get_provider(kind: str = "static") -> llm.LLMProvider:
        calls.append(kind)
        return original_get_provider(kind)

    monkeypatch.setattr(llm, "get_provider", tracking_get_provider)
    assert cli.main(["respond", "player", "--smart", "--provider", "ollama"]) == 0
    assert calls == ["ollama"]
