"""Runtime import-graph isolation: prove daemon-core MVP avoids unsafe imports.

Each test spawns a clean subprocess, performs a defined import or parser
construction, and asserts that no forbidden package appears in ``sys.modules``.

All scenarios use isolated subprocesses to prevent cross-contamination from
prior imports in the test runner process.
"""

from __future__ import annotations

import importlib
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest


SRC = str(Path(__file__).resolve().parent.parent / "src")

SURFACE_SIDE_EFFECT_TRAP_PRELUDE = """\
import builtins
_original_import = builtins.__import__
def _trap_import(name, globals=None, locals=None, fromlist=(), level=0):
    blocked = {
        'httpx',
        'socket',
        'urllib.request',
        'kolmafa.llm',
    }
    if name in blocked or (name == 'urllib' and 'request' in fromlist) or (name == 'kolmafa' and 'llm' in fromlist):
        raise AssertionError('surface isolation trap blocked import: ' + name)
    return _original_import(name, globals, locals, fromlist, level)
builtins.__import__ = _trap_import
"""

SCENARIO_TEMPLATE = """\
import sys
sys.path.insert(0, {src!r})
{prelude}
{body}

live_prefix = "kolmafa.live."
forbidden_modules = [
    name for name in sys.modules
    if name == "kolmafa.live" or name.startswith(live_prefix)
    or name in {forbidden_imports!r}
]
if forbidden_modules:
    sys.stdout.write("FAIL: {label} loaded forbidden modules: " + str(sorted(forbidden_modules)) + "\\n")
    raise SystemExit(1)
else:
    sys.stdout.write("OK: {label} did not load forbidden modules\\n")
"""


def _assert_scenario_clean(
    label: str,
    body: str,
    *,
    forbid_network_modules: bool = False,
    trap_surface_dependencies: bool = False,
) -> None:
    """Run a Python snippet in a clean subprocess, check kolmafa.live absence."""
    code = SCENARIO_TEMPLATE.format(
        src=SRC,
        label=label,
        prelude=SURFACE_SIDE_EFFECT_TRAP_PRELUDE if trap_surface_dependencies else "",
        body=body,
        forbidden_imports={"httpx", "urllib.request", "socket"} if forbid_network_modules else set(),
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = result.stdout.strip()
    err = result.stderr.strip()
    print(out)
    if err:
        print(err)

    if result.returncode != 0 or "FAIL" in out:
        raise AssertionError(
            f"Import isolation FAILED for {label} (exit={result.returncode}):\n{out}\n{err}"
        )


# ── Plain-module imports ──────────────────────────────────────────────────────

def test_kolmafa_bridge_does_not_import_live() -> None:
    _assert_scenario_clean("kolmafa.bridge", "import kolmafa.bridge")


def test_kolmafa_llm_does_not_import_live() -> None:
    _assert_scenario_clean("kolmafa.llm", "import kolmafa.llm")


def test_kolmafa_policy_does_not_import_live() -> None:
    _assert_scenario_clean("kolmafa.policy", "import kolmafa.policy")


def test_kolmafa_cli_does_not_import_live() -> None:
    _assert_scenario_clean("kolmafa.cli", "import kolmafa.cli")


def test_kolmafa_init_does_not_import_live() -> None:
    _assert_scenario_clean("kolmafa", "import kolmafa")


# ── Parser construction paths ─────────────────────────────────────────────────

def test_respond_parser_construction_does_not_import_live() -> None:
    _assert_scenario_clean(
        "respond parser (--help)",
        "import kolmafa.cli; kolmafa.cli.build_parser().parse_args(['respond', '--help'])",
    )


def test_loop_parser_construction_does_not_import_live() -> None:
    _assert_scenario_clean(
        "loop parser (--help)",
        "import kolmafa.cli; kolmafa.cli.build_parser().parse_args(['loop', '--help'])",
    )


def test_cli_top_level_help_does_not_import_live() -> None:
    _assert_scenario_clean(
        "top-level --help",
        "import kolmafa.cli; kolmafa.cli.build_parser().parse_args(['--help'])",
    )


# ── Provider construction (no network) ────────────────────────────────────────

def test_static_provider_default_does_not_import_live() -> None:
    _assert_scenario_clean(
        "get_provider() default -> StaticProvider",
        "from kolmafa.llm import get_provider; p = get_provider(); assert type(p).__name__ == 'StaticProvider'",
    )


def test_static_provider_explicit_does_not_import_live() -> None:
    _assert_scenario_clean(
        "get_provider('static') -> StaticProvider",
        "from kolmafa.llm import get_provider; p = get_provider('static'); assert type(p).__name__ == 'StaticProvider'",
    )


def test_surface_import_does_not_load_live_network_or_provider() -> None:
    _assert_scenario_clean(
        "kolmafa.surface import",
        """
import kolmafa.surface
assert 'kolmafa.llm' not in sys.modules
assert 'kolmafa.live' not in sys.modules
""",
        forbid_network_modules=True,
        trap_surface_dependencies=True,
    )


def test_surface_provider_health_does_not_load_live_network_or_provider() -> None:
    _assert_scenario_clean(
        "kolmafa.surface provider_health",
        """
from kolmafa.surface import get_provider_health_surface
response = get_provider_health_surface(request_id='iso', provider_kind='ollama')
assert response.data['network_checked'] is False
assert response.data['ollama_instantiated'] is False
assert 'kolmafa.llm' not in sys.modules
assert 'kolmafa.live' not in sys.modules
""",
        forbid_network_modules=True,
        trap_surface_dependencies=True,
    )


def test_surface_provider_health_respects_monkeypatch_side_effect_traps(monkeypatch: pytest.MonkeyPatch) -> None:
    def trap(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("surface import isolation must not construct providers or perform network I/O")

    monkeypatch.setattr(socket, "socket", trap)
    monkeypatch.setattr(urllib.request, "urlopen", trap)
    try:
        httpx = importlib.import_module("httpx")
    except ImportError:
        httpx = None
    if httpx is not None:
        monkeypatch.setattr(httpx, "AsyncClient", trap)

    llm = importlib.import_module("kolmafa.llm")
    monkeypatch.setattr(llm.OllamaProvider, "__init__", trap)
    monkeypatch.setattr(llm, "get_provider", trap)

    surface = importlib.import_module("kolmafa.surface")
    response = surface.get_provider_health_surface(request_id="iso-monkeypatch", provider_kind="ollama")

    assert response.data["network_checked"] is False
    assert response.data["ollama_instantiated"] is False
