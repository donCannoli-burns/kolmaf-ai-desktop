#!/usr/bin/env python3
"""Shared verifier for the commissioned native.can-equip checkpoint.

Two profiles, one implementation:

- ``--mode portable``: repository-only. Checks the commissioning manifest,
  canonical helper identity/hash, source capability registry, committed
  generated registry/bootstrap agreement, transport/authority coherence, and
  that implementation and commissioning test files parse. Never touches
  ~/.kolmafia, the installed relay helper, live provider health, relay
  reachability, the receipt journal, or a machine-local interpreter.
  Success line: ``PORTABLE CHECKPOINT VALID``.

- ``--mode local``: everything in portable, plus the machine-local
  installation checks: installed relay helper exists and hashes equal to
  canonical, local provider health READY, and local bootstrap freshness
  (READY). Success line: ``LOCAL INSTALLATION CHECKPOINT VALID``.

Read-only in both modes. No network I/O, no proposals, no gameplay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

IMPL_FILES = (
    "src/kolmafa/devtest/native_query.py",
    "src/kolmafa/devtest/native_relay.py",
    "src/kolmafa/devtest/inspection.py",
    "src/kolmafa/devtest/evidence.py",
    "src/kolmafa/devtest/capability_registry.py",
    "tests/devtest/test_native_query.py",
    "tests/devtest/test_native_relay.py",
    "tests/devtest/test_equipability_preflight.py",
    "tests/devtest/test_capability_registry.py",
    "tests/devtest/test_read_receipts.py",
)

failures: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("PASS " if condition else "FAIL ") + name)
    if not condition:
        failures.append(name)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def portable_checks(project: Path) -> dict:
    """Repository-only checks. Returns the parsed commissioning manifest."""
    manifest = load_json(project / "docs/commissioning/native-can-equip-t1-commissioning.json")
    check("manifest parses", True)
    check("manifest capability is native.can-equip",
          manifest.get("capability") == "native.can-equip")
    check("manifest authority is OBSERVATION_ONLY",
          manifest.get("authority") == "OBSERVATION_ONLY")
    check("manifest mutation scope is none", manifest.get("mutation_scope") == "none")

    # Canonical helper identity: exists and hashes to the manifest pin.
    canon = project / manifest["artifacts"]["canonical_helper"]["path"]
    check("canonical helper exists", canon.is_file())
    if canon.is_file():
        check(
            "canonical helper hash matches manifest",
            sha256(canon) == manifest["artifacts"]["canonical_helper"]["sha256"],
        )

    # Source registry carries the capability with observation-only authority.
    caps = {c["id"]: c for c in load_json(project / "data/capabilities/registry.json")["capabilities"]}
    entry = caps.get("native.can-equip", {})
    check("source registry has native.can-equip",
          entry.get("authority") == "OBSERVATION_ONLY")

    # Transport/authority coherence: fixed relay GET, caller controls nothing.
    transport = entry.get("transport", {})
    check(
        "transport is fixed-relay-get",
        transport.get("type") == "fixed-relay-get" and transport.get("method") == "GET",
    )
    check(
        "transport caller controls nothing",
        not any(
            transport.get(key, True)
            for key in (
                "caller_controls_code",
                "caller_controls_destination",
                "caller_controls_function",
            )
        ),
    )
    check("manifest transport agrees with registry",
          manifest.get("transport") == transport.get("type"))

    # Committed generated registry agrees with the source registry.
    gen_caps = {
        c["id"]: c
        for c in load_json(project / "agentflow/runtime/capabilities.json")["capabilities"]
    }
    check("committed generated registry agrees",
          gen_caps.get("native.can-equip") == entry)

    # Committed bootstrap agrees on identity/authority (never on readiness:
    # READY is a machine-local claim checked only by the local profile).
    boot = load_json(project / "agentflow/runtime/lead-bootstrap.json")
    native_boot = boot.get("native_capabilities", {}).get("native.can-equip", {})
    check("committed bootstrap lists native.can-equip", bool(native_boot))
    check("bootstrap authority agrees",
          native_boot.get("authority") == entry.get("authority"))

    # Implementation files and commissioning tests parse.
    for rel in IMPL_FILES:
        try:
            compile((project / rel).read_text(encoding="utf-8"), rel, "exec")
            check(f"parses {rel}", True)
        except (OSError, SyntaxError):
            check(f"parses {rel}", False)
    return manifest


def local_checks(project: Path, manifest: dict) -> None:
    """Machine-local installation checks (requires operator host state)."""
    canon = project / manifest["artifacts"]["canonical_helper"]["path"]
    inst = Path(manifest["artifacts"]["installed_helper"]["path"])
    check("installed helper exists", inst.is_file())
    if canon.is_file() and inst.is_file():
        check("installed helper hash matches canonical", sha256(canon) == sha256(inst))

    health = {
        p["id"]: p
        for p in load_json(project / "agentflow/runtime/provider-health.json")["providers"]
    }
    check("provider health READY", health.get("don-runtime", {}).get("status") == "READY")
    check("health lists capability",
          "native.can-equip" in health.get("don-runtime", {}).get("capabilities", []))

    boot = load_json(project / "agentflow/runtime/lead-bootstrap.json")
    native_boot = boot.get("native_capabilities", {}).get("native.can-equip", {})
    check("bootstrap advertises READY", native_boot.get("status") == "READY")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("portable", "local"), required=True)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    project = Path(args.project_root)

    manifest = portable_checks(project)
    if args.mode == "local":
        local_checks(project, manifest)

    label = "PORTABLE CHECKPOINT" if args.mode == "portable" else "LOCAL INSTALLATION CHECKPOINT"
    if failures:
        print(f"\n{label} INVALID: {len(failures)} failing check(s)")
        return 1
    print(f"\n{label} VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
