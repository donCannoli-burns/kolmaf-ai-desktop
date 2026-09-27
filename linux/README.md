# Kolmaf-AI Desktop — Linux

This directory is the canonical Git home for the current Linux version of Kolmaf-AI Desktop.

## Current lineage

Active build lineage:

```text
Kolmaf-AI Don Edition
kolmaf-ai-v.0.0.1.-dev_test-linux
```

The latest supplied handoff describes the current runtime as:

```text
OpenCode
→ Maf-AI Dev-Test
→ DonRuntime
→ ActionBroker
→ ConfirmationStore
→ RelayWriter
→ KoLmafia relay
```

For approved live T2 actions the intended invariant is:

```text
live state
→ normalized proposal
→ exact state binding
→ durable confirmation
→ final live-state recheck
→ one RelayWriter transmission
→ read-only reconciliation
```

Latest archived verification supplied with the project:

```text
83 devtest passed
439 total passed
0 failures
```

This repository scaffold does not fabricate the working source from historical summaries. The working Linux tree should be imported here as the source of truth.

## Official dependencies

The Linux desktop requires these KoLmafia-side projects:

1. `donCannoli-burns/kol-goblin-docs`
2. `donCannoli-burns/kol-html-matrix`
3. `donCannoli-burns/kol-ash-it-down`

They are installed independently through KoLmafia Git and consumed through their installed `data/`, `relay/`, `scripts/`, session-evidence, and localhost service surfaces.

See:

- [DEPENDENCIES.md](DEPENDENCIES.md)
- [dependencies.json](dependencies.json)

## Repository boundary

Keep platform code here. Do not commit machine runtime state.

Recommended Linux layout as the working tree is imported:

```text
linux/
├── README.md
├── DEPENDENCIES.md
├── dependencies.json
├── src/
├── tests/
├── scripts/
├── docs/
├── launchers/
└── packaging/
```

The existing working implementation should determine the exact subtree names; do not rename functioning modules merely to match this sketch.

## Import safety

Before pushing the working Linux tree here, exclude at minimum:

```text
.env
.env.*
*.key
*.pem
*.sqlite
*.sqlite3
*.db
daily-hash*
sessions/
logs/
.pytest_cache/
__pycache__/
.venv/
venv/
dist/
build/
```

Preserve source, tests, documentation, fixtures that are safe/public, and reproducible configuration examples such as `.env.example`.
