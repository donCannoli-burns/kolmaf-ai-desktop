# Tasks — current actionable work

One Markdown file per task. Source of truth; generated projections live under
`data/runtime/work/` and `docs/INDEX.md` (generated, do not hand-edit).

Contract: `kolmaf-work-record/v1`, TOML `+++` front matter (stdlib `tomllib`,
no new dependency). Filename must be the ID or ID-plus-slug:
`TASK-0001.md`, `TASK-0001-matrix-overlay.md`.

Required front matter: `schema id kind title status owner created updated
related`. Optional: `blocked_by depends_on verification_required next_actor`.

Statuses: `QUEUED ACTIVE BLOCKED VERIFY DONE CANCELLED`.
`BLOCKED` requires non-empty `blocked_by`. Dates `YYYY-MM-DD`,
`updated >= created`. `related` entries that are `kolmaf://` URIs must be
registered in the LinkBus registry; entries matching record IDs
(`TASK-`/`ESC-`/`ADR-`) must exist.

Validate: `$HOME/anaconda3/bin/python -m pytest tests/test_work_records.py -q`
