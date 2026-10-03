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

## KoLmafia companion tools

The broader public Kolmaf-AI companion constellation contains **9 projects**; see the canonical numbered/hyperlinked registry in [`../README.md#tool-constellation`](../README.md#tool-constellation). This Linux integration layer currently works directly with **4 reviewed runtime-facing surfaces**:

1. `donCannoli-burns/kol-goblin-docs`
2. `donCannoli-burns/kol-html-matrix`
3. `donCannoli-burns/kol-ash-it-down`
4. `donCannoli-burns/actor-engine`

They are maintained separately and consumed through their installed `data/`, `relay/`, `scripts/`, session-evidence, and localhost service surfaces.

See:

- [TOOLS.md](TOOLS.md)
- [tools.json](tools.json)

## Repository boundary

Keep platform code here. Do not commit machine runtime state.

Recommended Linux layout as the working tree is imported:

```text
linux/
├── README.md
├── TOOLS.md
├── tools.json
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

---

## Imported runtime documentation

# Kolmaf-AI

> **Current functional implementation:** `kolmafa` 0.1.0 in this directory.
> Canonical workspace: `$HOME/repos/build-dev/build-dev-ai-kol/kolmaf-AI/kolmaf-ai`.
> SpringBridge is obsolete. Current read-only operator path is docker-free session-log observation; live relay/GCLI writes remain fail-closed.

Lean Python CLI/REPL implementation for safe KoLmafia diagnostics, local context search,
session observation, reviewed relay-action proposals, and fail-closed gated relay sends.

V1 intentionally stays inside the Python `kolmafa` process boundary. First-class OpenCode
plugin/action integration is deferred until the local API surface is validated, and no Node
sidecar or OpenCode plugin files are required for this slice.

## Milestone boundary

- Architecture milestone: `docs/PRD.yaml` and `docs/architecture/kolmaf-ai-opencode-power-app/`
  define the OpenCode power-app concept and no-runtime boundary.
- Safe v1 implementation milestone: this package implements the Python CLI/REPL boundary,
  SQLite schema, policy decisions, durable confirmations, redaction, session observation, and
  relay send gate.
- Do not infer an implemented OpenCode plugin/action, Node sidecar, ChromaDB service,
  browser dashboard, KoLmafia alias UX, or Q-table runtime from the architecture package.
- PRD milestone notes must be approved by the orchestrator before editing `docs/PRD.yaml`.

## Goals

- Provide safe CLI/REPL diagnostics and proposal workflows for an operator.
- Observe explicit `KOLMAFA_USER:` lines from `sessions/<player_name>.txt` without importing
  private logs into RAG.
- Keep local game/context data in SQLite.
- Support RAG with SQLite FTS5 now and `sqlite-vec` when installed.
- Run against an existing KoLmafia home/session directory without requiring Docker.
- Copy/import reference data into this project when needed; do not depend on external paths at runtime.
- Keep deep-thinking mode no-action by default; game-affecting live execution requires policy,
  allowlist, redaction, audit, and durable human confirmation.

## Current scaffold

```text
kolmaf-ai/
|-- docker-compose.yml        # KoLmafia web container + optional sqlite-web
|-- pyproject.toml            # Python 3.13 project config
|-- data/reference/           # copied seed docs/reference snippets
|-- sql/schema.sql            # SQLite tables, FTS5, optional vec notes
|-- src/kolmafa/
|   |-- cli.py                # CLI/REPL entry point and safe operator loop
|   |-- config.py             # env/file settings
|   |-- db.py                 # SQLite helpers
|   |-- policy.py             # static allowlist, action classes, fail-closed decisions
|   |-- confirmations.py      # durable one-shot confirmation lifecycle
|   |-- redaction.py          # secret redaction helpers
|   |-- bridge.py             # relay transport, command audit, session observation
|   `-- rag.py                # explicit document ingest/search
`-- tests/
```

## Quick start

```bash
cd $HOME/repos/build-dev/build-dev-ai-kol/kolmaf-AI/kolmaf-ai
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
kolmafa init-db
kolmafa search "relay nobrowser"
kolmafa repl --once "search relay"
kolmafa propose status
kolmafa propose adventure
kolmafa dry-run status
```

`kolmafa search` and REPL search are advisory only. If no corpus has been explicitly ingested,
they return a safe no-results fallback instead of attempting any game action.

Docker is not required for the docker-free bridge path. Point Kolmafa at an existing KoLmafia
home directory and session log, then run read-only diagnostics:

For the common local setup, use the repo-local convenience wrapper. It defaults to
`KOLMAFA_TRANSPORT=docker-free`, `KOLMAFA_KOLMAFIA_HOME=$HOME/.kolmafia`,
and `KOLMAFA_PLAYER_NAME=test_player`, and it adds the default player for `observe`,
`listen`, `respond`, and `loop` when no player argument is supplied:

```bash
scripts/kolmafa-df doctor
scripts/kolmafa-df observe
scripts/kolmafa-df respond
scripts/kolmafa-df loop --once
scripts/kolmafa-df respond otherplayer
```

Existing environment variables still override the wrapper defaults:

```bash
KOLMAFA_KOLMAFIA_HOME=/path/to/kolmafia KOLMAFA_PLAYER_NAME=playername scripts/kolmafa-df observe
```

The wrapper calls `python3 -m kolmafa.cli`; it does not call Docker, live relay `sideCommand`,
OS automation, or a second Java process. `respond` and `loop` remain proposal-only with live write-back
deferred.

```bash
export KOLMAFA_TRANSPORT=docker-free
export KOLMAFA_KOLMAFIA_HOME=/path/to/kolmafia
export KOLMAFA_PLAYER_NAME=playername
kolmafa doctor
kolmafa observe playername
kolmafa respond playername
kolmafa loop playername --once
```

`KOLMAFA_KOLMAFIA_HOME` must be the KoLmafia root that contains `sessions/`.
`KOLMAFA_PLAYER_NAME` maps to `sessions/<player_name>.txt` and accepts only
`A-Z`, `a-z`, `0-9`, `_`, and `-`. `doctor` never creates live paths; it reports
`docker_free_ready` plus missing-path reasons.

## Safe operator loop

The v1 operator surface is the Python CLI/REPL fallback:

```bash
kolmafa doctor
kolmafa observe playername
kolmafa listen playername
kolmafa respond playername
kolmafa loop playername --once
kolmafa loop playername --max-events 1 --poll-interval 0.25
kolmafa tail --once playername
kolmafa dry-run status
kolmafa repl
kolmafa repl --once "respond playername"
kolmafa repl --mode deep-thinking --once "search relay"
kolmafa repl --mode deep-thinking --once "send adventure"
```

Supported REPL commands are `doctor`, `search <query>`, `observe <player>`,
`listen <player>`, `respond <player>`, `loop <player>`, `propose <relay-command>`,
`dry-run <relay-command>`, `help`, and `exit`.
Deep-thinking mode is no-action by default; attempted `send` commands are refused and marked
`not executed`.

Safe v1 rules:

- `doctor` prints local diagnostics only and reports whether relay pwd is configured as a boolean.
- `search` uses local SQLite FTS5 documents only; no corpus means no-results and `not executed`.
- `observe` reads `KOLMAFA_USER:` lines from the active KoLmafia session log and redacts messages.
- `listen` is a docker-free alias for `observe`; `tail --once` prints only redacted prefixed events,
  never raw session-log lines.
- `respond` observes newly appended `KOLMAFA_USER:` events and prints deterministic dry-run response
  proposals only.
- `loop` continuously watches newly appended `KOLMAFA_USER:` events and prints one deterministic
  dry-run response proposal per accepted event. Use `--once`, `--max-events`, and small
  `--poll-interval` values for finite smoke tests.
- `propose` evaluates policy and prints a redacted no-action proposal; it never calls relay transport.
- `dry-run` uses the policy-bound writer and audit path, but never contacts live transports.
- REPL `send` is not a shortcut; deep-thinking mode refuses live send attempts.
- CLI `send` currently routes through the policy-bound dry-run writer for `relay` and `docker-free`
  transports; it does not perform live relay or GCLI writes in this plan.

### Dry-run response proposal

`respond` and `loop` are proposal-only commands for the current safe response-loop MVP:

```bash
kolmafa respond PLAYER_NAME
kolmafa loop PLAYER_NAME --once
kolmafa loop PLAYER_NAME --max-events 1 --poll-interval 0.25
kolmafa repl --once "respond PLAYER_NAME"
```

`scripts/kolmafa-df loop --once` uses docker-free defaults and defaults the player to
`test_player` unless `KOLMAFA_PLAYER_NAME` or an explicit player argument is supplied.

**Warning:** `loop` is dry-run/proposal-only. It never writes back into KoLmafia, never calls
relay `sideCommand`, never starts Docker or a second Java process, and never performs OS
automation. It only observes accepted `KOLMAFA_USER:` session-log events through the durable
cursor and prints deferred response proposals to the console.

Output uses fixed labels:

```text
response_event_id: <event-id>
response_proposal: KOLMAFA: hello, I am online
response_status: proposed; write-back deferred; not executed
```

If no new event is available, output is:

```text
response_status: no_new_events; write-back deferred; not executed
```

Exit codes:

- `0`: proposal printed or no new events.
- `1`: runtime or configuration failure; diagnostics are redacted.
- `2`: CLI usage error, such as missing `PLAYER_NAME`.

Response proposal safety:

- Proposal text is fixed to `KOLMAFA: hello, I am online`.
- Player/session message bodies are untrusted input and are not echoed in the proposal.
- Session input is redacted before display or SQLite persistence.
- First observation initializes at EOF, so historical private session text is not replayed.
- Proposals are console-only and are not stored in a response/proposal table.
- No live write-back is available from `respond`, `loop`, or `repl --once "respond PLAYER_NAME"`.
- The command does not call relay `sideCommand`, GCLI writers, subprocess writers, Docker, or OS automation.

Session listener trust model:

- Only `KOLMAFA_USER:` is treated as the routing prefix for player-originated bridge events.
- Session-log content after the prefix is untrusted input and is redacted before display or SQLite persistence.
- Initial `observe` records cursor state at EOF and returns no events, avoiding historical private-log import.
- Follow-up `observe` or `listen` reads appended bytes only, using file identity and byte offsets before dedupe.
- Oversized, empty, malformed, self-output, and unprefixed lines are ignored.
- Do not paste, persist, commit, summarize, or ingest raw private session-log lines.

Manual smoke checks do not require live credentials:

```bash
KOLMAFA_DB=/tmp/kolmafa-smoke.db kolmafa init-db
KOLMAFA_DB=/tmp/kolmafa-smoke.db kolmafa doctor
KOLMAFA_DB=/tmp/kolmafa-smoke.db kolmafa repl --once "search relay"
KOLMAFA_DB=/tmp/kolmafa-smoke.db kolmafa propose adventure
```

Manual response-loop checks should use a temporary KoLmafia home fixture before any explicit live-session
manual step:

```bash
tmp_home=$(mktemp -d)
mkdir -p "$tmp_home/sessions"
: > "$tmp_home/sessions/player.txt"
KOLMAFA_DB="$tmp_home/kolmafa.db" KOLMAFA_KOLMAFIA_HOME="$tmp_home" kolmafa respond player
printf '%s\n' 'KOLMAFA_USER: fixture body' >> "$tmp_home/sessions/player.txt"
KOLMAFA_DB="$tmp_home/kolmafa.db" KOLMAFA_KOLMAFIA_HOME="$tmp_home" kolmafa respond player
KOLMAFA_DB="$tmp_home/kolmafa.db" KOLMAFA_KOLMAFIA_HOME="$tmp_home" kolmafa repl --once "respond player"
```

Expected fixture behavior:

- First `respond` prints only `response_status: no_new_events; write-back deferred; not executed`.
- Second `respond` prints `response_event_id`, `response_proposal`, and `response_status`.
- `response_proposal` is exactly `KOLMAFA: hello, I am online`.
- The fixture user body is not echoed in the proposal.
- A third run without appended input prints no new event and no proposal.
- Live private sessions are optional explicit manual checks only; never paste raw private session text into docs or logs.

## Bridge modes and send gate

Implemented docker-free dry-run path:

```text
operator CLI command
  -> canonical relay command check
  -> static policy allowlist decision
  -> redacted policy and command audit rows
  -> durable one-shot confirmation when required
  -> non-mutating GCLI dry-run writer
  -> redacted command result persisted for review
```

This path avoids the file-lock problem because it never starts a second KoLmafia process.
In this docker-free slice, live execution remains deferred: unknown commands deny by default,
game-affecting dry-runs require durable confirmation, and deep-thinking workflows do not
execute live game actions.

The docker-free path is session/dry-run only:

- Session observation reads the configured KoLmafia `sessions/<player_name>.txt` file.
- Dry-run writer results use the `gcli-dry-run` transport and say `not executed`.
- `KOLMAFA_TRANSPORT=docker-free` suppresses Docker readiness checks in `doctor`.
- Live play must not launch a second KoLmafia Java process.
- The Docker GCLI wrapper is offline-only and blocked from the live operator path.
- OpenCode SDK JS remains optional/future; it is not required for this bridge path.

Set docker-free path configuration in the environment:

```bash
export KOLMAFA_TRANSPORT=docker-free
export KOLMAFA_KOLMAFIA_HOME=/path/to/kolmafia
export KOLMAFA_PLAYER_NAME=playername
```

Then:

```bash
kolmafa doctor
kolmafa propose status
kolmafa observe playername
kolmafa listen playername
kolmafa dry-run status
```

Do not configure `KOLMAFA_CLI_COMMAND` to a wrapper that starts KoLmafia for live play. Known
Docker CLI fallback wrappers are refused because they can launch a second Java process.

GCLI writer gating model:

- `dry-run` and docker-free `send` use the same policy, redaction, audit, and confirmation path.
- The final writer boundary is non-mutating: no typing, clicking, Docker, Java launch, relay contact, or game mutation.
- Read-only allowlisted commands such as `status` can return successful dry-run results.
- Game-affecting commands such as `adventure` require a matching, unexpired, one-shot confirmation even in dry-run.
- Noncanonical, unknown, social, and secret-bearing commands fail closed and store redacted audit output.
- Operators must not bypass the gate with alternate wrappers, raw relay calls, shell injection, or manual audit edits.

### Relay password not needed for docker-free dry-run

The implemented docker-free bridge does not require `KOLMAFA_RELAY_PWD`. Do not capture relay
password fields, cookies, browser storage, or SDK credentials for this path. Test with no-action
diagnostics/proposals instead:

```bash
kolmafa doctor
kolmafa propose status
```

Live relay/GCLI writing is deferred in this plan. Do not use `KOLMAFA_RELAY_PWD` to enable live
execution unless a future approved replan implements and reviews the live branch.

Live branch deferral prerequisites and stop conditions:

- Required proof: a safe write mechanism into an already-running KoLmafia instance, with no second Java process.
- Required approval: explicit PRD/change-request approval for live game execution beyond evaluation/dry-run scope.
- Required gates: policy allowlist, redaction, command audit, durable one-shot confirmation, and reviewed tests.
- Stop if any mechanism launches KoLmafia, captures credentials, persists raw session data, or bypasses the gate.
- Stop if Docker, relay password, OpenCode SDK JS, or OS automation becomes mandatory for the docker-free path.
- Stop if command/session output cannot be redacted before display, audit persistence, or RAG reuse.

Secret handling:

- Never paste relay password values, cookies, tokens, API keys, OpenCode credentials, or SDK auth data.
- Redaction replaces known secret-bearing values before display, audit persistence, or RAG reuse.
- Command-audit schema rejects common unredacted secret-like patterns.
- Use boolean readiness output, not raw values, when reporting setup state.

### Docker GCLI fallback wrapper

This is now treated as **offline-only**. It starts a second KoLmafia Java process, so it will conflict with a live web/relay KoLmafia character session and may print `Could not acquire file lock`.

Do not use it while `kolmafia-web` is logged into your character. The supported v1 boundary is the
Python CLI/REPL fallback; live relay/jsonApi automation stays behind the send gate.

`scripts/kolmafia-gcli-docker.sh` is an offline fallback wrapper. It:

1. reads raw command text from stdin,
2. writes a temporary `.cli` batch file inside the running Docker container,
3. runs `java -DuseCWDasROOT -Djava.awt.headless=true -jar /etc/kolmafia/kolmafia.jar --CLI <batch>` in the `kolmafia-web` container,
4. deletes the temporary batch file on exit.

If KoLmafia is fully stopped and you intentionally want to inspect this fallback, do it outside
the v1 live operator loop and do not use it as a live character transport. `kolmafa send` still
fails closed by default, including with `--offline-ok`, until a reviewed offline workflow exists.

```bash
kolmafa send --offline-ok 'version'  # expected v1 result: refused closed
```

Do not run `kolmafa` with `sudo`; sudo uses a different PATH/environment and usually cannot see your editable Python install. If the command is not found, install from the project root with `python3 -m pip install -e .` or use `PYTHONPATH=src python3 -m kolmafa.cli ...`.

If your container name or jar path differs:

```bash
export KOLMAFA_DOCKER_CONTAINER=kolmafia-web
export KOLMAFA_CONTAINER_JAR=/etc/kolmafia/kolmafia.jar
```

## Airflow / DAG note

Apache Airflow is free/open source, but it is heavy for the first pass. This scaffold keeps database/RAG jobs as plain Python CLI commands first. Add Airflow later only as an orchestration layer around these commands, not as core logic.

## Deferred and future surfaces

These are not implemented safe v1 runtime surfaces:

| Surface | Safe v1 status |
| --- | --- |
| OpenCode command/action or plugin | Deferred until local installed API/type validation succeeds. |
| Node/OpenCode SDK sidecar | Future-only; cannot own SQLite state or bypass policy. |
| ChromaDB | Future-only; SQLite FTS5 is the current retrieval path. |
| Browser dashboard/custom image | Future-only and outside the safe v1 operator loop. |
| KoLmafia alias UX | Deferred until argument handling and safety gates are reviewed. |
| Q-table runtime learning | Future-only; advisory data cannot grant permissions. |
| Offline Docker GCLI fallback as live transport | Prohibited for live play because it starts a second Java process. |

## Verification matrix

Run from `$HOME/repos/build-dev/build-dev-ai-kol/kolmaf-AI/kolmaf-ai`:

| Area | Command | Expected safe v1 result |
| --- | --- | --- |
| Python tests | `python3 -m pytest tests -q` | CLI, bridge, schema, policy, RAG, and confirmation tests pass. |
| Python syntax | `python3 -m py_compile src/kolmafa/*.py` | Runtime modules compile. |
| Shell syntax | `bash -n scripts/kolmafia-gcli-docker.sh` | Offline wrapper syntax is valid. |
| Compose syntax | `docker compose config` | Compose file renders; separately verify bind-mounted paths. |
| Local DB smoke | `KOLMAFA_DB=/tmp/kolmafa-smoke.db kolmafa init-db` | SQLite schema initializes. |
| Read-only diagnostics | `KOLMAFA_DB=/tmp/kolmafa-smoke.db kolmafa doctor` | Prints paths and booleans; no game action. |
| No-corpus search | `KOLMAFA_DB=/tmp/kolmafa-smoke.db kolmafa repl --once "search relay"` | Prints no-results and `not executed`. |
| Proposal check | `KOLMAFA_DB=/tmp/kolmafa-smoke.db kolmafa propose adventure` | Shows confirmation required; does not execute. |
| Response proposal | Temp `KOLMAFA_KOLMAFIA_HOME` fixture plus `kolmafa respond player` | Prints labels and fixed proposal only; no write-back. |
| REPL response proposal | Temp `KOLMAFA_KOLMAFIA_HOME` fixture plus `kolmafa repl --once "respond player"` | Same one-shot proposal semantics as CLI. |

## Source parity anchors

- Config variables and player validation: `src/kolmafa/config.py:11-85`.
- CLI commands and safe REPL behavior: `src/kolmafa/cli.py:19-98`, `src/kolmafa/cli.py:230-280`.
- Response command and labels: `src/kolmafa/cli.py:48-52`, `src/kolmafa/cli.py:169-191`.
- REPL response command parity: `src/kolmafa/cli.py:275-283`, `src/kolmafa/cli.py:384-389`.
- Fixed response proposal/no-echo rule: `src/kolmafa/bridge.py:954-962`.
- Doctor docker-free readiness output: `src/kolmafa/cli.py:101-119`, `src/kolmafa/bridge.py:450-529`.
- Dry-run send routing: `src/kolmafa/cli.py:349-382`, `src/kolmafa/bridge.py:343-447`.
- Second-Java fallback block: `src/kolmafa/bridge.py:171-185`, `src/kolmafa/cli.py:359-377`.
- Session prefix observation and redaction: `src/kolmafa/bridge.py:780-831`, `src/kolmafa/bridge.py:856-937`.
- Response-loop regression evidence: `tests/test_cli_safe_operator_loop.py:249-340`.
- Static policy and confirmation requirement: `src/kolmafa/policy.py:58-108`.
- Durable one-shot confirmation checks: `src/kolmafa/confirmations.py:77-179`.
- Secret redaction helpers: `src/kolmafa/redaction.py:1-74`.
- SQLite audit and redaction guards: `sql/schema.sql:105-200`.
- Docker-free regression evidence: `tests/test_docker_free_regression_suite.py:9-78`.

## Naming

- **Kolmaf-AI** is the product/project name.
- **kolmafa** is the bridge package and CLI command inside the project.
