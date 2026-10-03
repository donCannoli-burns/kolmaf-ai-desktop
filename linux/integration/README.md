# Integration — provider/URI contract (LinkBus Slice 2)

Sideways integration beside the frozen Don authority chain. This directory
describes the seven already-installed plugins and compiles them into one
validated runtime registry. It never executes game actions.

## Layout

```text
integration/
├── README.md
├── schemas/
│   ├── provider-v1.schema.json
│   └── registry-v1.schema.json
├── providers/        # durable source manifests (config only, no observations)
│   ├── sandbox.json
│   ├── tokens.json
│   ├── memory.json
│   ├── skills.json
│   ├── ash-it-down.json
│   ├── goblin.json
│   └── matrix.json
└── linkbus/          # stdlib-only validator + compiler (no kolmafa imports)
    ├── __init__.py
    ├── validate.py
    └── compile_registry.py
```

Generated output (git-ignored, never edited by hand):

```text
data/runtime/linkbus/
├── registry.json
├── status.json
└── providers/<id>.json
```

## Frozen vocabularies

Authority: `NAVIGATION_ONLY REFERENCE_ONLY GUIDANCE_ONLY OBSERVATION_ONLY
TEST_ONLY LOCAL_DOCUMENT_WRITE GOVERNED_MUTATION STRUCTURAL_DENY`

Freshness: `STATIC VERSIONED SESSION LIVE DERIVED HISTORICAL`

Relationships: `DOCUMENTS PROVIDES IMPLEMENTS DEPENDS_ON REFERENCES
RELATED_TO TESTED_BY CAN_VERIFY CAN_RENDER GENERATED_FROM OBSERVED_FROM`

A `kolmaf://` URI is a logical registered identifier, not a path. Only
explicitly registered identities resolve; there is no generic filesystem,
URL, shell, gCLI, ASH-eval, or command resolver. Missing targets fail
loudly (`REGISTERED_BUT_TARGET_MISSING`) — never fall back to web search,
another provider, live KoLmafia, or sandbox-to-live execution.

## Commands (offline)

```bash
$HOME/anaconda3/bin/python -m pytest tests/test_linkbus_contract.py -q
$HOME/anaconda3/bin/python -m linkbus.compile_registry --project-root .
```

Run the compiler from the Don project root with `integration` on the
import path, or import `linkbus` from `integration/` in tests.

## Scope

Slice 2 only: manifests → validation → canonical identities → registry.
Matrix overlay, task system, Memory bridge, Ash-It-Down transport, and
OpenCode context tools are later slices. Do not modify the frozen Don
authority chain (`action_broker.py`, `confirmations.py`, `relay_writer.py`,
policy/bridge send boundary) or any installed plugin from here.
