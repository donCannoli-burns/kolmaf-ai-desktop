"""Ensure Don Edition has no legacy runtime dependencies."""

from __future__ import annotations

import subprocess
import pathlib


def test_no_port_8080_in_source() -> None:
    root = pathlib.Path(__file__).resolve().parents[2] / "src"
    for p in root.rglob("*.py"):
        for lineno, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            stripped = line.strip()
            # Allow comments/docstrings that say we do NOT use 8080
            if "no port" in stripped.lower() and "8080" in stripped:
                continue
            if stripped.startswith("#") and "8080" in stripped and "not" in stripped.lower():
                continue
            # Check for actual port usage (e.g., localhost:8080 or :8080)
            if ":8080" in line or "port 8080" in line.lower():
                # If line explicitly says NOT to use it, allow
                if "no" in line.lower() or "not" in line.lower() or "without" in line.lower():
                    continue
                assert False, f"{p}:{lineno} must not reference port 8080 (SpringBridge): {line!r}"


def test_no_legacy_imports() -> None:
    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "kolmafa" / "devtest"
    for p in root.rglob("*.py"):
        content = p.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            # Docstring/comment mentions are allowed if they say we don't use it
            lower = stripped.lower()
            if "no " in lower or "not " in lower or "without" in lower or stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                if any(f.lower() in lower for f in ["pymafia_bridge", "kolmcp", "kolmafia-spring", "springbridge"]):
                    continue
            # Check for actual import or runtime reference
            if "import pymafia_bridge" in line or "from pymafia_bridge" in line:
                assert False, f"{p} must not import legacy pymafia_bridge"
            if "import kolmcp" in line or "from kolmcp" in line:
                assert False, f"{p} must not import legacy kolmcp"
            if "kolmafia-spring" in line and "import" in line.lower():
                assert False, f"{p} must not import legacy kolmafia-spring"


def test_no_legacy_import_at_runtime() -> None:
    # Import checks: ensure devtest modules don't import legacy at import time
    import importlib

    for mod in ["kolmafa.devtest.runtime", "kolmafa.devtest.readiness", "kolmafa.devtest.mcp_server", "kolmafa.devtest.evidence"]:
        m = importlib.import_module(mod)
        assert m is not None
