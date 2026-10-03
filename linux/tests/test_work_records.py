"""Work-record Slice-4 tests (offline only).

Taxonomy:
- Unmarked tests are PORTABLE_CONTRACT: lifecycle, negative, determinism,
  atomicity, work-overlay, and multi-plane search tests run against tmp_path
  record trees plus a portable LinkBus registry derived from the committed
  source manifests (tests/fixtures/portable.py). The dependency boundary is
  explicit: every compile/validate call receives an injected registry path;
  no test implicitly reads data/runtime/... or ~/.kolmafia.
- `local_runtime` tests assert against the real generated registry
  (data/runtime/linkbus/registry.json), the real generated provider overlay,
  and the real installed Matrix corpus.

Real tree: genuine records only (1 ADR, 2 architecture, 0 tasks/escalations).
Lifecycles, negative cases, and search fixtures live in tmp trees — never in
the real source tree.
"""

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integration"
REGISTRY_PATH = ROOT / "data" / "runtime" / "linkbus" / "registry.json"
MANIFESTS_DIR = INTEGRATION / "providers"

sys.path.insert(0, str(INTEGRATION))
sys.path.insert(0, str(ROOT / "tests"))

importlib.import_module("work.records")
importlib.import_module("work.validate")
importlib.import_module("work.build_index")
importlib.import_module("work.build_matrix_overlay")
importlib.import_module("matrix.build_overlay")
R = sys.modules["work.records"]
V = sys.modules["work.validate"]
I = sys.modules["work.build_index"]
W = sys.modules["work.build_matrix_overlay"]
M = sys.modules["matrix.build_overlay"]

from fixtures.portable import MATRIX_FIXTURE_HOME, write_portable_registry  # noqa: E402


def _portable_registry(tmp_path):
    """Portable registry fixture: committed-manifest identities, no host paths."""
    return write_portable_registry(tmp_path / "registry.json")


def _registered(registry_path):
    uris, err = I.registered_uris(registry_path)
    assert err is None
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    assert len(uris) == len(registry["identities"]) + len(registry["providers"])
    return uris


def _task(rid="TASK-0001", status="QUEUED", **kw):
    fields = {
        "schema": '"kolmaf-work-record/v1"',
        "id": f'"{rid}"',
        "kind": '"task"',
        "title": '"T"',
        "status": f'"{status}"',
        "owner": '"Maf-AI-Dev-Test"',
        "created": '"2026-09-28"',
        "updated": '"2026-09-28"',
        "related": "[]",
    }
    fields.update(kw)
    front = "\n".join(f"{k} = {v}" for k, v in fields.items())
    return f"+++\n{front}\n+++\n\n# T\n\n## Goal\n\nx\n"


def _escalation(rid="ESC-0001", status="OPEN", **kw):
    fields = {
        "schema": '"kolmaf-work-record/v1"',
        "id": f'"{rid}"',
        "kind": '"escalation"',
        "title": '"E"',
        "status": f'"{status}"',
        "owner": '"Maf-AI-Dev-Test"',
        "created": '"2026-09-28"',
        "updated": '"2026-09-28"',
        "related": "[]",
        "class": '"HUMAN_DECISION"',
        "reason": '"need a ruling"',
    }
    fields.update(kw)
    front = "\n".join(f"{k} = {v}" for k, v in fields.items())
    return f"+++\n{front}\n+++\n\n# E\n\n## Reason\n\nneed a ruling\n"


def _decision(rid="ADR-0001", status="ACCEPTED", **kw):
    fields = {
        "schema": '"kolmaf-work-record/v1"',
        "id": f'"{rid}"',
        "kind": '"decision"',
        "title": '"D"',
        "status": f'"{status}"',
        "owner": '"Maf-AI-Dev-Test"',
        "created": '"2026-09-28"',
        "updated": '"2026-09-28"',
        "related": "[]",
    }
    fields.update(kw)
    front = "\n".join(f"{k} = {v}" for k, v in fields.items())
    return f"+++\n{front}\n+++\n\n# D\n\n## Context\n\nx\n"


def _arch(rid="ALPHA", status="CURRENT", **kw):
    fields = {
        "schema": '"kolmaf-work-record/v1"',
        "id": f'"{rid}"',
        "kind": '"architecture"',
        "title": '"A"',
        "status": f'"{status}"',
        "owner": '"Maf-AI-Dev-Test"',
        "created": '"2026-09-28"',
        "updated": '"2026-09-28"',
        "related": "[]",
    }
    fields.update(kw)
    front = "\n".join(f"{k} = {v}" for k, v in fields.items())
    return f"+++\n{front}\n+++\n\n# A\n\n## Structure\n\nx\n"


def _scaffold(root: Path):
    for sub in ("tasks", "escalations", "decisions", "architecture"):
        (root / "docs" / sub).mkdir(parents=True, exist_ok=True)


def _write(root: Path, sub: str, name: str, content: str) -> Path:
    path = root / "docs" / sub / name
    path.write_text(content, encoding="utf-8")
    return path


def _validate(root: Path, registry_path):
    records, load_errors = R.load_all(root)
    errors = list(load_errors)
    errors.extend(V.validate_all(records, _registered(registry_path), root))
    return records, errors


def _codes(errors):
    return {e["code"] for e in errors}


# --- real tree: genuine records only -------------------------------------------
# The real records' kolmaf:// references are validated against the portable
# registry derived from the committed source manifests; the URI set is
# identical to the generated registry's, so no host state is required.


def test_real_records_parse():
    records, load_errors = R.load_all(ROOT)
    assert load_errors == []
    assert sorted(d["id"] for d in records) == ["ADR-0001", "MATRIX-CORPUS-BASELINE", "WORK-RECORDS"]


def test_real_tree_valid(tmp_path):
    records, _ = R.load_all(ROOT)
    assert V.validate_all(records, _registered(_portable_registry(tmp_path)), ROOT) == []


def test_real_ids_unique():
    records, _ = R.load_all(ROOT)
    ids = [d["id"] for d in records]
    assert len(set(ids)) == len(ids)


# --- negative fixtures ------------------------------------------------------------


def test_duplicate_task_id(tmp_path):
    _scaffold(tmp_path)
    _write(tmp_path, "tasks", "TASK-0001.md", _task())
    _write(tmp_path, "tasks", "TASK-0001-again.md", _task())
    _, errors = _validate(tmp_path, _portable_registry(tmp_path))
    assert "DUPLICATE_ID" in _codes(errors)


def test_filename_id_binding(tmp_path):
    _scaffold(tmp_path)
    _write(tmp_path, "tasks", "WRONG.md", _task())
    _, errors = _validate(tmp_path, _portable_registry(tmp_path))
    assert "FILENAME_ID_MISMATCH" in _codes(errors)


def test_missing_owner(tmp_path):
    _scaffold(tmp_path)
    _write(tmp_path, "tasks", "TASK-0001.md", _task(owner='""'))
    _, errors = _validate(tmp_path, _portable_registry(tmp_path))
    assert "MISSING_OWNER" in _codes(errors)


def test_unknown_task_state(tmp_path):
    _scaffold(tmp_path)
    _write(tmp_path, "tasks", "TASK-0001.md", _task(status="FROBNICATING"))
    _, errors = _validate(tmp_path, _portable_registry(tmp_path))
    assert "UNKNOWN_TASK_STATUS" in _codes(errors)


def test_unknown_escalation_class(tmp_path):
    _scaffold(tmp_path)
    _write(tmp_path, "escalations", "ESC-0001.md", _escalation(**{"class": '"VIBES"'}))
    _, errors = _validate(tmp_path, _portable_registry(tmp_path))
    assert "UNKNOWN_ESCALATION_CLASS" in _codes(errors)


def test_blocked_without_blocker(tmp_path):
    _scaffold(tmp_path)
    _write(tmp_path, "tasks", "TASK-0001.md", _task(status="BLOCKED"))
    _, errors = _validate(tmp_path, _portable_registry(tmp_path))
    assert "BLOCKED_WITHOUT_BLOCKER" in _codes(errors)


def test_broken_record_reference(tmp_path):
    _scaffold(tmp_path)
    _write(tmp_path, "tasks", "TASK-0001.md", _task(depends_on='["TASK-9999"]'))
    _, errors = _validate(tmp_path, _portable_registry(tmp_path))
    assert "BROKEN_REFERENCE" in _codes(errors)


def test_unknown_kolmaf_uri(tmp_path):
    _scaffold(tmp_path)
    _write(
        tmp_path, "tasks", "TASK-0001.md",
        _task(related='["kolmaf://provider/ghost"]'),
    )
    _, errors = _validate(tmp_path, _portable_registry(tmp_path))
    assert "UNKNOWN_URI" in _codes(errors)


def test_bad_supersession(tmp_path):
    _scaffold(tmp_path)
    _write(
        tmp_path, "decisions", "ADR-0001.md",
        _decision(status="SUPERSEDED", superseded_by='"ADR-9999"'),
    )
    _, errors = _validate(tmp_path, _portable_registry(tmp_path))
    assert "BAD_SUPERSESSION" in _codes(errors)


def test_malformed_front_matter(tmp_path):
    _scaffold(tmp_path)
    _write(tmp_path, "tasks", "TASK-0001.md", "# no front matter here\n")
    records, load_errors = R.load_all(tmp_path)
    assert records == []
    assert any(e["code"] == "MALFORMED_RECORD" for e in load_errors)


def test_generated_marker_tamper(tmp_path):
    _scaffold(tmp_path)
    _write(tmp_path, "tasks", "TASK-0001.md", _task())
    (tmp_path / "docs" / "INDEX.md").write_text("# hand edited\n", encoding="utf-8")
    _, errors = _validate(tmp_path, _portable_registry(tmp_path))
    assert "GENERATED_EDITED" in _codes(errors)


# --- lifecycle fixtures --------------------------------------------------------------


def test_task_lifecycle_queued_to_done(tmp_path):
    _scaffold(tmp_path)
    registry_path = _portable_registry(tmp_path)
    path = _write(tmp_path, "tasks", "TASK-0001.md", _task(status="QUEUED"))
    for status in ("QUEUED", "ACTIVE", "VERIFY", "DONE"):
        path.write_text(_task(status=status), encoding="utf-8")
        _, errors = _validate(tmp_path, registry_path)
        assert errors == [], (status, errors)


def test_blocked_escalation_cycle(tmp_path):
    _scaffold(tmp_path)
    registry_path = _portable_registry(tmp_path)
    task = _write(tmp_path, "tasks", "TASK-0001.md", _task(status="ACTIVE"))
    esc = _write(tmp_path, "escalations", "ESC-0001.md", _escalation(task='"TASK-0001"'))
    task.write_text(_task(status="BLOCKED", blocked_by='["ESC-0001"]'), encoding="utf-8")
    _, errors = _validate(tmp_path, registry_path)
    assert errors == [], errors
    esc.write_text(
        _escalation(status="RESOLVED", task='"TASK-0001"', resolution='"ruled"'),
        encoding="utf-8",
    )
    task.write_text(_task(status="VERIFY", blocked_by='["ESC-0001"]'), encoding="utf-8")
    _, errors = _validate(tmp_path, registry_path)
    assert errors == [], errors
    task.write_text(_task(status="DONE", blocked_by='["ESC-0001"]'), encoding="utf-8")
    _, errors = _validate(tmp_path, registry_path)
    assert errors == [], errors


def test_decision_and_architecture_supersession(tmp_path):
    _scaffold(tmp_path)
    registry_path = _portable_registry(tmp_path)
    first = _write(tmp_path, "decisions", "ADR-0001.md", _decision())
    _write(tmp_path, "decisions", "ADR-0002.md", _decision(rid="ADR-0002"))
    first.write_text(
        _decision(status="SUPERSEDED", superseded_by='"ADR-0002"'), encoding="utf-8"
    )
    _, errors = _validate(tmp_path, registry_path)
    assert errors == [], errors
    old = _write(tmp_path, "architecture", "alpha.md", _arch())
    _write(tmp_path, "architecture", "beta.md", _arch(rid="BETA"))
    old.write_text(_arch(status="SUPERSEDED", superseded_by='"BETA"'), encoding="utf-8")
    _, errors = _validate(tmp_path, registry_path)
    assert errors == [], errors


# --- determinism + atomicity ------------------------------------------------------------


def _fixture_tree(root: Path):
    _scaffold(root)
    _write(root, "tasks", "TASK-0001.md", _task(status="ACTIVE"))
    _write(
        root, "escalations", "ESC-0001.md",
        _escalation(**{"class": '"PROVIDER_MISSING"'}),
    )
    _write(root, "decisions", "ADR-0001.md", _decision())
    _write(root, "architecture", "alpha.md", _arch())


def _snapshot(paths):
    return {str(p): Path(p).read_bytes() for p in paths if Path(p).exists()}


def test_index_deterministic(tmp_path):
    _fixture_tree(tmp_path)
    registry_path = _portable_registry(tmp_path)
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    code, _ = I.compile_all(tmp_path, registry_path, out_a, tmp_path / "ia.md")
    assert code == 0
    code, _ = I.compile_all(tmp_path, registry_path, out_b, tmp_path / "ib.md")
    assert code == 0
    for name in ("records.json", "tasks.json", "escalations.json"):
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes()
    assert (tmp_path / "ia.md").read_bytes() == (tmp_path / "ib.md").read_bytes()


def test_failure_preserves_previous_outputs(tmp_path):
    _fixture_tree(tmp_path)
    registry_path = _portable_registry(tmp_path)
    out = tmp_path / "out"
    code, _ = I.compile_all(tmp_path, registry_path, out, tmp_path / "docs" / "INDEX.md")
    assert code == 0
    before = _snapshot([out / "records.json", out / "status.json",
                        tmp_path / "docs" / "INDEX.md"])
    assert len(before) == 3
    _write(tmp_path, "tasks", "TASK-0002.md", _task(rid="TASK-0002", status="BOGUS"))
    code, result = I.compile_all(
        tmp_path, registry_path, out, tmp_path / "docs" / "INDEX.md")
    assert code == 1 and not result["ok"]
    assert _snapshot(list(before)) == before


# --- work overlay ------------------------------------------------------------------


def test_work_overlay_deterministic_and_shaped(tmp_path):
    _fixture_tree(tmp_path)
    registry_path = _portable_registry(tmp_path)
    out_a, out_b = tmp_path / "a.json", tmp_path / "b.json"
    code, _ = W.compile_all(tmp_path, registry_path, out_a, tmp_path / "sa.json")
    assert code == 0
    code, _ = W.compile_all(tmp_path, registry_path, out_b, tmp_path / "sb.json")
    assert code == 0
    assert out_a.read_bytes() == out_b.read_bytes()
    overlay = json.loads(out_a.read_text(encoding="utf-8"))
    assert overlay["schema"] == "kolmaf-work-overlay/v1"
    assert overlay["root"]["children"] == [
        "kolmaf-work-tasks", "kolmaf-work-escalations",
        "kolmaf-work-decisions", "kolmaf-work-architecture",
    ]
    assert all(r["uri"] is None for r in overlay["records"])
    assert overlay["counts"] == {"records": 4, "by_kind": {
        "task": 1, "escalation": 1, "decision": 1, "architecture": 1}}


def test_search_three_planes(tmp_path):
    registry_path = _portable_registry(tmp_path)
    _scaffold(tmp_path)
    _write(tmp_path, "tasks", "TASK-0001-memory.md",
           _task(rid="TASK-0001", status="BLOCKED", title='"Memory index refresh"',
                 blocked_by='["ESC-0001"]'))
    _write(tmp_path, "escalations", "ESC-0001.md",
           _escalation(**{"class": '"PROVIDER_MISSING"',
                          "reason": '"provider endpoint unreachable"'}))
    _write(tmp_path, "architecture", "matrix-arch.md",
           _arch(rid="MATRIX-ARCH", title='"Matrix architecture notes"'))
    records, errors = R.load_all(tmp_path)
    assert errors == []
    from work.validate import validate_all as _v

    assert _v(records, _registered(registry_path), tmp_path) == []
    matrix_records = [
        M.adapt_matrix_node(n) for n in M.load_corpus_nodes(MATRIX_FIXTURE_HOME)
    ]
    overlay_out = tmp_path / "matrix-out"
    code, _ = M.compile_all(MATRIX_FIXTURE_HOME, registry_path, MANIFESTS_DIR, overlay_out)
    assert code == 0
    overlay = json.loads((overlay_out / "kolmaf-overlay.json").read_text(encoding="utf-8"))
    provider_records = [M.adapt_overlay_node(n)
                        for n in overlay["providers"] + overlay["identities"]]
    for record in provider_records:
        record["plane"] = "kolmaf-provider-overlay"
    work_records = [W.adapt_work_record(d) for d in records]
    combined = matrix_records + provider_records + work_records
    assert {r.get("plane", "matrix-corpus") for r in matrix_records} == {"matrix-corpus"}
    expectations = {
        "blocked": "kolmaf-work-overlay",
        "memory": "kolmaf-work-overlay",
        "architecture": "kolmaf-work-overlay",
        "escalation": "kolmaf-work-overlay",
        "provider": "kolmaf-work-overlay",
        "sublime": "matrix-corpus",
        "sandbox": "kolmaf-provider-overlay",
    }
    for query, plane in expectations.items():
        hits = M.search_records(combined, query)
        assert any(h.get("plane", "matrix-corpus") == plane for h in hits), query


def test_work_compile_preserves_matrix_inputs(tmp_path):
    """Portable analog of the overlay/corpus preservation contract."""
    registry_path = _portable_registry(tmp_path)
    overlay_out = tmp_path / "matrix-out"
    code, _ = M.compile_all(MATRIX_FIXTURE_HOME, registry_path, MANIFESTS_DIR, overlay_out)
    assert code == 0
    overlay_path = overlay_out / "kolmaf-overlay.json"
    targets = [overlay_path] + [MATRIX_FIXTURE_HOME / n for n in M.CORPUS_FILES]
    before = _snapshot(targets)
    assert len(before) == 4
    _fixture_tree(tmp_path)
    out = tmp_path / "out"
    code, _ = I.compile_all(tmp_path, registry_path, out, tmp_path / "INDEX.md")
    assert code == 0
    code, _ = W.compile_all(tmp_path, registry_path, tmp_path / "w.json", tmp_path / "s.json")
    assert code == 0
    assert _snapshot(targets) == before


# --- real generated runtime state (local runtime profile) -------------------------


@pytest.mark.local_runtime
def test_provider_overlay_and_corpus_untouched(tmp_path):
    overlay_path = ROOT / "data" / "runtime" / "matrix" / "kolmaf-overlay.json"
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    home = M.matrix_home_from_registry(registry)
    targets = [overlay_path] + [home / n for n in M.CORPUS_FILES]
    before = _snapshot(targets)
    assert len(before) == 4
    _fixture_tree(tmp_path)
    out = tmp_path / "out"
    code, _ = I.compile_all(tmp_path, REGISTRY_PATH, out, tmp_path / "INDEX.md")
    assert code == 0
    code, _ = W.compile_all(tmp_path, REGISTRY_PATH, tmp_path / "w.json", tmp_path / "s.json")
    assert code == 0
    assert _snapshot(targets) == before


def test_work_isolation():
    import re

    banned = (
        "socket", "urllib", "requests", "http.client", "subprocess",
        "RelayWriter", "sideCommand", "ActionBroker", "ConfirmationStore",
    )
    secrets = ("service.token", "cookies", "password")
    import_pattern = re.compile(r"^\s*(import|from)\s+kolmafa", re.MULTILINE)
    for name in ("__init__.py", "records.py", "validate.py", "build_index.py",
                 "build_matrix_overlay.py"):
        source = (INTEGRATION / "work" / name).read_text(encoding="utf-8")
        for token in banned + secrets:
            assert token not in source, f"{name} contains {token!r}"
        assert not import_pattern.search(source), f"{name} imports kolmafa"
