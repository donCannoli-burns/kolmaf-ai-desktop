"""Kolmafa command-line interface."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sqlite3
from pathlib import Path
import shlex
import time

from kolmafa import (
    bridge,
    capability_import,
    db,
    libkol_db_inspection,
    llm,
    rag,
    source_catalog,
)
from kolmafa.config import ConfigError, get_settings
from kolmafa.policy import ActionClass, ActionRequest, ModeState, PolicyDecision, PolicyEngine
from kolmafa.redaction import redact_text


DEEP_THINKING_MODE = "deep-thinking"
NORMAL_PLAY_MODE = "normal"


class _KolmafaArgumentParser(argparse.ArgumentParser):
    """Argument parser with command-specific validation hooks."""

    def parse_args(
        self,
        args: list[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> argparse.Namespace:
        parsed = super().parse_args(args, namespace)
        if parsed.command == "inspect-libkol-db":
            explicit_path = parsed.database_path or parsed.database_path_arg
            if explicit_path is None:
                self.error("inspect-libkol-db requires an explicit --db path")
            if parsed.database_path is not None and parsed.database_path_arg is not None:
                self.error("inspect-libkol-db accepts either --db or a positional path, not both")
            parsed.database_path = explicit_path
        if parsed.command == "load-source-catalog":
            if not parsed.source_dump_paths and not parsed.libkol_inspection_json_paths:
                self.error("load-source-catalog requires at least one explicit source input")
        return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""

    parser = _KolmafaArgumentParser(prog="kolmafa")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the SQLite database")

    subparsers.add_parser("doctor", help="Check bridge paths and docker-free readiness")

    inspect_libkol = subparsers.add_parser(
        "inspect-libkol-db",
        help="Read-only deterministic inspection for an explicit libkol SQLite DB",
    )
    inspect_libkol.add_argument("database_path_arg", nargs="?", type=Path, metavar="DB")
    inspect_libkol.add_argument("--db", type=Path, default=None, dest="database_path")
    inspect_libkol.add_argument(
        "--json",
        action="store_true",
        help="Print deterministic JSON result instead of text summary",
    )

    capability_load = subparsers.add_parser(
        "load-capability-import",
        help="Offline replace-load capability CSV authority into an explicit SQLite database",
    )
    capability_load.add_argument("--db", required=True, type=Path, dest="database_path")
    capability_load.add_argument("--capability-csv", required=True, type=Path)
    capability_load.add_argument("--priority-csv", required=True, type=Path)
    capability_load.add_argument(
        "--json",
        action="store_true",
        help="Print deterministic JSON result instead of text summary",
    )
    capability_load.add_argument(
        "--expect-sha256",
        action="append",
        default=None,
        metavar="CORPUS=HEX",
        help="Fail closed unless the named input artifact has the expected SHA256 (repeatable)",
    )

    authority_report = subparsers.add_parser(
        "authority-report",
        help="Read-only report for an explicit SQLite capability authority database",
    )
    authority_report.add_argument("--db", required=True, type=Path, dest="database_path")
    authority_report.add_argument("--capability-csv", type=Path, default=None)
    authority_report.add_argument("--priority-csv", type=Path, default=None)
    authority_report.add_argument(
        "--hashtable",
        action="append",
        type=Path,
        default=None,
        dest="hashtable_paths",
        help="Advisory frozen hashtable artifact path (repeatable)",
    )
    authority_report.add_argument("--provenance", type=Path, default=None, dest="provenance_path")
    authority_report.add_argument(
        "--json",
        action="store_true",
        help="Print deterministic JSON result instead of text summary",
    )

    capability_validate = subparsers.add_parser(
        "validate-capability-import",
        help="Validate canonical capability CSV artifacts without importing or executing actions",
    )
    capability_validate.add_argument("paths", nargs="+", type=Path)
    capability_validate.add_argument(
        "--json",
        action="store_true",
        help="Print deterministic JSON result instead of text summary",
    )
    capability_validate.add_argument(
        "--expect-sha256",
        action="append",
        default=None,
        metavar="CORPUS=HEX",
        help="Fail closed unless the named input artifact has the expected SHA256 (repeatable)",
    )

    source_catalog_validate = subparsers.add_parser(
        "validate-source-catalog",
        help="Validate an explicit KOL_Master source catalog dump without importing or network behavior",
    )
    source_catalog_validate.add_argument("path", type=Path)
    source_catalog_validate.add_argument(
        "--json",
        action="store_true",
        help="Print deterministic redaction-safe JSON result instead of text summary",
    )

    source_catalog_load = subparsers.add_parser(
        "load-source-catalog",
        help="Offline merge-load normalized source catalog rows into an explicit SQLite database",
    )
    source_catalog_load.add_argument("--db", required=True, type=Path, dest="database_path")
    source_catalog_load.add_argument(
        "--source-dump",
        action="append",
        type=Path,
        default=None,
        dest="source_dump_paths",
        help="Explicit KOL_Master source dump path to parse and load (repeatable)",
    )
    source_catalog_load.add_argument(
        "--libkol-inspection-json",
        action="append",
        type=Path,
        default=None,
        dest="libkol_inspection_json_paths",
        help="Explicit inspect-libkol-db --json proposal artifact to load (repeatable)",
    )
    source_catalog_load.add_argument(
        "--json",
        action="store_true",
        help="Print deterministic JSON result instead of text summary",
    )

    ingest = subparsers.add_parser("ingest", help="Ingest files/directories into FTS5")
    ingest.add_argument("paths", nargs="+", type=Path)
    ingest.add_argument(
        "--allow-root",
        action="append",
        type=Path,
        default=None,
        dest="allow_roots",
        help="Allowlist root dirs for RAG source validation (repeatable; defaults to ingested paths)",
    )

    search = subparsers.add_parser("search", help="Search local FTS5 context")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    observe = subparsers.add_parser(
        "observe",
        help="Parse current KOLMAFA_USER session-log events once without tailing",
    )
    observe.add_argument("player_name")

    listen = subparsers.add_parser(
        "listen",
        help="Alias for observe; parse appended KOLMAFA_USER events without raw log output",
    )
    listen.add_argument("player_name")

    respond = subparsers.add_parser(
        "respond",
        help="Observe new KOLMAFA_USER events and print response proposals",
    )
    respond.add_argument("player_name")
    respond.add_argument(
        "--smart",
        action="store_true",
        help="Use the configured LLM provider (Ollama/static) for smarter proposals",
    )
    respond.add_argument(
        "--provider",
        choices=["static", "ollama"],
        default="static",
        help="LLM provider kind (default: static)",
    )

    loop = subparsers.add_parser(
        "loop",
        help="Continuously observe KOLMAFA_USER events and print dry-run response proposals",
    )
    loop.add_argument("player_name", nargs="?")
    loop.add_argument(
        "--once",
        action="store_true",
        help="Poll once and exit, useful for tests and smoke checks",
    )
    loop.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Exit after proposing this many events",
    )
    loop.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between session-log polls in continuous mode",
    )
    loop.add_argument(
        "--smart",
        action="store_true",
        help="Use the configured LLM provider (Ollama/static) for smarter proposals",
    )
    loop.add_argument(
        "--provider",
        choices=["static", "ollama"],
        default="static",
        help="LLM provider kind (default: static)",
    )

    propose = subparsers.add_parser(
        "propose",
        help="Evaluate a relay command proposal without executing it",
    )
    propose.add_argument("gcli_command")
    propose.add_argument("--mode", default=NORMAL_PLAY_MODE)
    propose.add_argument("--state-binding", default="")

    dry_run = subparsers.add_parser(
        "dry-run",
        help="Submit a relay command through the policy-bound dry-run writer only",
    )
    dry_run.add_argument("gcli_command")
    dry_run.add_argument("--timeout", type=float, default=None)
    dry_run.add_argument("--confirmation-id", help="Durable confirmation id for game-affecting dry-runs")
    dry_run.add_argument("--actor-id", default="operator", help="Operator actor id bound to confirmation")
    dry_run.add_argument("--mode", default=NORMAL_PLAY_MODE, help="Current safety mode for policy evaluation")
    dry_run.add_argument("--state-binding", default="", help="State binding string checked against confirmation")

    send = subparsers.add_parser("send", help="Submit a relay command through the reviewed send gate")
    send.add_argument("gcli_command")
    send.add_argument("--timeout", type=float, default=None)
    send.add_argument(
        "--offline-ok",
        action="store_true",
        help="Allow the offline Docker CLI fallback that starts a second KoLmafia process",
    )
    send.add_argument("--confirmation-id", help="Durable confirmation id for game-affecting sends")
    send.add_argument("--actor-id", default="operator", help="Operator actor id bound to confirmation")
    send.add_argument("--mode", default="normal", help="Current safety mode for policy evaluation")
    send.add_argument("--state-binding", default="", help="State binding string checked against confirmation")

    tail = subparsers.add_parser("tail", help="Tail KoLmafia session log")
    tail.add_argument(
        "--once",
        action="store_true",
        help="Print currently visible redacted KOLMAFA_USER lines once and exit",
    )
    tail.add_argument("player_name")

    eval_cmd = subparsers.add_parser("eval", help="Run retrieval evaluation against a Q&A dataset")
    eval_cmd.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/eval/dataset.json"),
        help="Path to eval dataset JSON (default: data/eval/dataset.json)",
    )
    eval_cmd.add_argument(
        "--report-file",
        type=Path,
        default=None,
        help="Write JSON report to file instead of stdout",
    )
    eval_cmd.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of search results per question (default: 10)",
    )
    eval_cmd.add_argument(
        "--score-threshold",
        type=float,
        default=-5.0,
        help="BM25 score threshold for low-score detection (default: -5.0)",
    )

    repl = subparsers.add_parser(
        "repl",
        help="Safe CLI/REPL operator loop for diagnostics, search, observe, and proposals",
    )
    repl.add_argument("--mode", choices=[NORMAL_PLAY_MODE, DEEP_THINKING_MODE], default=NORMAL_PLAY_MODE)
    repl.add_argument(
        "--once",
        help="Run one REPL command non-interactively, useful for smoke tests",
    )

    return parser


def _print_status(status: bridge.BridgeStatus) -> None:
    """Print bridge diagnostics without changing game state."""

    print(f"database: {redact_text(status.database_path)}")
    print(f"kolmafia_home: {redact_text(status.kolmafia_home)}")
    print(f"session_dir: {redact_text(status.session_dir)} exists={status.session_dir.exists()}")
    print(f"cli_command: {redact_text(status.cli_command or '<unset>')}")
    print(f"transport: {status.transport}")
    print(f"relay_base_url: {redact_text(status.relay_base_url)}")
    print(f"relay_pwd_configured: {status.relay_pwd_configured}")
    print(f"player_name: {redact_text(status.player_name or '<unset>')}")
    print(f"session_file: {redact_text(status.session_file or '<unset>')}")
    print(f"docker_free_ready: {status.docker_free_ready}")
    if status.docker_free_problems:
        print(f"docker_free_problems: {', '.join(status.docker_free_problems)}")
    print(f"docker_available: {status.docker_available}")
    if status.container_running is not None:
        print(f"container_running: {status.container_running}")


def _policy_decision(command: str, mode: str, state_binding: str = "") -> PolicyDecision:
    """Evaluate a relay proposal without executing transport."""

    normalized = command.strip()
    if normalized != normalized.lower() or normalized != command:
        return PolicyDecision(False, ActionClass.UNSAFE_UNKNOWN, "noncanonical relay command not reviewed")

    engine = PolicyEngine(bridge.DEFAULT_RELAY_ALLOWLIST)
    return engine.decide(
        ActionRequest(command=normalized, mode=mode, arguments={"command": normalized}),
        ModeState(mode=mode, state_binding=state_binding),
    )


def _print_proposal(command: str, decision: PolicyDecision) -> None:
    """Print a redacted no-action relay proposal."""

    print(f"proposal: {redact_text(command)}")
    print(f"class: {decision.command_class.value}")
    print(f"allowed: {str(decision.allowed).lower()}")
    print(f"requires_confirmation: {str(decision.requires_confirmation).lower()}")
    if decision.allowlist_id:
        print(f"allowlist_id: {decision.allowlist_id}")
    print(f"reason: {redact_text(decision.reason)}")
    print("not executed: proposals never call the relay transport")


def _observe_once(player_name: str) -> int:
    """Observe current prefixed session-log lines once."""

    settings = get_settings()
    db.init_database(settings.database_path)
    session_path = bridge.session_file(settings.kolmafia_home, player_name)
    with db.connect(settings.database_path) as connection:
        events = bridge.observe_session_file(session_path, player_name, connection)
    suffix = "" if len(events) == 1 else "s"
    print(f"observed {len(events)} session event{suffix}")
    for event in events:
        print(f"[{event.event_id[:12]}] {event.message_redacted}")
    return 0


def _respond_once(player_name: str, *, smart: bool = False, provider: str = "static") -> int:
    """Observe appended events and print console-only safe response proposals."""

    provider_instance = llm.get_provider(provider) if smart else None
    events, connection = _observe_response_events(player_name)
    try:
        printed_count = _print_response_proposals(events, connection, provider=provider_instance)
        if printed_count < 0:
            return 1
        return 0
    finally:
        connection.close()


def _print_response_proposals(
    events: list[bridge.SessionPrefixEvent],
    connection: sqlite3.Connection,
    *,
    provider: object = None,
) -> int:
    """Print console-only safe response proposals for observed events.

    If a provider is given (e.g. StaticProvider or OllamaProvider), the LLM
    synthesis path is used.  Otherwise the deterministic smart-RAG path builds
    a proposal from FTS5 snippets.
    """

    if not events:
        print("response_status: no_new_events; write-back deferred; not executed")
        return 0

    for event in events:
        if provider is not None:
            proposal = bridge.build_llm_response_proposal(event, connection, provider)
        else:
            proposal = bridge.build_smart_response_proposal(event, connection)
        if proposal is None:
            proposal = bridge.build_fixed_response_proposal()
        if proposal is None:
            print(f"response_status: failed for {event.event_id[:12]}; not executed")
            return -1
        print(f"response_event_id: {event.event_id}")
        print(f"response_proposal: {proposal}")
        print("response_status: proposed; write-back deferred; not executed")
    return len(events)


def _observe_response_events(player_name: str) -> tuple[list[bridge.SessionPrefixEvent], sqlite3.Connection]:
    """Observe appended response-loop events using the durable session cursor."""

    settings = get_settings()
    db.init_database(settings.database_path)
    session_path = bridge.session_file(settings.kolmafia_home, player_name)
    connection = db.connect(settings.database_path)
    events = bridge.observe_session_file(session_path, player_name, connection)
    return events, connection


def _loop_responses(
    player_name: str,
    *,
    once: bool,
    max_events: int | None,
    poll_interval: float,
    smart: bool = False,
    provider: str = "static",
) -> int:
    """Run the docker-free dry-run response loop without live write-back."""

    provider_instance = llm.get_provider(provider) if smart else None

    if max_events is not None and max_events < 1:
        print("usage: loop <player_name> [--max-events N>=1]")
        return 2
    if poll_interval < 0:
        print("usage: loop <player_name> [--poll-interval SECONDS>=0]")
        return 2

    proposed_events = 0
    try:
        while True:
            events, connection = _observe_response_events(player_name)
            try:
                printed_count = _print_response_proposals(events, connection, provider=provider_instance)
                if printed_count < 0:
                    return 1
                proposed_events += printed_count
            finally:
                connection.close()
            if once or (max_events is not None and proposed_events >= max_events):
                return 0
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("loop_status: interrupted; write-back deferred; not executed")
        return 0


def _dry_run_once(
    command: str,
    *,
    timeout: float | None,
    confirmation_id: str | None,
    actor_id: str,
    mode: str,
    state_binding: str,
) -> int:
    """Run the policy-bound dry-run writer and print redacted audit-safe output."""

    settings = get_settings()
    db.init_database(settings.database_path)
    with db.connect(settings.database_path) as connection:
        result = bridge.send_gcli_dry_run_command(
            command,
            timeout or settings.send_timeout,
            connection=connection,
            confirmation_id=confirmation_id,
            actor_id=actor_id,
            mode=mode,
            state_binding=state_binding,
        )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    print("not executed: dry-run writer never contacts live transports")
    return result.return_code


def _search_once(query: str, limit: int = 10) -> int:
    """Run a safe local FTS5 search with explicit no-corpus messaging."""

    settings = get_settings()
    with db.connect(settings.database_path) as connection:
        rows = rag.search(connection, query, limit)
    if not rows:
        print("no local FTS5 results; not executed")
        return 0
    for row in rows:
        title = redact_text(row["title"])
        source_path = redact_text(row["source_path"])
        source_label = redact_text(row["source_label"] or "source")
        snippet = redact_text(row["snippet"])
        print(f"[{row['rowid']}] {title} — {source_label}: {source_path}\n{snippet}\n")
    print("not executed: search results are advisory context only")
    return 0


def _run_repl_command(line: str, mode: str) -> int:
    """Run one safe operator-loop command."""

    command_line = line.strip()
    if not command_line:
        return 0

    command, _, rest = command_line.partition(" ")
    match command:
        case "doctor":
            settings = get_settings()
            _print_status(
                bridge.check_status(
                    settings.database_path,
                    settings.kolmafia_home,
                    settings.cli_command,
                    settings.transport,
                    settings.relay_base_url,
                    settings.relay_pwd,
                    settings.player_name,
                )
            )
            print("not executed: diagnostics are read-only")
            return 0
        case "search":
            return _search_once(rest)
        case "observe" | "listen":
            if not rest.strip():
                print(f"usage: {command} <player_name>")
                return 2
            return _observe_once(rest.strip())
        case "respond":
            parts = shlex.split(rest)
            if not parts:
                print("usage: respond <player_name> [--smart] [--provider {static,ollama}]")
                return 2
            respond_parser = argparse.ArgumentParser(prog="respond", add_help=False)
            respond_parser.add_argument("player_name")
            respond_parser.add_argument("--smart", action="store_true")
            respond_parser.add_argument("--provider", choices=["static", "ollama"], default="static")
            try:
                respond_args = respond_parser.parse_args(parts)
            except SystemExit:
                return 2
            try:
                return _respond_once(respond_args.player_name, smart=respond_args.smart, provider=respond_args.provider)
            except (ConfigError, ValueError, bridge.BridgeError) as exc:
                print(f"config_error: {redact_text(str(exc))}")
                return 1
        case "loop":
            parts = shlex.split(rest)
            if not parts:
                print("usage: loop <player_name> [--once] [--max-events N] [--poll-interval SECONDS] [--smart] [--provider {static,ollama}]")
                return 2
            loop_parser = argparse.ArgumentParser(prog="loop", add_help=False)
            loop_parser.add_argument("player_name", nargs="?")
            loop_parser.add_argument("--once", action="store_true")
            loop_parser.add_argument("--max-events", type=int, default=None)
            loop_parser.add_argument("--poll-interval", type=float, default=1.0)
            loop_parser.add_argument("--smart", action="store_true")
            loop_parser.add_argument("--provider", choices=["static", "ollama"], default="static")
            try:
                loop_args = loop_parser.parse_args(parts)
            except SystemExit:
                return 2
            try:
                return _loop_responses(
                    loop_args.player_name or get_settings().player_name or "",
                    once=loop_args.once,
                    max_events=loop_args.max_events,
                    poll_interval=loop_args.poll_interval,
                    smart=loop_args.smart,
                    provider=loop_args.provider,
                )
            except (ConfigError, ValueError, bridge.BridgeError) as exc:
                print(f"config_error: {redact_text(str(exc))}")
                return 1
        case "propose":
            if not rest.strip():
                print("usage: propose <relay_command>")
                return 2
            _print_proposal(rest.strip(), _policy_decision(rest.strip(), mode))
            return 0
        case "dry-run":
            if not rest.strip():
                print("usage: dry-run <relay_command>")
                return 2
            return _dry_run_once(
                rest.strip(),
                timeout=None,
                confirmation_id=None,
                actor_id="operator",
                mode=mode,
                state_binding="",
            )
        case "send":
            if mode == DEEP_THINKING_MODE:
                print("deep-thinking mode is no-action by default; not executed")
                return 2
            print("live send is not a REPL shortcut; run 'propose <command>' and use gated CLI send")
            print("not executed")
            return 2
        case "help":
            print(
                "commands: doctor, search <query>, observe <player>, listen <player>, "
                "respond <player>, loop <player>, propose <command>, dry-run <command>, help, exit"
            )
            return 0
        case "exit" | "quit":
            return 0
        case _:
            safe = shlex.quote(command)
            print(f"unknown safe-loop command: {safe}; not executed")
            return 2


def _run_repl(mode: str, once: str | None) -> int:
    """Run the interactive safe operator loop."""

    if once is not None:
        return _run_repl_command(once, mode)

    print(f"kolmafa safe operator loop ({mode}); type help or exit")
    while True:
        try:
            line = input("kolmafa> ")
        except EOFError:
            print()
            return 0
        if line.strip() in {"exit", "quit"}:
            return 0
        _run_repl_command(line, mode)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""

    args = build_parser().parse_args(argv)

    if args.command == "load-capability-import":
        try:
            expected_sha256 = _parse_checksum_expectations(args.expect_sha256 or [])
        except ValueError as exc:
            print(f"usage: load-capability-import --expect-sha256 CORPUS=64_HEX: {exc}")
            return 2
        result = capability_import.load_capability_authority(
            args.database_path,
            args.capability_csv,
            args.priority_csv,
            expected_sha256=expected_sha256,
        )
        if args.json:
            print(capability_import.load_result_to_json(result))
        else:
            _print_capability_load_result(result)
        return 0 if result.ok else 1

    if args.command == "authority-report":
        result = capability_import.build_authority_report(
            args.database_path,
            capability_csv_path=args.capability_csv,
            priority_csv_path=args.priority_csv,
            hashtable_paths=args.hashtable_paths,
            provenance_path=args.provenance_path,
        )
        if args.json:
            print(capability_import.authority_report_to_json(result))
        else:
            _print_authority_report_result(result)
        return 0 if result.ok else 1

    if args.command == "validate-capability-import":
        try:
            expected_sha256 = _parse_checksum_expectations(args.expect_sha256 or [])
        except ValueError as exc:
            print(f"usage: validate-capability-import --expect-sha256 CORPUS=64_HEX: {exc}")
            return 2
        result = capability_import.validate_capability_csv_files(
            args.paths,
            expected_sha256=expected_sha256,
        )
        if args.json:
            print(capability_import.result_to_json(result))
        else:
            status = "ok" if result.ok else "failed"
            print(f"capability_import_validation: {status}")
            print(f"planned_rows: {result.row_count}")
            for artifact in result.artifacts:
                print(
                    "artifact: "
                    f"{artifact.source_corpus} rows={artifact.row_count} "
                    f"columns={artifact.column_count} sha256={artifact.sha256}"
                )
            for error in result.errors:
                row = "" if error.row_number is None else f":{error.row_number}"
                print(f"error: {error.source_corpus}{row}: {error.message}")
            print("not executed: validation is read-only and does not mutate runtime KoL state")
        return 0 if result.ok else 1

    if args.command == "validate-source-catalog":
        result = source_catalog.validate_source_dump_file(args.path)
        if args.json:
            print(source_catalog.result_to_json(result))
        else:
            for line in source_catalog.result_to_text_lines(result):
                print(line)
        return 0 if result.ok else 1

    if args.command == "load-source-catalog":
        result = source_catalog.load_source_catalog_rows(
            args.database_path,
            source_dump_paths=tuple(args.source_dump_paths or ()),
            libkol_inspection_json_paths=tuple(args.libkol_inspection_json_paths or ()),
        )
        if args.json:
            print(source_catalog.load_result_to_json(result))
        else:
            _print_source_catalog_load_result(result)
        return 0 if result.ok else 1

    if args.command == "inspect-libkol-db":
        result = libkol_db_inspection.inspect_database(args.database_path)
        if args.json:
            print(libkol_db_inspection.result_to_json(result))
        else:
            _print_libkol_inspection_result(result)
        return 0 if result.ok else 1

    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"config_error: {redact_text(str(exc))}")
        if args.command == "respond":
            return 1
        return 2

    if args.command == "init-db":
        db.init_database(settings.database_path)
        print(f"initialized {settings.database_path}")
        return 0

    if args.command == "doctor":
        status = bridge.check_status(
            settings.database_path,
            settings.kolmafia_home,
            settings.cli_command,
            settings.transport,
            settings.relay_base_url,
            settings.relay_pwd,
            settings.player_name,
        )
        _print_status(status)
        return 0

    if args.command == "ingest":
        db.init_database(settings.database_path)
        allowed = args.allow_roots or args.paths
        with db.connect(settings.database_path) as connection:
            count = rag.ingest_paths(
                connection,
                args.paths,
                explicit_opt_in=True,
                allowed_roots=allowed,
            )
        print(f"ingested {count} documents")
        return 0

    if args.command == "search":
        return _search_once(args.query, args.limit)

    if args.command in {"observe", "listen"}:
        return _observe_once(args.player_name)

    if args.command == "respond":
        try:
            return _respond_once(args.player_name, smart=args.smart, provider=args.provider)
        except (ConfigError, ValueError, bridge.BridgeError) as exc:
            print(f"config_error: {redact_text(str(exc))}")
            return 1

    if args.command == "loop":
        try:
            return _loop_responses(
                args.player_name or settings.player_name or "",
                once=args.once,
                max_events=args.max_events,
                poll_interval=args.poll_interval,
                smart=args.smart,
                provider=args.provider,
            )
        except (ConfigError, ValueError, bridge.BridgeError) as exc:
            print(f"config_error: {redact_text(str(exc))}")
            return 1

    if args.command == "propose":
        _print_proposal(
            args.gcli_command,
            _policy_decision(args.gcli_command, args.mode, args.state_binding),
        )
        return 0

    if args.command == "dry-run":
        return _dry_run_once(
            args.gcli_command,
            timeout=args.timeout,
            confirmation_id=args.confirmation_id,
            actor_id=args.actor_id,
            mode=args.mode,
            state_binding=args.state_binding,
        )

    if args.command == "send":
        extra_reason = ""
        if bridge.is_docker_cli_fallback(settings.cli_command):
            extra_reason = " The Docker CLI fallback can start a second KoLmafia Java process and is blocked."
        db.init_database(settings.database_path)
        with db.connect(settings.database_path) as connection:
            if settings.transport in {"relay", "docker-free"} and not extra_reason:
                result = bridge.send_gcli_dry_run_command(
                    args.gcli_command,
                    args.timeout or settings.send_timeout,
                    connection=connection,
                    confirmation_id=args.confirmation_id,
                    actor_id=args.actor_id,
                    mode=args.mode,
                    state_binding=args.state_binding,
                )
            else:
                result = bridge.deny_send_result(extra_reason)
                bridge.log_command(connection, result)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")
        return result.return_code

    if args.command == "tail":
        try:
            session_path = bridge.session_file(settings.kolmafia_home, args.player_name)
            if args.once:
                events = bridge.read_safe_session_events(session_path, args.player_name)
                for event in events:
                    print(f"[{event.event_id[:12]}] {event.message_redacted}")
            else:
                bridge.follow_session(session_path, args.player_name)
        except (ValueError, bridge.BridgeError) as exc:
            print(f"tail_error: {redact_text(str(exc))}")
            return 2
        return 0

    if args.command == "eval":
        from kolmafa import eval as kolmafa_eval

        dataset = kolmafa_eval.load_dataset(args.dataset)
        with db.connect(settings.database_path) as connection:
            report = kolmafa_eval.run_evaluation(
                connection, dataset, limit=args.limit, score_threshold=args.score_threshold
            )

        report_dict = asdict(report)
        report_json = json.dumps(report_dict, indent=2, default=str)

        if args.report_file:
            args.report_file.parent.mkdir(parents=True, exist_ok=True)
            args.report_file.write_text(report_json)
            print(f"Report written to {args.report_file}")
        else:
            print(report_json)

        return 0

    if args.command == "repl":
        return _run_repl(args.mode, args.once)

    raise AssertionError(f"Unhandled command: {args.command}")


def _parse_checksum_expectations(values: list[str]) -> dict[str, str]:
    """Parse CORPUS=HEX checksum expectations for read-only CSV validation."""

    expectations: dict[str, str] = {}
    hexdigits = frozenset("0123456789abcdefABCDEF")
    for value in values:
        corpus, separator, checksum = value.partition("=")
        if not separator or not corpus or len(checksum) != 64 or set(checksum) - hexdigits:
            raise ValueError(value)
        expectations[corpus] = checksum.lower()
    return expectations


def _print_capability_load_result(result: capability_import.CapabilityLoadResult) -> None:
    """Print human-readable offline capability import result."""

    print(f"capability_import_load: {result.status}")
    print(f"mode: {result.mode}")
    print(f"capability_records: {result.capability_count}")
    print(f"priority_annotations: {result.annotation_count}")
    for artifact in result.artifacts:
        print(
            "artifact: "
            f"{artifact.source_corpus} rows={artifact.row_count} "
            f"columns={artifact.column_count} sha256={artifact.sha256}"
        )
    for drift in result.drift:
        print(f"drift: {drift}")
    for error in result.errors:
        row = "" if error.row_number is None else f":{error.row_number}"
        print(f"error: {error.source_corpus}{row}: {error.message}")
    print("offline only: SQLite import does not contact KoLmafia or mutate live KoL state")


def _print_source_catalog_load_result(result: source_catalog.SourceCatalogLoadResult) -> None:
    """Print human-readable offline source catalog load result."""

    status = "ok" if result.ok else "failed"
    print(f"source_catalog_load: {status}")
    print(f"mode: {result.mode}")
    print(f"inserted: {result.inserted}")
    print(f"unchanged: {result.unchanged}")
    print(f"conflicts: {result.conflicts}")
    print(f"source_catalog: {result.source_catalog_rows}")
    print(f"source_crosswalk: {result.source_crosswalk_rows}")
    print(f"manifest_id: {result.manifest_id}")
    for artifact in result.artifacts:
        print(
            "artifact: "
            f"{artifact['artifact_type']} {artifact['path']} "
            f"rows={artifact['row_count']} sha256={artifact['sha256']}"
        )
    for error in result.errors:
        row = "" if error.row_id is None else f":{error.row_id}"
        print(f"error: {error.artifact}{row}: {error.message}")
    print("offline-only: no live KoL/network behavior")
    print(
        "not executed: source catalog loading does not touch Chroma, "
        "KOL_Master, don-libkol, or runtime KoL state"
    )


def _print_authority_report_result(result: capability_import.AuthorityReportResult) -> None:
    """Print human-readable offline read-only authority report."""

    print(f"authority_report: {result.status}")
    print(f"database: {result.database_path}")
    for name, count in result.counts.items():
        print(f"{name}: {count}")
    for name, checksum in result.authority_checksums.items():
        print(f"authority_checksum.{name}: {checksum}")
    summary = result.priority_annotation_summary
    if summary:
        print(f"priority_annotation_count: {summary['annotation_count']}")
        print(f"priority_fail_closed_if_unresolved_count: {summary['fail_closed_if_unresolved_count']}")
        print(
            "priority_recursive_classification_required_count: "
            f"{summary['recursive_classification_required_count']}"
        )
        for group in summary["risk_fail_closed_groups"]:
            print(
                "priority_group: "
                f"risk={group['risk']} "
                f"fail_closed={group['fail_closed_if_unresolved']} "
                f"recursive={group['recursive_classification_required']} "
                f"count={group['count']}"
            )
    for drift in result.csv_drift:
        print(
            "csv_drift: "
            f"{drift.source_corpus} status={drift.status} "
            f"csv_rows={drift.csv_row_count} db_rows={drift.db_row_count} "
            f"csv_checksum={drift.csv_content_checksum} db_checksum={drift.db_content_checksum}"
        )
        for message in drift.messages:
            print(f"csv_drift_message: {drift.source_corpus}: {message}")
    if result.hashtable_validation is not None:
        print(f"hashtable_validation: {'ok' if result.hashtable_validation.ok else 'failed'}")
        for artifact in result.hashtable_validation.artifacts:
            print(
                "hashtable: "
                f"{artifact.artifact_name} size={artifact.size} capacity={artifact.capacity} "
                f"sha256={artifact.sha256} source={artifact.source}"
            )
        for error in result.hashtable_validation.errors:
            row = "" if error.row_number is None else f":{error.row_number}"
            print(f"hashtable_mismatch: {error.source_corpus}{row}: {error.message}")
    for error in result.errors:
        row = "" if error.row_number is None else f":{error.row_number}"
        print(f"error: {error.source_corpus}{row}: {error.message}")
    print("offline/read-only: report opens an explicit SQLite DB and performs no imports, writes, external calls, or live KoL mutation")


def _print_libkol_inspection_result(result: libkol_db_inspection.LibkolInspectionResult) -> None:
    """Print human-readable offline read-only libkol DB inspection result."""

    payload = result.to_dict()
    proposals = payload["proposals"]
    print(f"libkol_db_inspection: {result.status}")
    print(f"database: {result.summary.get('path', '<unknown>')}")
    print(f"tables: {result.summary.get('table_count', 0)}")
    print(f"rows: {result.summary.get('row_count', 0)}")
    if "sha256" in result.summary:
        print(f"sha256: {result.summary['sha256']}")
    for table in result.tables:
        print(
            f"table: {table.name} columns={len(table.columns)} "
            f"indexes={len(table.indexes)} rows={table.row_count} sha256={table.content_sha256}"
        )
    for error in result.errors:
        print(f"error: {error.code}: {error.message}")
    print(f"proposal_mode: {proposals['write_mode']}")
    for source in proposals["source_catalog"]:
        print(
            "source_catalog_candidate: "
            f"{source['source_id']} {source['category']} "
            f"{source['provenance']['classification']}"
        )
    for crosswalk in proposals["source_crosswalk"]:
        print(
            "source_crosswalk_candidate: "
            f"{crosswalk['graph_category']} {crosswalk['graph_node_key']} "
            f"confidence={crosswalk['confidence']}"
        )
    print("operator_command: kolmafa inspect-libkol-db --db <downloaded-libkol-db> --json")
    print("offline/read-only: inspection opens an explicit SQLite DB and performs no imports, writes, external calls, or live KoL mutation")


if __name__ == "__main__":
    raise SystemExit(main())
