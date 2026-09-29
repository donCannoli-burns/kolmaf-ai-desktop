# Kolmaf-AI Desktop

**LLM intelligence, KoLmafia runtime truth.**

Kolmaf-AI is an experimental, local-first desktop/control layer for connecting **LLM reasoning** to **KoLmafia** without pretending the model is the game client.

The model can inspect context, retrieve grounded references, reason, explain, debug, and prepare bounded action proposals. KoLmafia remains the game-aware local runtime that knows the player state and talks to the game. State-changing actions stay behind explicit policy, confirmation, state-binding, transport, and readback boundaries.

> **Project status:** early / active development  
> **Current platform:** Linux  
> **Windows / macOS:** planned, with no release date promised  
> **Public project page:** https://doncannoli-burns.github.io/kolmaf-ai-desktop/
> **Actor Engine page:** https://doncannoli-burns.github.io/kolmaf-ai-desktop/actor-engine.html

---

## What Kolmaf-AI is

Think of Kolmaf-AI as a control desk between:

```text
human
  +
desktop workspace
  +
LLM reasoning
  +
grounded local context
  +
policy / confirmation gates
  +
KoLmafia runtime truth
```

The design goal is **not** “let the AI loose.”

It is to make an LLM genuinely useful around KoLmafia while keeping permission, mutation authority, runtime truth, and verification outside the model's own confidence.

LLMs can misunderstand state, invent details, use stale knowledge, or propose the wrong command. Kolmaf-AI is designed around that assumption.

---

## Runtime model

The public desktop architecture is:

```text
Human intent
    ↓
Desktop
    ↓
LLM
    ↓
Context / knowledge tools
    ↓
Policy / confirmation gate
    ↓
KoLmafia
    ↓
Independent readback
```

### What the LLM is for

- turning a human goal into a concrete plan;
- reading structured KoLmafia references and local documentation;
- retrieving typed or provenance-carrying evidence instead of relying on memory alone;
- explaining state and surfacing uncertainty;
- drafting bounded action proposals instead of silently executing them;
- helping debug, test, and document the local system.

### What KoLmafia is for

- being the actual game-aware local runtime;
- providing ASH, gCLI, relay, preferences, session evidence, and live state;
- performing approved game interactions through the intended local path;
- providing runtime truth that the desktop can independently verify.

A polished model response is not authority. A retrieval hit is not authority. A mock result is not permission to fall through to live KoLmafia.

---

## Trust model

Kolmaf-AI separates **evidence**, **reasoning**, **permission**, and **execution**.

Core rules:

- **evidence ≠ authority**
- **prompt ≠ permission**
- **mock ≠ live fallback**
- **LLM output = proposal material**
- live/version-sensitive facts should be checked against the installed runtime;
- state-changing actions should be bound to the state that was actually reviewed;
- a successful transport return is not the same as a verified game-state result;
- ambiguous write outcomes must not be blindly retried.

For the Don Edition / dev-test lineage, the intended approved-write shape is:

```text
live state
→ normalized proposal
→ exact state binding
→ durable confirmation
→ final live-state recheck
→ one governed transport
→ read-only reconciliation
```

---

## Use safely

This is experimental software. Treat model mistakes as expected.

Before testing mutating features:

1. **Back up your KoLmafia home.** Keep a restore copy that does not depend on the AI or the current install.
2. **Minimize exposed Meat.** Consider keeping only the amount you actually need readily spendable during early mutation testing.
3. **Read the proposal.** Verify target, quantity, cost, location, and state assumptions yourself.
4. **Prefer reversible tests.** Start with low-cost actions whose result is easy to inspect.
5. **Keep secrets out of prompts and reports.** Do not paste passwords, relay hashes, API keys, session cookies, or other credentials into model conversations or public issues.
6. **Verify after mutation.** Read the resulting state back independently instead of trusting the tool response alone.

---

## Tool constellation

Kolmaf-AI is intentionally split across **nine companion projects** rather than asking one giant model prompt or one privileged bridge to do everything.

The following **01–09 registry is the canonical discovery list** for the public companion ecosystem. Agents should start here instead of rediscovering related repositories ad hoc. The Linux runtime manifest is intentionally narrower and currently tracks only four reviewed runtime-facing integrations.

| # | Project | Role | Boundary |
|---:|---|---|---|
| 01 | [kol-agent-sandbox](https://github.com/donCannoli-burns/kol-agent-sandbox) | Isolated agent testing around a pinned `loathers/kolmafia-mock` | Safe proving ground; mock failure never authorizes live fallback |
| 02 | [tokens-of-loathing](https://github.com/donCannoli-burns/tokens-of-loathing) | Typed KoL game data through SQLite plus client/API/MCP compatibility surfaces | Queryable facts, not live execution authority |
| 03 | [kol-agent-memory](https://github.com/donCannoli-burns/kol-agent-memory) | KoLmafia-local structured memory with SYSTEM / STATE / LOCAL / ROUTING planes | Context can survive; routing indexes do not become live-state authority |
| 04 | [kolmafia-skills](https://github.com/donCannoli-burns/kolmafia-skills) | KoLmafia-native task-guidance / skill bus using a spaceless `/skill@...` namespace | Skill text is guidance, not permission |
| 05 | [kol-ash-it-down](https://github.com/donCannoli-burns/kol-ash-it-down) | Bounded local document/edit/convert bridge, gCLI correlation evidence, session-tail capture, and local audit memory | Not a second KoL mutation executor |
| 06 | [kol-goblin-docs](https://github.com/donCannoli-burns/kol-goblin-docs) | Agent-first HTML5 map of the local KoLmafia tree and editable runtime documentation | Navigation/context only; documentation does not grant authority |
| 07 | [kol-html-matrix](https://github.com/donCannoli-burns/kol-html-matrix) | Human relay UI plus machine-readable KoLmafia scripting/retrieval matrix | Reference/retrieval only; provenance helps grounding, not authorization |
| 08 | [kingdomsitter](https://github.com/donCannoli-burns/kingdomsitter) | Go + Tree-sitter ASH language sidecar with typed IR, agent-readable analysis, and ASH → TypeScript/Libram emission | Language/tooling bridge only in v0; KoLmafia remains authoritative for live game state and mutations |
| 09 | [actor-engine](https://github.com/donCannoli-burns/actor-engine) | Go + ASH actor/state control plane with release monitoring, state-digest confirmation, receipts, and multi-language clients | Proposal-and-confirmed local staging only in v0.1.0; no arbitrary ASH/gCLI, install/restart, or live game mutation |

A shorthand view:

```text
sandbox   → test away from live state
tokens    → typed game data
memory    → structured local context
skills    → task guidance
ash-it-down → bounded files + evidence
goblin docs → navigate the local runtime
html matrix → retrieve grounded references
kingdomsitter → parse, type, analyze, and bridge ASH
actor engine → concurrent state plane + proposal binding + release staging
desktop   → workspace + proposal + policy gate
KoLmafia  → runtime truth
```

### Current integration metadata

The broader ecosystem above contains **nine companion projects (01–09)**. The Linux integration manifest in this repository currently records four reviewed runtime-facing companion surfaces:

- `kol-goblin-docs`
- `kol-html-matrix`
- `kol-ash-it-down`
- `actor-engine`

See:

- [`linux/TOOLS.md`](linux/TOOLS.md)
- [`linux/tools.json`](linux/tools.json)

That manifest is intentionally narrower than the ecosystem list; it describes reviewed desktop/runtime integration surfaces, not every related project.

---

## Active platform: Linux

The current development line is Linux-first and lives under:

```text
/linux/
```

The active lineage is:

```text
Kolmaf-AI Don Edition
kolmaf-ai-v.0.0.1.-dev_test-linux
```

Historical Don Edition handoff material reports a Python `kolmafa` runtime spine with a state-bound T2 proposal/confirmation/write path, structural T3 denial, and a real relay writer behind the broker. The latest archived checkpoint supplied to this repository reported:

```text
83 devtest passed
439 total passed
0 failures
```

Those numbers are **archived handoff evidence**, not a claim that this repository has freshly rerun that suite.

### Current repository state

This repository currently contains:

```text
/
├── index.html          # GitHub Pages project page
├── README.md
├── AGENTS.md
└── linux/
    ├── README.md
    ├── TOOLS.md
    └── tools.json
```

The working Linux runtime source should be published/imported under `/linux/` from the real working tree rather than reconstructed from historical summaries. Functioning module names and boundaries should win over a cosmetic re-layout.

Machine runtime state, credentials, session logs, local databases, caches, and private account material do not belong in Git.

---

## Integration rules

Companion tools stay in their own repositories and keep their own trust boundaries.

Kolmaf-AI Desktop should:

- discover and use reviewed installed surfaces instead of silently vendoring them;
- preserve provenance when reference tools provide it;
- keep documentation/retrieval systems separate from execution authority;
- keep local document/evidence helpers from becoming hidden KoL executors;
- report missing or stale dependencies rather than substituting an ungoverned alternate path;
- keep secrets out of logs, commits, prompts, and model-visible diagnostics;
- use the desktop/runtime's explicit proposal → confirmation → transport → readback path for live mutations.

---

## Contributing

Discussion is part of the build.

Questions, testing, pushback, patches, UX ideas, Linux packaging help, cross-platform work, and corrections from experienced KoLmafia users are welcome.

Especially useful feedback includes:

- a model/runtime boundary that feels wrong;
- a tool contract that is confusing or too permissive;
- Linux setup that is unnecessarily brittle;
- missing provenance or weak readback;
- a companion tool exposing the wrong evidence surface;
- documentation that does not match current KoLmafia behavior.

Use GitHub Issues for bugs/discussion and pull requests for proposed changes:

- https://github.com/donCannoli-burns/kolmaf-ai-desktop/issues
- https://github.com/donCannoli-burns/kolmaf-ai-desktop/pulls

---

## Credit

Kolmaf-AI is an integration experiment built on a much larger ecosystem.

Credit belongs especially to:

- [KoLmafia](https://github.com/kolmafia/kolmafia) — the mature desktop tool, scripting runtime, relay environment, and community foundation Kolmaf-AI connects to;
- [data-of-loathing](https://github.com/loathers/data-of-loathing) — the upstream typed game-data project behind the `tokens-of-loathing` compatibility/fork line;
- [kolmafia-mock](https://github.com/loathers/kolmafia-mock) — the upstream mock engine used by the sandbox for isolated compatibility testing;
- the KoL / KoLmafia scripting community — script authors, maintainers, wiki contributors, testers, spaders, data maintainers, and people documenting the weird edge cases that make grounded tooling possible.

Kolmaf-AI does **not** claim to have invented the underlying tools, data, or scripting ecosystem it builds on.

Kolmaf-AI is an independent experiment. It is not affiliated with, maintained by, or endorsed by the KoLmafia project.

---

## License

MIT. See [LICENSE](LICENSE).
