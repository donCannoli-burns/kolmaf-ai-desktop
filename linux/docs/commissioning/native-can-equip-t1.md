# native.can-equip T1 — commissioning checkpoint

Status: `COMMISSIONED` (content frozen; commit blocked — see below).
Machine-readable public attestation: `native-can-equip-t1-public.json` (same
directory). This is a sanitized, repository-only record: no local paths, no
secrets, no installed-runtime claims.

## What was built

A fixed, read-only native query path that answers "can the current character
equip this item?" without duplicating KoLmafia rules and without any mutation
authority:

```text
fresh-session discovery
  → bootstrap → registry → provider health → lazy routing
  → typed native.can-equip request
  → fixed GET transport → fixed relay helper
  → KoLmafia can_equip(item) → normalized result
  → durable T1 evidence receipt → independent verification
```

## Why

Transport-level success (`rc=0`) cannot distinguish parsing, local
eligibility gates, or execution. The marker-only path left one accepted
transmission unclassifiable. The native answer closes that gap for future
commands.

## Architecture

- `src/kolmafa/devtest/native_query.py` — static registry, typed
  request/result, fake/unavailable transports, normalization.
- `src/kolmafa/devtest/native_relay.py` — the single live GET transport plus
  verbatim helper installer and T1 receipt emission.
- `src/kolmafa/devtest/relay/don_native_can_equip.ash` — canonical helper
  source (one operation: validate `item_id` → `to_item` → `can_equip` →
  bounded JSON).
- `src/kolmafa/devtest/inspection.py` — preflight integration (fail-closed).
- `src/kolmafa/devtest/evidence.py` — journal with `event_id` per event.
- `src/kolmafa/devtest/capability_registry.py` — portable metadata, health
  rule, bootstrap rule, intent routing (observation vs T2).

## Authority boundary

- `native.can-equip` is `OBSERVATION_ONLY`, `mutation_scope: none`.
- A `true` result is evidence, never permission: proposals, confirmations,
  broker execution, and RelayWriter are untouched by this path.
- No generic ASH/CLI executor, no second mutation path, no rule duplication.

## Live transport

- Fixed GET `…/don_native_can_equip.ash?relay=true&item_id=<int>`.
- Caller controls only `item_id`; destination, path, method, and function
  are fixed. No POST, no `/sideCommand`.

## Receipt model

One live query → exactly one allowlisted receipt
(`capability`, `item_id`, `result`, `result_status`, `transport`) in
`logs/don-evidence.jsonl`. Transport/schema/journal failures are recorded
as `TRANSPORT_ERROR` / `SCHEMA_ERROR` / `WRITE_FAILED`; the GET is never
retried for logging reasons.

## Tests

Focused 69 · devtest 194 · full 609 · failures 0.

## Known limitations

- `can_equip == true` does not guarantee a future equip succeeds.
- The historical 2026-09-25 equip response was not retained; that attempt
  stays `PARTIAL` with unknown exact branch.
- Only `native.can-equip` is commissioned; no other ASH function is approved.
- Generated runtime files are byte-reproducible only with
  `PROJECT_ROOT=$HOME` (`environment.PROJECT_ROOT` is dynamic).

## Two evidence layers

The commissioning checkpoint is split into two independent layers. Neither
implies the other.

### Public source checkpoint (repository-only)

Proven from committed public repository content only: the public attestation
(`native-can-equip-t1-public.json`), the source capability registry, the
canonical helper identity and hash, transport/authority coherence, intent
routing, helper structural shape, implementation/test parseability, and
source-snapshot provenance. It never touches installed runtime state, the
installed relay helper, live provider health, relay reachability, or the
receipt journal, and it never claims installed-runtime READY.

Verifier: `scripts/verify-native-can-equip-checkpoint-portable` (read-only,
safe for public CI). Prints `PORTABLE CHECKPOINT VALID` on success.

### Local installation checkpoint (machine-local)

Everything in the public source checkpoint, plus machine-local installation
checks: the installed relay helper exists and hashes equal to the canonical
helper, the local runtime projection (capabilities/bootstrap/provider-health)
agrees with the source registry, and provider health is READY. This layer
requires operator host state and never runs in CI.

Verifier: `scripts/verify-native-can-equip-checkpoint-local` (read-only,
LOCAL_RUNTIME). The runtime projection location is explicit via
`--runtime-root` (or `KOLMAF_RUNTIME_ROOT`); no machine-local path is
hardcoded. Prints `LOCAL INSTALLATION CHECKPOINT VALID` on success.

## Fresh-agent discovery (local/private flow)

On the operator-host standalone checkout, a fresh agent discovers the
commissioned path from machine-local runtime state:

1. Read `agentflow/runtime/lead-bootstrap.json` → `native_capabilities`.
2. Follow `capability_registry` → `capabilities.json` entry.
3. Check `provider-health.json` → `don-runtime` READY + helper paths exist.
4. Route equipability questions to `native.can-equip`; route equip
   imperatives to the T2 proposal flow and stop before execution.

This flow is local-only. The public repository deliberately excludes
`agentflow/runtime/*`, `data/capabilities/registry.json`, and other
generated/private runtime state; the public source checkpoint proves the
commissioning without any of it.

## Drift detection

Two verifiers, one implementation
(`scripts/verify_native_can_equip_checkpoint.py`), two profiles:

- **Portable** (`--mode portable`) fails on helper/source/attestation drift:
  public attestation missing or altered, canonical helper missing or
  hash-drifted, capability ID/authority/transport/caller-controls altered in
  the source registry, source-snapshot provenance disagreement, helper
  structural-shape violation, or unparsable implementation/test files.
- **Local** (`--mode local`) fails on all portable drift plus
  installed-helper/runtime-projection/provider-health/readiness drift:
  installed helper missing or hash-drifted, runtime projection
  disagreement, provider health not READY, or local bootstrap not READY.

Both are read-only. Neither performs network I/O, proposals, or gameplay.

## What remains prohibited

Generic ASH/CLI execution, new native functions without review, any
gameplay mutation from this path, and rewriting the historical PARTIAL.
