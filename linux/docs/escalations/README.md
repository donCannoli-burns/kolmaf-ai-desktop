# Escalations — explicit blockers, open or resolved

One Markdown file per escalation. An escalation is a fact about missing
authorization, evidence, or decision — never an automatic authorization.
`LIVE_AUTH_REQUIRED` means authorization is absent.

Contract: `kolmaf-work-record/v1`, TOML `+++` front matter. Filename must be
the ID or ID-plus-slug: `ESC-0001.md`.

Required front matter: `schema id kind title status owner created updated
related class reason`. Optional: `task next_actor resolution`
(`resolution` required when `RESOLVED`).

Classes: `HUMAN_DECISION LIVE_AUTH_REQUIRED EVIDENCE_STALE PROVIDER_MISSING
CONTRACT_DRIFT TEST_FAILURE AMBIGUOUS_RESULT SECURITY_BOUNDARY`.
Statuses: `OPEN RESOLVED CANCELLED`.
