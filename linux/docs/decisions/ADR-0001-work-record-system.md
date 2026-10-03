+++
schema = "kolmaf-work-record/v1"
id = "ADR-0001"
kind = "decision"
title = "Adopt file-based work records with hygiene validation"
status = "ACCEPTED"
owner = "Maf-AI-Dev-Test"
created = "2026-09-28"
updated = "2026-09-28"
related = ["kolmaf://provider/matrix"]
+++

# ADR-0001: Adopt file-based work records with hygiene validation

## Context

Slices 1–3 built registry and Matrix overlays with handoff evidence only in
`docs/handoff.md` and `state/slice-*.md`. There was no predictable place for
current actionable work, blockers, durable decisions, or structural docs.

## Decision

One Markdown file per record under `docs/tasks/`, `docs/escalations/`,
`docs/decisions/`, `docs/architecture/`, with TOML `+++` front matter parsed
by stdlib `tomllib` (no new dependency), a hygiene validator, deterministic
generated indexes (`data/runtime/work/`, `docs/INDEX.md`), and a separate
Matrix work overlay. Markdown stays authoritative; generated files are
projections.

## Consequences

`docs/handoff.md` remains chronological evidence, never a task database.
`state/slice-*.md` remain migration checkpoints. No task URIs are minted;
records keep `TASK-`/`ESC-`/`ADR-` identities and carry registered
`kolmaf://` references in `related`.
