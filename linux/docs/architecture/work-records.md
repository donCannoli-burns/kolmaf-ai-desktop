+++
schema = "kolmaf-work-record/v1"
id = "WORK-RECORDS"
kind = "architecture"
title = "File-based work records and hygiene pipeline"
status = "CURRENT"
owner = "Maf-AI-Dev-Test"
created = "2026-09-28"
updated = "2026-09-28"
related = ["kolmaf://provider/matrix"]
+++

# Work records and hygiene pipeline

Human/agent work becomes canonical Markdown records
(`docs/tasks|escalations|decisions|architecture/`). `integration/work/`
parses (`records.py`), validates (`validate.py`), and projects them:
normalized JSON under `data/runtime/work/`, human-readable `docs/INDEX.md`,
and a Matrix work overlay at
`data/runtime/matrix/kolmaf-work-overlay.json` reusing the Slice-3 substring
search path with explicit source namespaces (`matrix-corpus`,
`kolmaf-provider-overlay`, `kolmaf-work-overlay`).

Task status is not authority; escalation class is not authority;
documentation is never execution permission. Hygiene reports problems and
never silently repairs intent; generators build-then-replace atomically and
leave previous outputs intact on failure.
