# Official Linux Dependencies

These three projects are first-class external dependencies of Kolmaf-AI Desktop on Linux.

They are intentionally maintained in their own repositories and installed into KoLmafia with its Git script installer. Kolmaf-AI Desktop should **discover and use the installed surfaces**, not copy their source into this repository.

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

Desktop contract:

- use as retrieval/reference;
- preserve source IDs/provenance when practical;
- do not treat a matrix result as execution permission;
- re-check live/version-sensitive facts against installed KoLmafia runtime evidence.

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

Desktop contract:

- use for navigation and local-area context;
- preserve user-edited docs and backups;
- never interpret documentation presence or wording as permission;
- verify installed runtime truth before relying on a documented command/function.

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

Desktop contract:

- use for bounded local document operations, conversions, evidence capture, and its own audit queries;
- retain preview → confirm → backup → atomic write → event-record semantics;
- do not turn its Python service into a KoL mutation path;
- a session marker proves the gCLI marker path ran, not that an unrelated KoL mutation succeeded.

## Recommended install/order

For a fresh KoLmafia home:

```text
git checkout donCannoli-burns/kol-html-matrix
git checkout https://github.com/donCannoli-burns/kol-goblin-docs
git checkout https://github.com/donCannoli-burns/kol-ash-it-down.git
kol-goblin-docs setup
```

Then configure/start the Ash-It-Down Conda service outside gCLI when that capability is needed.

## Readiness behavior

Kolmaf-AI Desktop should eventually expose one dependency/readiness check that reports, separately:

- installed checkout present;
- expected installed data/relay/script surface present;
- dependency revision/update state when knowable;
- optional localhost service health for Ash-It-Down;
- no secret values.

A missing dependency should be a visible readiness failure/degradation, not an excuse to silently create an alternate ungoverned execution path.
