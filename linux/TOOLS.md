# KoLmafia Companion Tools

These projects are maintained in their own repositories and installed into KoLmafia with its Git script installer. Kolmaf-AI Desktop should discover and use their installed surfaces rather than copy their source into this repository.

## 1. kol-html-matrix

Repository: https://github.com/donCannoli-burns/kol-html-matrix

Reviewed revision:

```text
caa77c9dedde07727f0aa2a553ca24247d6c052a
```

Purpose:

- interactive human HTML5 KoLmafia scripting matrix;
- exact machine-readable agent retrieval plane;
- stable node IDs / `mem://` pointers and provenance;
- workflows/use-cases for grounded agent lookup.

Install in KoLmafia gCLI:

```text
git checkout donCannoli-burns/kol-html-matrix
```

Update:

```text
git update kol-html-matrix
```

Primary installed agent surfaces:

```text
~/.kolmafia/data/html-matrix/FOR-AGENT.html
~/.kolmafia/data/html-matrix/agent-master-index.json
~/.kolmafia/data/html-matrix/hyper-data.json
~/.kolmafia/data/html-matrix/source-manifest.json
```

Use it as retrieval/reference material. Preserve source IDs/provenance when practical, do not treat a matrix result as execution permission, and re-check live/version-sensitive facts against installed KoLmafia runtime evidence.

## 2. kol-goblin-docs

Repository: https://github.com/donCannoli-burns/kol-goblin-docs

Reviewed revision:

```text
6c4c516c312a79a6eeeff164982ddebcce79fff0
```

Purpose:

- agent-first map of major KoLmafia working areas;
- editable HTML5 branch documentation;
- runtime snapshot/index;
- low-friction relay navigation for humans and agents.

Install in KoLmafia gCLI:

```text
git checkout https://github.com/donCannoli-burns/kol-goblin-docs
kol-goblin-docs setup
```

Update:

```text
update-llm
```

or:

```text
git update donCannoli-burns-kol-goblin-docs
kol-goblin-docs refresh git-update
```

Primary installed agent surface:

```text
~/.kolmafia/data/kol-goblin-docs/README.html
```

Use it for navigation and local-area context. Preserve user-edited docs and backups, never interpret documentation presence or wording as permission, and verify installed runtime truth before relying on a documented command/function.

## 3. kol-ash-it-down

Repository: https://github.com/donCannoli-burns/kol-ash-it-down

Reviewed revision:

```text
ce2d07fb7cd03a47c0d5ee241ddcca5bedcdbc7d
```

Purpose:

- bounded local KoLmafia document read/edit/convert bridge;
- `.md`, `.ash`, `.html`, `.html5`, `.txt`, `.xml`, and `.json` cross-formatting;
- gCLI correlation marker emission;
- `active_session.<player>` tail capture;
- local evidence/status artifacts;
- append-oriented SQLite event/audit memory with read-only query surface.

Install in KoLmafia gCLI:

```text
git checkout https://github.com/donCannoli-burns/kol-ash-it-down.git
```

Update:

```text
git update donCannoli-burns-kol-ash-it-down
```

Python/Conda side from the KoLmafia-managed checkout:

```bash
cd ~/.kolmafia/git/donCannoli-burns-kol-ash-it-down
conda env create -f environment.yml
conda activate kol-doc-edit
pip install -e .
kol-doc-edit serve
```

Local service:

```text
127.0.0.1:61337
```

Primary installed/runtime surfaces:

```text
~/.kolmafia/relay/doc_edit.ash
~/.kolmafia/data/doc_edit/
~/.kolmafia/sessions/active_session.<player>
```

Use it for bounded local document operations, conversions, evidence capture, and its own audit queries. Retain preview → confirm → backup → atomic write → event-record semantics. Do not turn its Python service into a KoL mutation path. A session marker proves the gCLI marker path ran, not that an unrelated KoL mutation succeeded.

## 4. actor-engine

Repository: https://github.com/donCannoli-burns/actor-engine

Reviewed revision:

```text
200f5e458d01be7cffb097f5015633712c8ff5c8
```

Purpose:

- Go + ASH actor/state control plane around KoLmafia;
- concurrent-state runtime observations instead of one monolithic FSM;
- KoLmafia release monitoring and installed-JAR revision inspection;
- read-only Kingdomsitter health/state observation;
- exact-state-digest proposal confirmation and receipts;
- one bounded v0.1.0 write: local KoLmafia release staging;
- transport clients for Go, Rust, Kotlin, C#, C++, C, and Swift.

Install the KoLmafia-facing projection in gCLI:

```text
git checkout https://github.com/donCannoli-burns/actor-engine.git main
```

Install/start the Go sidecar separately:

```bash
go install github.com/donCannoli-burns/actor-engine/cmd/kol-actor-engine@latest
kol-actor-engine
```

Update:

```text
git update actor-engine
```

and separately refresh the Go binary when wanted:

```bash
go install github.com/donCannoli-burns/actor-engine/cmd/kol-actor-engine@latest
```

Primary installed/runtime surfaces:

```text
~/.kolmafia/scripts/kol_actor.ash
~/.kolmafia/data/actor-engine/runtime.json
http://127.0.0.1:10424/v1/state
http://127.0.0.1:10424/v1/release/latest
```

The ASH shim is observation-only. In v0.1.0 the Go engine does not expose arbitrary ASH/gCLI execution, release installation/restart, or live game mutation. Its implemented write is state-bound, human-confirmed local release staging.

Desktop page: https://doncannoli-burns.github.io/kolmaf-ai-desktop/actor-engine.html

## Suggested install order

For a fresh KoLmafia home:

```text
git checkout donCannoli-burns/kol-html-matrix
git checkout https://github.com/donCannoli-burns/kol-goblin-docs
git checkout https://github.com/donCannoli-burns/kol-ash-it-down.git
git checkout https://github.com/donCannoli-burns/actor-engine.git main
kol-goblin-docs setup
```

Then configure/start the Ash-It-Down Conda service outside gCLI when that capability is needed.

Kolmaf-AI Desktop may expose a readiness view showing whether each expected checkout/surface is present, whether the optional Ash-It-Down localhost service is healthy, and whether a reviewed revision has changed. It must not expose secret values or silently create an alternate ungoverned execution path when one of these projects is unavailable.
