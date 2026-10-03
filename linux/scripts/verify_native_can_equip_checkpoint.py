#!/usr/bin/env python3
"""Shared verifier for the commissioned native.can-equip checkpoint.

Two profiles, one implementation:

- ``--mode portable``: repository-only. Proves the public commissioning
  attestation, the source capability registry, the canonical helper identity
  and hash, transport/authority coherence, intent routing, helper structural
  shape, implementation/test parseability, and source-snapshot provenance.
  Never touches machine-local runtime state, the installed relay helper,
  live provider health, relay reachability, or the receipt journal.
  Success line: ``PORTABLE CHECKPOINT VALID``.

- ``--mode local``: everything in portable, plus machine-local installation
  checks: the installed relay helper exists and hashes equal to canonical,
  the local runtime projection (capabilities/bootstrap/provider-health)
  agrees with the source registry, and provider health is READY. Requires
  operator host state; never runs in CI.
  Success line: ``LOCAL INSTALLATION CHECKPOINT VALID``.

Read-only in both modes. No network I/O, no proposals, no gameplay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ATTESTATION_PATH = "docs/commissioning/native-can-equip-t1-public.json"
PROVENANCE_PATH = "IMPORT_PROVENANCE.md"
HELPER_PATH = "src/kolmafa/devtest/relay/don_native_can_equip.ash"

ATTESTATION_SCHEMA = "kolmaf-public-commissioning-attestation/v1"
EXPECTED_CAPABILITY = "native.can-equip"
EXPECTED_AUTHORITY = "OBSERVATION_ONLY"
EXPECTED_NATIVE_OWNER = "KoLmafia"
EXPECTED_ADAPTER_OWNER = "Don"
EXPECTED_PROVIDER = "don-runtime"
EXPECTED_ACTIVATION = "lazy"
EXPECTED_FRESHNESS = "LIVE"
EXPECTED_TRANSPORT_TYPE = "fixed-relay-get"
EXPECTED_TRANSPORT_METHOD = "GET"
EXPECTED_HELPER_SHA256 = "666c8abd92935cabd7d9099b45e2d92814e9dced0e2540ee6d97614d77648944"
EXPECTED_SOURCE_COMMIT = "a0299b8fbd5f41aaf8a2e1c09da47b109ba6c744"

# Synthetic placeholder for the machine-local installed helper path. Portable
# mode proves the canonical helper only; the installed path is a local claim.
LOCAL_RUNTIME_PLACEHOLDER = "<LOCAL_RUNTIME_ONLY>"

CALLER_CONTROL_KEYS = (
    "caller_controls_code",
    "caller_controls_destination",
    "caller_controls_function",
)

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

# Helper structural shape: the canonical helper must be a fixed read-only
# observation. These tokens must never appear in the helper source.
HELPER_FORBIDDEN_TOKENS = (
    "cli_execute",
    "visit_url",
    "sideCommand",
    "kmail",
    "send_chat",
)
HELPER_FORBIDDEN_VERBS = (
    "use",
    "take",
    "put",
    "discard",
    "consume",
    "unequip",
    "wear",
    "remove",
)

failures: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("PASS " if condition else "FAIL ") + name)
    if not condition:
        failures.append(name)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _import_capability_registry(project: Path) -> Any:
    """Import the project's own capability_registry module.

    The project ``src`` tree is placed at the front of ``sys.path`` and any
    previously imported ``kolmafa`` modules are dropped so the verifier always
    evaluates the repository under test, never an installed copy.
    """
    src = project / "src"
    if not src.is_dir():
        raise FileNotFoundError(f"missing source tree: {src}")
    for module in list(sys.modules):
        if module == "kolmafa" or module.startswith("kolmafa."):
            del sys.modules[module]
    sys.path.insert(0, str(src))
    import kolmafa.devtest.capability_registry as registry

    return registry


def _caller_controls_nothing(transport: dict) -> bool:
    return not any(transport.get(key, True) for key in CALLER_CONTROL_KEYS)


def _semantic_entry(entry: dict) -> dict:
    """Project a registry entry to its semantic (non-path) fields.

    ``helper_canonical`` and ``helper_installed`` are path representations that
    differ by design between the repository-relative constructed entry and the
    machine-local runtime projection, so they are excluded from agreement.
    """
    return {key: value for key, value in entry.items() if key not in ("helper_canonical", "helper_installed")}


def portable_checks(project: Path) -> dict[str, Any]:
    """Repository-only checks. Returns attestation + constructed registry entry."""
    try:
        attestation = load_json(project / ATTESTATION_PATH)
        check("attestation parses", True)
    except (OSError, json.JSONDecodeError) as error:
        check("attestation parses", False)
        print(f"     load error: {error}")
        attestation = {}
    check("attestation schema", attestation.get("schema") == ATTESTATION_SCHEMA)
    check(
        "attestation capability is native.can-equip",
        attestation.get("capability") == EXPECTED_CAPABILITY,
    )
    check(
        "attestation commissioning_status is COMMISSIONED",
        attestation.get("commissioning_status") == "COMMISSIONED",
    )
    check(
        "attestation authority is OBSERVATION_ONLY",
        attestation.get("authority") == EXPECTED_AUTHORITY,
    )
    check(
        "attestation mutation_scope is none",
        attestation.get("mutation_scope") == "none",
    )
    check(
        "attestation native_owner is KoLmafia",
        attestation.get("native_owner") == EXPECTED_NATIVE_OWNER,
    )
    check(
        "attestation adapter_owner is Don",
        attestation.get("adapter_owner") == EXPECTED_ADAPTER_OWNER,
    )

    att_transport = attestation.get("transport", {})
    check(
        "attestation transport is fixed-relay-get",
        att_transport.get("type") == EXPECTED_TRANSPORT_TYPE,
    )
    check(
        "attestation transport method is GET",
        att_transport.get("method") == EXPECTED_TRANSPORT_METHOD,
    )
    check(
        "attestation transport caller controls nothing",
        _caller_controls_nothing(att_transport),
    )

    att_helper = attestation.get("canonical_helper", {})
    check(
        "attestation helper path is repository-relative",
        att_helper.get("path") == HELPER_PATH,
    )
    check(
        "attestation helper sha256 is the historical pin",
        att_helper.get("sha256") == EXPECTED_HELPER_SHA256,
    )

    att_scope = attestation.get("scope", {})
    check("attestation scope is repository_only", att_scope.get("repository_only") is True)
    check(
        "attestation scope disclaims installed runtime",
        att_scope.get("installed_runtime_verified") is False,
    )
    check(
        "attestation scope disclaims provider ready",
        att_scope.get("provider_ready_verified") is False,
    )
    check(
        "attestation scope disclaims live freshness",
        att_scope.get("live_freshness_verified") is False,
    )

    # Source registry carries the capability with observation-only authority.
    try:
        registry = _import_capability_registry(project)
        check("source registry imports", True)
    except Exception as error:  # noqa: BLE001 - report any import failure
        check("source registry imports", False)
        print(f"     import error: {error}")
        registry = None

    if registry is not None:
        check(
            "registry NATIVE_CAN_EQUIP_ID",
            getattr(registry, "NATIVE_CAN_EQUIP_ID", None) == EXPECTED_CAPABILITY,
        )
        check(
            "registry OBSERVATION_AUTHORITY",
            getattr(registry, "OBSERVATION_AUTHORITY", None) == EXPECTED_AUTHORITY,
        )
        check(
            "registry NATIVE_OWNER",
            getattr(registry, "NATIVE_OWNER", None) == EXPECTED_NATIVE_OWNER,
        )
        check(
            "registry ADAPTER_OWNER",
            getattr(registry, "ADAPTER_OWNER", None) == EXPECTED_ADAPTER_OWNER,
        )

        question = registry.route_intent("Can I equip this?")
        check("route equipability question to native.can-equip", question["route"] == EXPECTED_CAPABILITY)
        check(
            "route equipability authority OBSERVATION_ONLY",
            question["authority"] == EXPECTED_AUTHORITY,
        )
        imperative = registry.route_intent("Equip this")
        check("route equip imperative to don.propose-action", imperative["route"] == "don.propose-action")
        check("route equip imperative authority T2", imperative["authority"] == "T2")

        entry = {}
        helper_sha = att_helper.get("sha256")
        if helper_sha:
            try:
                entry = registry.build_registry_entry(
                    helper_sha256=helper_sha,
                    helper_canonical=att_helper.get("path"),
                    helper_installed=LOCAL_RUNTIME_PLACEHOLDER,
                )
            except Exception as error:  # noqa: BLE001 - report any build failure
                check("constructed entry builds", False)
                print(f"     build error: {error}")
                entry = {}
        if entry:
            check("constructed entry id", entry["id"] == EXPECTED_CAPABILITY)
            check("constructed entry authority", entry["authority"] == EXPECTED_AUTHORITY)
            check("constructed entry native_owner", entry["native_owner"] == EXPECTED_NATIVE_OWNER)
            check("constructed entry adapter_owner", entry["adapter_owner"] == EXPECTED_ADAPTER_OWNER)
            check("constructed entry provider", entry["provider"] == EXPECTED_PROVIDER)
            check("constructed entry activation", entry["activation"] == EXPECTED_ACTIVATION)
            check("constructed entry freshness", entry["freshness"] == EXPECTED_FRESHNESS)
            check(
                "constructed entry transport type",
                entry["transport"]["type"] == EXPECTED_TRANSPORT_TYPE,
            )
            check(
                "constructed entry transport method",
                entry["transport"]["method"] == EXPECTED_TRANSPORT_METHOD,
            )
            check(
                "constructed entry caller controls nothing",
                _caller_controls_nothing(entry["transport"]),
            )
            check(
                "constructed entry installed path is placeholder",
                entry["helper_installed"] == LOCAL_RUNTIME_PLACEHOLDER,
            )
    else:
        entry = {}

    # Canonical helper identity: exists and hashes to the attestation pin.
    canon = project / HELPER_PATH
    check("canonical helper exists", canon.is_file())
    helper_hash = sha256(canon) if canon.is_file() else None
    if canon.is_file():
        check("canonical helper hash matches attestation", helper_hash == att_helper.get("sha256"))

    # Helper structural shape: fixed read-only observation only.
    if canon.is_file():
        text = canon.read_text(encoding="utf-8")
        check("helper contains can_equip(", "can_equip(" in text)
        form_fields = re.findall(r'form_field\("([^"]+)"\)', text)
        check("helper reads only item_id form field", form_fields == ["item_id"])
        for token in HELPER_FORBIDDEN_TOKENS:
            check(f"helper has no {token}", token not in text)
        for verb in HELPER_FORBIDDEN_VERBS:
            check(
                f"helper has no {verb} mutation",
                not re.search(rf"\b{verb}\s*\(", text),
            )

    # Implementation files and commissioning tests parse.
    for rel in IMPL_FILES:
        try:
            compile((project / rel).read_text(encoding="utf-8"), rel, "exec")
            check(f"parses {rel}", True)
        except (OSError, SyntaxError):
            check(f"parses {rel}", False)

    # Source snapshot provenance: attestation commit == IMPORT_PROVENANCE commit.
    provenance = (project / PROVENANCE_PATH).read_text(encoding="utf-8")
    match = re.search(r"Commit:\s*([0-9a-f]{40})", provenance)
    check("provenance records a commit", bool(match))
    att_source_commit = attestation.get("source_snapshot", {}).get("local_source_commit")
    check(
        "attestation source commit present",
        att_source_commit == EXPECTED_SOURCE_COMMIT,
    )
    if match:
        check("attestation source commit matches provenance", att_source_commit == match.group(1))

    # Attestation vs source implementation: two independent repository
    # representations must agree on identity, authority, ownership, transport.
    if registry is not None:
        check(
            "attestation capability == registry id",
            attestation.get("capability") == getattr(registry, "NATIVE_CAN_EQUIP_ID", None),
        )
        check(
            "attestation authority == registry authority",
            attestation.get("authority") == getattr(registry, "OBSERVATION_AUTHORITY", None),
        )
        check(
            "attestation native_owner == registry native_owner",
            attestation.get("native_owner") == getattr(registry, "NATIVE_OWNER", None),
        )
        check(
            "attestation adapter_owner == registry adapter_owner",
            attestation.get("adapter_owner") == getattr(registry, "ADAPTER_OWNER", None),
        )
        if entry:
            check(
                "attestation transport == constructed transport",
                att_transport == entry["transport"],
            )
    if helper_hash is not None:
        check(
            "attestation helper sha == actual helper sha",
            att_helper.get("sha256") == helper_hash,
        )

    return {"attestation": attestation, "entry": entry}


def local_checks(project: Path, context: dict[str, Any], runtime_root: Path) -> None:
    """Machine-local installation checks (requires operator host state)."""
    attestation = context["attestation"]
    entry = context["entry"]
    att_helper = attestation.get("canonical_helper", {})

    from kolmafa.config import get_settings
    from kolmafa.devtest.native_relay import HELPER_FILENAME

    settings = get_settings()
    installed = settings.kolmafia_home / "relay" / HELPER_FILENAME
    canon = project / HELPER_PATH
    check("installed helper exists", installed.is_file())
    if canon.is_file() and installed.is_file():
        check("installed helper hash matches canonical", sha256(canon) == sha256(installed))

    def load_runtime(name: str) -> dict:
        try:
            return load_json(runtime_root / name)
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            check(f"runtime projection {name} parses", False)
            print(f"     load error: {error}")
            return {}

    # Local runtime projection agrees with the source registry. The path fields
    # (helper_canonical/helper_installed) are machine-local by nature, so
    # agreement is checked on the semantic fields only.
    caps = {c["id"]: c for c in load_runtime("capabilities.json").get("capabilities", [])}
    check("runtime projection registry has native.can-equip", EXPECTED_CAPABILITY in caps)
    if entry:
        projected = _semantic_entry(caps.get(EXPECTED_CAPABILITY, {}))
        check("runtime projection registry agrees", projected == _semantic_entry(entry))

    boot = load_runtime("lead-bootstrap.json")
    native_boot = boot.get("native_capabilities", {}).get(EXPECTED_CAPABILITY, {})
    check("runtime bootstrap lists native.can-equip", bool(native_boot))
    check("runtime bootstrap authority agrees", native_boot.get("authority") == EXPECTED_AUTHORITY)
    check("runtime bootstrap advertises READY", native_boot.get("status") == "READY")

    health = {p["id"]: p for p in load_runtime("provider-health.json").get("providers", [])}
    check("provider health READY", health.get(EXPECTED_PROVIDER, {}).get("status") == "READY")
    check(
        "health lists capability",
        EXPECTED_CAPABILITY in health.get(EXPECTED_PROVIDER, {}).get("capabilities", []),
    )


def resolve_runtime_root(project: Path, explicit: str | None) -> Path:
    """Locate the machine-local runtime projection directory.

    Explicit ``--runtime-root`` wins, then ``KOLMAF_RUNTIME_ROOT``, then the
    historical private layout ``<project>/agentflow/runtime`` (present only in
    the operator-host standalone checkout, never in the public repository).
    """
    if explicit:
        return Path(explicit)
    env = os.environ.get("KOLMAF_RUNTIME_ROOT")
    if env:
        return Path(env)
    return project / "agentflow" / "runtime"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("portable", "local"), required=True)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument(
        "--runtime-root",
        default=None,
        help="machine-local runtime projection directory (local mode only)",
    )
    args = parser.parse_args(argv)
    project = Path(args.project_root)

    context = portable_checks(project)
    if args.mode == "local":
        local_checks(project, context, resolve_runtime_root(project, args.runtime_root))

    label = "PORTABLE CHECKPOINT" if args.mode == "portable" else "LOCAL INSTALLATION CHECKPOINT"
    if failures:
        print(f"\n{label} INVALID: {len(failures)} failing check(s)")
        return 1
    print(f"\n{label} VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
