# native.can-equip T1 — commissioning checkpoint

Status: `COMMISSIONED` (content frozen; commit blocked — see below).
Machine-readable manifest: `native-can-equip-t1-commissioning.json` (same directory).

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

## Fresh-agent discovery

1. Read `agentflow/runtime/lead-bootstrap.json` → `native_capabilities`.
2. Follow `capability_registry` → `capabilities.json` entry.
3. Check `provider-health.json` → `don-runtime` READY + helper paths exist.
4. Route equipability questions to `native.can-equip`; route equip
   imperatives to the T2 proposal flow and stop before execution.

## Drift detection

Run `scripts/verify-native-can-equip-checkpoint` (read-only). It fails on:
helper hash drift, missing projection, registry/bootstrap/health
disagreement, or unparsable test/manifest files.

## What remains prohibited

Generic ASH/CLI execution, new native functions without review, any
gameplay mutation from this path, and rewriting the historical PARTIAL.
