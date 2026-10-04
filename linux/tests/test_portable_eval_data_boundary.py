"""Narrow guard: portable evaluation tests must not depend on linux/data/eval/.

The historical evaluation artifacts under data/eval/ are intentionally
non-public. Portable contract tests (the public CI gate) must exercise
projection/evaluator semantics with synthetic, repository-contained inputs
only. This guard fails if any pytest-collectable test file that runs in the
portable gate regains a direct path dependency on the private data/eval/
directory.

Scope is deliberately small: pytest-collectable files under linux/tests/,
minus the two whole-file CI ignores, minus local_artifact-marked files (which
resolve artifacts via KOLMAF_PRIVATE_EVAL_ROOT and never reference data/eval/
by path), minus this guard itself.
"""

from __future__ import annotations

from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# Whole-file ignores retained by .github/workflows/linux-ci.yml.
PORTABLE_GATE_WHOLE_FILE_IGNORES = {
    "adversarial_envelope/test_phase4_lifecycle_contracts.py",
    "adversarial_envelope/test_phase6_evaluation.py",
}

# Path-construction forms that would couple a test to the private directory.
FORBIDDEN_FRAGMENTS = (
    "data/eval",
    '"data", "eval"',
    '"data" / "eval"',
    "data', 'eval'",
)

_GUARD_SELF = Path(__file__).name


def _portable_gate_test_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        rel = path.relative_to(TESTS_DIR).as_posix()
        if rel in PORTABLE_GATE_WHOLE_FILE_IGNORES:
            continue
        if path.name == _GUARD_SELF:
            continue
        if path.name.startswith("test_") or path.name.endswith("_test"):
            files.append(path)
        elif path.name == "conftest.py":
            files.append(path)
    return files


def test_portable_tests_do_not_reference_private_data_eval() -> None:
    offenders: list[str] = []
    for path in _portable_gate_test_files():
        rel = path.relative_to(TESTS_DIR).as_posix()
        text = path.read_text(encoding="utf-8")
        if "pytest.mark.local_artifact" in text:
            continue
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{rel}: forbidden fragment {fragment!r}")

    assert not offenders, (
        "portable evaluation tests must not depend on the private data/eval/ "
        f"directory; move historical-artifact checks to local_artifact tests "
        f"using KOLMAF_PRIVATE_EVAL_ROOT. Offenders: {'; '.join(offenders)}"
    )
