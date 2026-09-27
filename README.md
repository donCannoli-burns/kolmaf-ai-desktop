# Kolmaf-AI Desktop

Desktop home for the Kolmaf-AI development/runtime interface.

## Active platform

The current development line is **Linux** and lives under:

```text
/linux/
```

Platform-specific source, tests, launchers, and packaging should stay inside their platform directory. Shared repository-level documentation may remain at the root.

## Official KoLmafia-side dependencies

Kolmaf-AI Desktop depends on three separately maintained KoLmafia Git projects:

| Dependency | Role |
|---|---|
| [kol-goblin-docs](https://github.com/donCannoli-burns/kol-goblin-docs) | Agent-first runtime/navigation documentation map for the installed KoLmafia tree |
| [kol-html-matrix](https://github.com/donCannoli-burns/kol-html-matrix) | Human relay UI + machine-readable KoLmafia scripting/retrieval knowledge plane |
| [kol-ash-it-down](https://github.com/donCannoli-burns/kol-ash-it-down) | Bounded document conversion/edit bridge, gCLI correlation evidence, session-tail capture, and local audit memory |

These are **external dependencies**, not vendored copies. They remain installed and updated through KoLmafia's Git checkout mechanism.

The Linux dependency contract and reviewed revisions are recorded in:

```text
linux/DEPENDENCIES.md
linux/dependencies.json
```

## Integration rule

The three dependency projects provide context, evidence, documentation, and bounded local tooling. Their presence does not create execution authority.

Kolmaf-AI Desktop must preserve the upstream boundaries:

- Goblin Docs documentation is navigation/context, not permission.
- HTML Matrix retrieval/reference material is not execution authority.
- Ash-It-Down is not a second KoL executor; its Python service must remain outside KoLmafia mutation transport.
- Live or version-sensitive facts must be checked against the installed runtime.
- Mutations remain governed by the desktop/runtime's own authority, confirmation, and verification path.

## Linux development line

The current Linux build lineage is the **Kolmaf-AI Don Edition / dev-test** line. The verified handoff supplied for this repository reports a Python `kolmafa` runtime spine, a state-bound T2 proposal/confirmation/write path, structural T3 denial, a real relay writer behind the broker, and **83 devtest / 439 total tests passing** at the latest archived checkpoint.

The actual working Linux source should be imported into `/linux/`; do not reconstruct source code from summaries when the working tree is available.

## License

MIT. See [LICENSE](LICENSE).
