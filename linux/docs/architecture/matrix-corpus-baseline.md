+++
schema = "kolmaf-work-record/v1"
id = "MATRIX-CORPUS-BASELINE"
kind = "architecture"
title = "Matrix corpus baseline and deliberate rebaseline procedure"
status = "CURRENT"
owner = "Maf-AI-Dev-Test"
created = "2026-09-28"
updated = "2026-09-28"
related = ["kolmaf://matrix/nodes", "kolmaf://matrix/manifest"]
+++

# Matrix corpus baseline and deliberate rebaseline procedure

Baseline (Slice-1 inventory, Slice-3 verification): 665 nodes, 665 unique
IDs, 665 distinct `mem://` pointers, 13 workflows, 29 usecases. The overlay
builder never writes the corpus; tests prove byte-equality before/after and
fail loudly on drift.

Deliberate rebaseline procedure (explicit human/build decision only):

1. Inspect the new Matrix corpus: diff node IDs, pointers, workflows,
   provenance pins against `source-manifest.json`.
2. Verify the update is expected (plugin release notes, sha pins).
3. Run preservation checks; confirm the only differences are the expected ones.
4. Intentionally update `MATRIX_BASELINE` in `integration/matrix/build_overlay.py`.
5. Record why in a new decision/architecture record; never auto-adjust.

Grounded alias shrinkage likewise fails loudly (alias count is in overlay
status). Never silently relink aliases.
