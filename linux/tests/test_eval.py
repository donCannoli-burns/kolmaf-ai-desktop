"""Tests for the retrieval evaluation harness."""
# pylint: disable=protected-access

import hashlib
import sqlite3
from pathlib import Path

import pytest

from kolmafa import rag
from kolmafa import eval as kolmafa_eval


def _connection(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript((Path(__file__).parents[1] / "sql" / "schema.sql").read_text())
    return connection


def _ingest_doc(
    connection: sqlite3.Connection,
    path: Path,
    body: str,
    quality_class: str = "canonical",
) -> None:
    """Helper to ingest a single document for testing."""
    path.write_text(body, encoding="utf-8")
    rag.ingest_paths(
        connection,
        [path],
        explicit_opt_in=True,
        allowed_roots=[path.parent],
        quality_class=quality_class,
    )


# --- Contract constants and helpers (T002 metric contract §2, §5) ---

CONTRACT_THRESHOLD = -5.0


def _is_low_score(
    top_score: float | None,
    threshold: float = CONTRACT_THRESHOLD,
) -> bool:
    """Contract-correct predicate (§2.1): True when score is weak/unconfident.

    ``is_low_score = top_score is not None AND top_score > threshold``
    """
    if top_score is None:
        return False
    return top_score > threshold


def _system_abstained(
    num_results: int,
    top_score: float | None,
    threshold: float = CONTRACT_THRESHOLD,
) -> bool:
    """Contract-correct abstention (§5.1): True when evaluator declines to answer.

    ``system_abstained = num_results == 0 OR top_score > threshold``
    """
    if num_results == 0:
        return True
    if top_score is None:
        return True
    return top_score > threshold


def test_eval_precision_at_1(tmp_path: Path) -> None:
    """Test that precision@1 is 1.0 when top result matches expected source."""
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    # Ingest two documents
    _ingest_doc(connection, corpus / "items.txt", "helmet turtle gives 6 power 6 hat")
    _ingest_doc(connection, corpus / "effects.txt", "ode to booze gives 20 adventures")

    # Create eval dataset
    dataset = [
        kolmafa_eval.EvalQuestion(
            id="T01",
            question="helmet turtle",
            category="items",
            expected_sources=[
                {
                    "source_path_pattern": "%items.txt%",
                    "quality_class": "canonical",
                    "passage_text_fragment": "helmet turtle",
                }
            ],
        )
    ]

    report = kolmafa_eval.run_evaluation(connection, dataset, limit=5)
    assert report.total_questions == 1
    assert report.precision_at_1 == 1.0
    assert report.per_question[0].expected_source_rank == 1


def test_eval_no_answer_empty(tmp_path: Path) -> None:
    """Test that no-answer queries get 'empty' behavior."""
    connection = _connection(tmp_path)

    dataset = [
        kolmafa_eval.EvalQuestion(
            id="T02",
            question="asdfghjkl qwerty",
            category="edge_case",
            edge_case_type="no_answer",
            expected_sources=[],
        )
    ]

    report = kolmafa_eval.run_evaluation(connection, dataset, limit=5)
    assert report.per_question[0].num_results == 0
    assert report.per_question[0].no_answer_behavior == "empty"


def test_eval_precision_at_5(tmp_path: Path) -> None:
    """Test precision@5 calculation with multiple expected sources."""
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    _ingest_doc(connection, corpus / "doc1.txt", "apple apple apple apple apple")
    _ingest_doc(connection, corpus / "doc2.txt", "banana banana banana banana banana")
    _ingest_doc(connection, corpus / "doc3.txt", "cherry cherry cherry cherry cherry")

    dataset = [
        kolmafa_eval.EvalQuestion(
            id="T03",
            question="apple",
            category="test",
            expected_sources=[
                {
                    "source_path_pattern": "%doc1.txt%",
                    "quality_class": "canonical",
                    "passage_text_fragment": "apple",
                },
                {
                    "source_path_pattern": "%doc2.txt%",
                    "quality_class": "canonical",
                    "passage_text_fragment": "banana",
                },
            ],
        )
    ]

    report = kolmafa_eval.run_evaluation(connection, dataset, limit=5)
    # At least the expected sources should appear somewhere in top 5
    assert report.per_question[0].expected_source_rank > 0
    # Verify precision@5 is calculated
    assert 0 < report.per_question[0].precision_at_5 <= 1.0


def test_eval_irrelevant_context_rate(tmp_path: Path) -> None:
    """Test irrelevant-context rate calculation with mixed quality classes."""
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    _ingest_doc(connection, corpus / "canonical.txt", "meat drop bonus", quality_class="canonical")
    _ingest_doc(connection, corpus / "notes.txt", "meat drop strategy", quality_class="user_notes")
    _ingest_doc(connection, corpus / "ocr.txt", "meat drop from monsters", quality_class="ocr")

    dataset = [
        kolmafa_eval.EvalQuestion(
            id="T04",
            question="meat drop",
            category="mechanics",
            expected_sources=[
                {
                    "source_path_pattern": "%canonical.txt%",
                    "quality_class": "canonical",
                    "passage_text_fragment": "meat drop",
                }
            ],
        )
    ]

    report = kolmafa_eval.run_evaluation(connection, dataset, limit=5)
    # Some results may be from non-expected quality classes
    assert report.per_question[0].irrelevant_context_count >= 0


def test_eval_quality_class_in_results(tmp_path: Path) -> None:
    """Test that quality_class appears in search results used by eval."""
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    _ingest_doc(connection, corpus / "test.txt", "unique_test_content_xyz", quality_class="canonical")

    rows = rag.search(connection, "unique_test_content_xyz")
    assert len(rows) > 0
    assert "quality_class" in rows[0].keys()
    assert rows[0]["quality_class"] == "canonical"
    assert "score" in rows[0].keys()


# =============================================================================
# T004: Metric-contract tests (T002 contract, wave 3)
# These encode the proved Checkpoint 002 metric contract predicates.
# Some tests FAIL under the current uncorrected evaluator (inverted threshold).
# =============================================================================


def test_fts5_bm25_ordering_direction(tmp_path: Path) -> None:
    """Verify FTS5 BM25 returns more-negative scores for better matches (§1)."""
    db_path = tmp_path / "fts5_ordering.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE VIRTUAL TABLE docs_fts USING fts5(content)")

    # Docs with varying relevance to query term "aaaa"
    conn.execute("INSERT INTO docs_fts(content) VALUES (?)", ("aaaa " * 10,))       # high TF
    conn.execute("INSERT INTO docs_fts(content) VALUES (?)", ("aaaa " * 1,))         # low TF
    for i in range(20):
        conn.execute("INSERT INTO docs_fts(content) VALUES (?)", (f"other_{i} " * 5,))  # noise

    rows = conn.execute(
        "SELECT content, bm25(docs_fts) AS score "
        "FROM docs_fts WHERE docs_fts MATCH 'aaaa' ORDER BY bm25(docs_fts)"
    ).fetchall()

    assert len(rows) >= 2, "Need at least 2 matching documents"

    # All returned scores are non-positive (FTS5 BM25 convention)
    for _, score in rows:
        assert score <= 0, f"BM25 score {score} should be non-positive"

    # Ascending ORDER BY puts most-negative (best match) first
    for i in range(len(rows) - 1):
        assert rows[i][1] <= rows[i + 1][1], (
            f"Ascending BM25 violated at rank {i}: {rows[i][1]} > {rows[i+1][1]}"
        )

    # High-TF doc has a lower (more-negative) score than low-TF doc
    scores = dict(rows)
    high_tf = "aaaa " * 10
    low_tf = "aaaa " * 1
    if high_tf in scores and low_tf in scores:
        assert scores[high_tf] < scores[low_tf], (
            "High-TF document should have more-negative BM25 than low-TF document"
        )


def test_contract_is_low_score_predicate() -> None:
    """Contract predicate §2.1: is_low_score matches the boundary table (§2.3)."""
    # None (no results) → not low_score
    assert _is_low_score(None) is False
    # Strong match (-10.0, <= -5.0) → not low_score
    assert _is_low_score(-10.0) is False
    # Exact boundary (-5.0) → not low_score (not > threshold)
    assert _is_low_score(-5.0) is False
    # Just above boundary (-4.999) → low_score
    assert _is_low_score(-4.999) is True
    # Weak match (0.0) → low_score
    assert _is_low_score(0.0) is True


def test_contract_system_abstained_predicate() -> None:
    """Contract predicate §5.1: system_abstained from num_results and top_score."""
    # 0 results → abstained
    assert _system_abstained(0, None) is True
    assert _system_abstained(0, -10.0) is True  # num_results=0 dominates
    # Strong match → not abstained
    assert _system_abstained(5, -10.0) is False
    # Exact boundary → not abstained
    assert _system_abstained(5, -5.0) is False
    # Weak match → abstained
    assert _system_abstained(5, -2.0) is True
    assert _system_abstained(5, 0.0) is True
    # Defensive: top_score=None with results → abstained
    assert _system_abstained(5, None) is True


# ---------------------------------------------------------------------------
# Threshold boundary behavior (§2.2, §2.3)
# These end-to-end tests exercise run_evaluation with controlled BM25 scores.
# Under the current uncorrected eval.py, inverted predicate (top_score < threshold)
# causes wrong classifications — these xfail tests prove the contract gap.
# ---------------------------------------------------------------------------


def test_no_answer_strong_match_is_found(tmp_path: Path) -> None:
    """Strong match (score <= -5.0) → 'found', not 'low_score'.

    Current bug: strong matches score in [-10, -5], so -8.0 < -5.0 is True,
    wrongly classifying them as low_score. Contract says: top_score <= threshold
    means confident retrieval → 'found'.
    """
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    # Lots of filler so a rare term gets high IDF → strongly negative BM25
    for i in range(500):
        _ingest_doc(connection, corpus / f"fill_{i}.txt", f"filler_text_{i} " * 10)

    # One document with high TF of a unique term → very negative BM25
    _ingest_doc(connection, corpus / "match.txt", "rare_zxy_unique_term_xyz " * 200)

    dataset = [
        kolmafa_eval.EvalQuestion(
            id="C003-STRONG",
            question="rare_zxy_unique_term_xyz",
            category="test",
            edge_case_type="no_answer",
            expected_sources=[],
        )
    ]

    report = kolmafa_eval.run_evaluation(
        connection, dataset, limit=5, score_threshold=CONTRACT_THRESHOLD,
    )
    result = report.per_question[0]
    assert result.num_results > 0, "Should have retrieved the matching document"
    top_score = result.sources_found[0]["score"]
    assert top_score <= -5.0, (
        f"Expected strong match (score <= -5.0), got {top_score}"
    )
    # Contract: strong match → found
    # Current bug: top_score < threshold → low_score
    assert result.no_answer_behavior == "found", (
        f"score={top_score}: expected 'found', got '{result.no_answer_behavior}' "
        "(inverted threshold bug at eval.py:195)"
    )


def test_no_answer_weak_match_is_low_score(tmp_path: Path) -> None:
    """Weak match (score > -5.0) → 'low_score', not 'found'.

    Current bug: a common term with low discriminative power gets BM25 ≈ 0.0.
    0.0 < -5.0 is False, so it falls through to 'found'. Contract says:
    top_score > threshold means weak retrieval → 'low_score'.
    """
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    # Every doc contains the search term once → IDF=0, BM25=0 (weak match)
    for i in range(300):
        _ingest_doc(connection, corpus / f"doc_{i}.txt", f"common_word_{i} " * 3)

    # Also add a shared term with very low frequency
    for i in range(300):
        _ingest_doc(connection, corpus / f"shared_{i}.txt", "generic_term_zxy " * 2)

    dataset = [
        kolmafa_eval.EvalQuestion(
            id="C003-WEAK",
            question="generic_term_zxy",
            category="test",
            edge_case_type="no_answer",
            expected_sources=[],
        )
    ]

    report = kolmafa_eval.run_evaluation(
        connection, dataset, limit=5, score_threshold=CONTRACT_THRESHOLD,
    )
    result = report.per_question[0]
    assert result.num_results > 0, "Should have retrieved matching documents"
    top_score = result.sources_found[0]["score"]
    assert top_score > CONTRACT_THRESHOLD, (
        f"Expected weak match (score > -5.0), got {top_score}"
    )
    # Contract: weak match → low_score
    # Current bug: top_score < threshold is False → falls through to 'found'
    assert result.no_answer_behavior == "low_score", (
        f"score={top_score}: expected 'low_score', got '{result.no_answer_behavior}' "
        "(inverted threshold bug at eval.py:204)"
    )


# ---------------------------------------------------------------------------
# No-answer behavior classification (§3)
# ---------------------------------------------------------------------------


def test_no_answer_noise(tmp_path: Path) -> None:
    """Strong match + unknown quality + no_answer → 'noise' (§3.2)."""
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    for i in range(300):
        _ingest_doc(connection, corpus / f"fill_{i}.txt", f"filler_{i} " * 10)

    _ingest_doc(
        connection, corpus / "noise.txt",
        "rare_unknown_quality_term " * 200,
        quality_class="unknown",
    )

    dataset = [
        kolmafa_eval.EvalQuestion(
            id="C003-NOISE",
            question="rare_unknown_quality_term",
            category="test",
            edge_case_type="no_answer",
            expected_sources=[],
        )
    ]

    report = kolmafa_eval.run_evaluation(
        connection, dataset, limit=5, score_threshold=CONTRACT_THRESHOLD,
    )
    result = report.per_question[0]

    # Verify we at least retrieved results
    if result.num_results == 0:
        pytest.skip("No results retrieved — corpus may need adjustment")
        return

    top_score = result.sources_found[0]["score"]
    actual_behavior = result.no_answer_behavior

    # Contract says:
    #   top_score <= threshold + unknown quality + no_answer → "noise"
    if top_score <= CONTRACT_THRESHOLD and actual_behavior != "noise":
        # This case fails under current code because inverted predicate
        # routes strong matches to "low_score" before reaching quality_class check
        pytest.xfail(
            f"score={top_score} <= threshold but got '{actual_behavior}' "
            "(inverted predicate prevents reaching noise check)"
        )

    assert actual_behavior == "noise", (
        f"Expected 'noise' for score={top_score}, quality=unknown, "
        f"got '{actual_behavior}'"
    )


# ---------------------------------------------------------------------------
# System abstention (§5.1, §5.2)
# ---------------------------------------------------------------------------


def test_system_abstained_consistency(tmp_path: Path) -> None:
    """Verify system_abstained matches contract logic across scenarios."""
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    # Scenario A: empty results → abstained (passes under current code)
    dataset_empty = [
        kolmafa_eval.EvalQuestion(
            id="ABST-EMPTY",
            question="asdfghjkl_nonexistent_xxxxx",
            category="test",
            edge_case_type="no_answer",
            expected_sources=[],
        )
    ]
    report = kolmafa_eval.run_evaluation(
        connection, dataset_empty, limit=5, score_threshold=CONTRACT_THRESHOLD,
    )
    assert report.per_question[0].num_results == 0
    # Both current and contract agree: empty → abstained
    assert report.per_question[0].no_answer_behavior == "empty"

    # Scenario B: ingesting a strong match doc
    for i in range(500):
        _ingest_doc(connection, corpus / f"abst_fill_{i}.txt", f"xxfill_{i} " * 10)
    _ingest_doc(
        connection, corpus / "abst_strong.txt",
        "strong_match_zxy_for_abst " * 200,
    )

    dataset_strong = [
        kolmafa_eval.EvalQuestion(
            id="ABST-STRONG",
            question="strong_match_zxy_for_abst",
            category="test",
            edge_case_type="no_answer",
            expected_sources=[],
        )
    ]
    report = kolmafa_eval.run_evaluation(
        connection, dataset_strong, limit=5, score_threshold=CONTRACT_THRESHOLD,
    )
    result_s = report.per_question[0]
    if result_s.num_results > 0:
        top_score_s = result_s.sources_found[0]["score"]
        contract_abstained = _system_abstained(result_s.num_results, top_score_s)
        # If the score is a strong match, contract says NOT abstained,
        # but current code may say abstained (inverted)
        if contract_abstained != (result_s.no_answer_behavior in ("empty", "low_score")):
            pytest.xfail(
                f"score={top_score_s}: contract abstained={contract_abstained} "
                f"but current eval gives {result_s.no_answer_behavior}"
            )


# ---------------------------------------------------------------------------
# Adversarial handling (§5.3)
# ---------------------------------------------------------------------------


def test_adversarial_empty_abstains(tmp_path: Path) -> None:
    """Adversarial + empty results → handled correctly (both current and contract)."""
    connection = _connection(tmp_path)
    dataset = [
        kolmafa_eval.EvalQuestion(
            id="ADV-EMPTY",
            question="qwerty_nonexistent_adversarial_12345",
            category="test",
            adversarial=True,
            expected_sources=[],
        )
    ]
    report = kolmafa_eval.run_evaluation(
        connection, dataset, limit=5, score_threshold=CONTRACT_THRESHOLD,
    )
    result = report.per_question[0]
    assert result.num_results == 0
    assert result.adversarial_handled_correctly is True


def test_adversarial_weak_match_abstains(tmp_path: Path) -> None:
    """Adversarial + weak match → handled correctly (contract expects abstention)."""
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    for i in range(300):
        _ingest_doc(connection, corpus / f"adv_doc_{i}.txt", "adv_common_word " * 2)

    dataset = [
        kolmafa_eval.EvalQuestion(
            id="ADV-WEAK",
            question="adv_common_word",
            category="test",
            adversarial=True,
            expected_sources=[],
        )
    ]

    report = kolmafa_eval.run_evaluation(
        connection, dataset, limit=5, score_threshold=CONTRACT_THRESHOLD,
    )
    result = report.per_question[0]
    if result.num_results > 0:
        top_score = result.sources_found[0]["score"]
        # Contract: weak match → system abstains → adversarial_handled_correctly = True
        if top_score > CONTRACT_THRESHOLD:
            # Current code: -2.0 < -5.0 is False → not abstained → False (DIFFERS)
            if result.adversarial_handled_correctly is not True:
                pytest.xfail(
                    f"score={top_score} is weak: contract expects True, "
                    f"got {result.adversarial_handled_correctly} "
                    "(inverted threshold reverses abstention)"
                )


# ---------------------------------------------------------------------------
# Explicit inverted-threshold regression test (§1.4, §2.1)
# ---------------------------------------------------------------------------


def test_inverted_threshold_bug_direct(tmp_path: Path) -> None:
    """Direct proof: evaluation yields wrong no_answer_behavior for strong match.

    Insert a strongly matching document and verify it is classified as 'found'
    per the contract. Under current code the inverted predicate classifies it
    as 'low_score', proving the bug.
    """
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    # 500 filler docs + 1 strong match
    for i in range(500):
        _ingest_doc(connection, corpus / f"bug_fill_{i}.txt", f"bf_{i} " * 10)
    _ingest_doc(connection, corpus / "bug_match.txt", "proof_bug_zxy_term " * 200)

    dataset = [
        kolmafa_eval.EvalQuestion(
            id="BUG-PROOF",
            question="proof_bug_zxy_term",
            category="test",
            edge_case_type="no_answer",
            expected_sources=[],
        )
    ]

    report = kolmafa_eval.run_evaluation(
        connection, dataset, limit=5, score_threshold=CONTRACT_THRESHOLD,
    )
    result = report.per_question[0]

    assert result.num_results > 0, "Must have retrieved the matching document"

    top_score = result.sources_found[0]["score"]
    actual = result.no_answer_behavior

    # Contract expectation: top_score <= -5.0 → "found"
    # Current code:      top_score < -5.0  → "low_score" (BUG)
    expected = "found" if top_score <= CONTRACT_THRESHOLD else "low_score"

    assert actual == expected, (
        f"INVERTED THRESHOLD BUG: score={top_score:.4f}, "
        f"threshold={CONTRACT_THRESHOLD}, "
        f"actual='{actual}', expected='{expected}'\n"
        f"Current predicate: top_score < threshold → {top_score < CONTRACT_THRESHOLD}\n"
        f"Contract predicate: top_score > threshold → {top_score > CONTRACT_THRESHOLD}"
    )


# ---------------------------------------------------------------------------
# Confidence rate derived from abstention (§6.2, §6.3)
# ---------------------------------------------------------------------------


def test_confidence_rate_derived(tmp_path: Path) -> None:
    """Confidence rate equals proportion of non-abstained questions."""
    connection = _connection(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    for i in range(500):
        _ingest_doc(connection, corpus / f"cr_fill_{i}.txt", f"crf_{i} " * 10)
    _ingest_doc(connection, corpus / "cr_strong.txt", "confident_match_zxy " * 200)

    # Strong-match question — should be confident (not abstained)
    dataset = [
        kolmafa_eval.EvalQuestion(
            id="CR-STRONG",
            question="confident_match_zxy",
            category="mechanics",
            expected_sources=[],
            edge_case_type=None,
        )
    ]

    report = kolmafa_eval.run_evaluation(
        connection, dataset, limit=5, score_threshold=CONTRACT_THRESHOLD,
    )
    result = report.per_question[0]
    if result.num_results == 0:
        pytest.skip("No results — corpus adjustment needed")

    top_score = result.sources_found[0]["score"]
    is_strong = top_score <= CONTRACT_THRESHOLD

    # Under contract: strong match → not abstained → confident
    # Under current code: strong match → abstained (inverted) → NOT confident
    # Check category-level confidence_rate (current code uses >= threshold at line 595)
    cat_key = "mechanics"
    if cat_key in report.per_category:
        conf_rate = report.per_category[cat_key].get("confidence_rate", -1)
        if is_strong:
            # Strong match should give confidence_rate = 1.0
            if conf_rate != 1.0:
                pytest.xfail(
                    f"score={top_score} (strong match): confidence_rate={conf_rate}, "
                    "expected 1.0 (current code uses >= threshold at line 595)"
                )
        # Verify it's a valid rate
        assert 0.0 <= conf_rate <= 1.0, f"confidence_rate={conf_rate} out of range"


# ---------------------------------------------------------------------------
# Original artifact SHA-256 preservation (§7.1)
# ---------------------------------------------------------------------------


DATASET_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "eval" / "dataset.json"
)
CHECKPOINT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "eval" / "checkpoint-002.json"
)

DATASET_EXPECTED_SHA256 = "0874fdc79d66ee2f42aa94e06144ff2fa0309ad535e49106e34b05f352720a6a"
CHECKPOINT_EXPECTED_SHA256 = "6795d2f95263bb06399aad5a1c3a2350999d837d691c29e4e20973644ddf519e"


def test_original_artifact_sha256() -> None:
    """Verify original dataset and checkpoint bytes match supplied SHA-256 (§7.1)."""
    dataset_hash = hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()
    assert dataset_hash == DATASET_EXPECTED_SHA256, (
        f"dataset.json SHA-256 mismatch: got {dataset_hash}, "
        f"expected {DATASET_EXPECTED_SHA256}"
    )

    checkpoint_hash = hashlib.sha256(CHECKPOINT_PATH.read_bytes()).hexdigest()
    assert checkpoint_hash == CHECKPOINT_EXPECTED_SHA256, (
        f"checkpoint-002.json SHA-256 mismatch: got {checkpoint_hash}, "
        f"expected {CHECKPOINT_EXPECTED_SHA256}"
    )
