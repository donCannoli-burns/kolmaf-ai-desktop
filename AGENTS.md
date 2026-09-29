# AGENTS.md — kolmaf-ai-desktop

Start with `linux/README.md` for the active platform.

## Repository rules

1. The active development platform is `/linux/`.
2. Treat the projects listed in `linux/tools.json` as separately maintained KoLmafia companion tools. Do not vendor or silently fork them into this repository.
3. Do not infer execution permission from documentation, indexes, retrieval hits, session logs, or successful tool returns.
4. Resolve live/version-sensitive KoLmafia facts against the installed runtime before depending on them.
5. Preserve each tool's authority boundary:
   - Goblin Docs = navigation/context.
   - HTML Matrix = retrieval/reference.
   - Ash-It-Down = bounded local document/evidence bridge, not a KoL mutation executor.
   - Actor Engine = actor/state control plane; v0.1.0 authority is exact-state-confirmed local release staging only.
6. Do not modify those working copies while implementing desktop changes unless the task explicitly targets that project.
7. Do not print, commit, log, or expose relay credentials, daily hashes, API keys, account secrets, session cookies, or private runtime state.
8. Keep generated logs, local databases, caches, credentials, and machine-specific runtime state out of Git.
9. For live KoL mutations, use only the desktop/runtime's explicit proposal/confirmation/transport path and independently read back the resulting state.
10. If one of these tools is missing, stale, or structurally incompatible, report the condition instead of substituting a hidden alternate executor.

## Tool entry points

- `~/.kolmafia/data/kol-goblin-docs/README.html`
- `~/.kolmafia/data/html-matrix/FOR-AGENT.html`
- `~/.kolmafia/data/html-matrix/agent-master-index.json`
- `~/.kolmafia/data/html-matrix/hyper-data.json`
- `~/.kolmafia/git/donCannoli-burns-kol-ash-it-down/`
- `~/.kolmafia/data/doc_edit/`
- `~/.kolmafia/scripts/kol_actor.ash`
- `~/.kolmafia/data/actor-engine/runtime.json`
- `http://127.0.0.1:10424/v1/state`

See `linux/TOOLS.md` for install/update and integration details.
