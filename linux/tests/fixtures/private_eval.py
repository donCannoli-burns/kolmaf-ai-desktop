"""Presence-checked access to intentionally non-public evaluation artifacts.

The historical adversarial-envelope artifacts (dataset.json, checkpoint-002.json,
the aligned case export, and the expected-packets export) are deliberately not
published in this repository. Tests that verify exact historical alignment or
exact historical bytes are marked ``local_artifact`` and run only when the
operator explicitly supplies the artifact location via ``KOLMAF_PRIVATE_EVAL_ROOT``.

This helper contains no private paths, no artifact bytes, and no download or
sibling-workspace guessing: it only resolves artifact filenames under the
operator-supplied root and fails closed with a precise skip when the root is
unset or an artifact is missing. Assertion outcomes are never converted to skips.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

PRIVATE_EVAL_ROOT_ENV = "KOLMAF_PRIVATE_EVAL_ROOT"

REQUIRED_ARTIFACTS = (
    "dataset.json",
    "checkpoint-002.json",
    "adversarial-envelope-aligned-v2.0.0-preprototype.json",
    "adversarial-envelope-expected-packets-v2.0.0-preprototype.json",
)


def private_eval_root() -> Path | None:
    """Return the operator-supplied private artifact root, or None when unset."""
    root = os.environ.get(PRIVATE_EVAL_ROOT_ENV)
    if not root:
        return None
    return Path(root)


def require_private_eval_artifact(name: str) -> Path:
    """Resolve one historical artifact under KOLMAF_PRIVATE_EVAL_ROOT.

    Skips precisely when the environment variable is unset or when the named
    artifact is absent. Never raises for presence problems and never converts
    assertion failures into skips.
    """
    root = private_eval_root()
    if root is None:
        pytest.skip(
            f"{PRIVATE_EVAL_ROOT_ENV} is not set; historical artifact {name!r} is "
            "intentionally non-public and unavailable in this environment"
        )
    path = root / name
    if not path.is_file():
        pytest.skip(
            f"historical artifact {name!r} not found under {PRIVATE_EVAL_ROOT_ENV} "
            f"({root}); install the private evaluation artifacts to run local_artifact tests"
        )
    return path


def require_private_eval_root() -> Path:
    """Return the private artifact root, skipping precisely when unset."""
    root = private_eval_root()
    if root is None:
        pytest.skip(
            f"{PRIVATE_EVAL_ROOT_ENV} is not set; historical artifact verification "
            "is intentionally non-public and unavailable in this environment"
        )
    return root
