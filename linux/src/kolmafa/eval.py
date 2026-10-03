"""Retrieval evaluation harness for the local FTS5 RAG knowledge base."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field, asdict
import statistics
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid
from typing import Any


@dataclass
class EvalQuestion:
    """A canonical evaluation question with expected sources."""

    id: str
    question: str
    category: str
    edge_case_type: str | None = None
    expected_source_mode: str | None = None  # "single" | "any" | "all" | "none"
    expected_sources: list[dict[str, str]] = field(default_factory=list)
    required_sources: list[dict[str, str]] = field(default_factory=list)
    acceptable_sources: list[dict[str, str]] = field(default_factory=list)
    expected_quality_classes: list[str] = field(default_factory=list)
    expected_abstention: bool = False
    conflict_expected: bool = False
    action_sensitive: bool = False
    adversarial: bool = False
    notes: str = ""


@dataclass
class PerQuestionResult:
    """Metrics for a single evaluation question."""

    id: str
    question: str
    category: str
    edge_case_type: str | None
    num_results: int
    precision_at_1: float
    precision_at_5: float
    expected_source_rank: int  # 1-indexed position of first expected source, or -1
    irrelevant_context_count: int
    no_answer_behavior: str  # 'empty' | 'low_score' | 'noise' | 'found'
    sources_found: list[dict[str, Any]]
    mrr: float = 0.0  # reciprocal rank of first expected source
    recall_at_5: float = 0.0
    expected_source_rank_distribution: list[int] = field(default_factory=list)  # ranks 1-5+
    score_margin: float | None = None  # BM25 score gap rank-1 vs rank-2
    abstention_correct: bool | None = None
    abstention_expected: bool | None = None
    conflict_detected: bool = False
    conflict_details: dict | None = None
    no_answer_category: str | None = None
    adversarial_handled_correctly: bool | None = None
    expected_quality_classes: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class EvalReport:
    """Aggregate evaluation report."""

    run_id: str
    timestamp: str
    total_questions: int
    precision_at_1: float
    precision_at_5: float
    irrelevant_context_rate: float
    no_answer_counts: dict[str, int]
    per_category: dict[str, dict[str, float]]
    per_question: list[PerQuestionResult]
    per_quality_class: dict[str, dict[str, float | int]]
    mrr: float = 0.0
    mrr_by_category: dict[str, float] = field(default_factory=dict)
    mrr_by_quality_class: dict[str, float] = field(default_factory=dict)
    recall_at_5: float = 0.0
    recall_at_5_by_category: dict[str, float] = field(default_factory=dict)
    recall_at_5_by_quality_class: dict[str, float] = field(default_factory=dict)
    expected_source_rank_distribution: dict[str, int] = field(default_factory=dict)
    score_margin_stats: dict = field(default_factory=dict)
    score_margin_distribution: list[float] = field(default_factory=list)
    abstention_precision: float = 0.0
    abstention_recall: float = 0.0
    unsafe_non_abstentions: int = 0
    correct_abstentions: int = 0
    incorrect_abstentions: int = 0
    adversarial_metrics: dict = field(default_factory=dict)
    conflict_metrics: dict = field(default_factory=dict)
    no_answer_category_counts: dict[str, int] = field(default_factory=dict)


def load_dataset(path: Path) -> list[EvalQuestion]:
    """Load evaluation questions from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [EvalQuestion(**q) for q in data]


def run_evaluation(
    connection: sqlite3.Connection,
    dataset: list[EvalQuestion],
    limit: int = 10,
    score_threshold: float = 0.0,
) -> EvalReport:
    """Run retrieval evaluation against a dataset.

    Args:
        connection: SQLite connection to the RAG database.
        dataset: List of evaluation questions.
        limit: Number of search results to retrieve per question.
        score_threshold: BM25 score threshold for 'low_score' detection.
            FTS5 BM25 returns non-positive values; more-negative = better match.
            A threshold of -5.0 means anything above -5.0 (less negative) is
            a low-score result.
    """
    from kolmafa import rag

    per_question: list[PerQuestionResult] = []

    for q in dataset:
        # Search - convert sqlite3.Row objects to dicts for safe access
        results = [dict(row) for row in rag.search(connection, q.question, limit=limit)]

        expected_paths = [src["source_path_pattern"] for src in q.expected_sources]
        expected_quality = set(src["quality_class"] for src in q.expected_sources)

        # Compute metrics
        num_results = len(results)

        if num_results == 0:
            precision_at_1 = 0.0
            precision_at_5 = 0.0
            expected_source_rank = -1
            irrelevant_context_count = 0
            no_answer_behavior = "empty"
        else:
            # Check how many top results match expected sources
            matched_at_1 = 0
            if num_results >= 1:
                for exp_path in expected_paths:
                    pattern = exp_path.replace("%", "")
                    if pattern in str(results[0]["source_path"]) or any(
                        pattern in str(results[0][k])
                        for k in ("source_path", "title", "source_label")
                    ):
                        matched_at_1 = 1
                        break

            matches_at_5 = 0
            for i, row in enumerate(results[:5]):
                for exp_path in expected_paths:
                    pattern = exp_path.replace("%", "")
                    if pattern in str(row["source_path"]) or pattern in str(
                        row.get("title", "")
                    ) or pattern in str(row.get("source_label", "")):
                        matches_at_5 += 1
                        break

            precision_at_1 = float(matched_at_1)
            precision_at_5 = matches_at_5 / min(5, num_results)

            # Rank of first expected source
            expected_source_rank = -1
            for i, row in enumerate(results):
                for exp_path in expected_paths:
                    pattern = exp_path.replace("%", "")
                    if pattern in str(row["source_path"]) or pattern in str(
                        row.get("title", "")
                    ) or pattern in str(row.get("source_label", "")):
                        expected_source_rank = i + 1
                        break
                if expected_source_rank > 0:
                    break

            # Irrelevant context: results whose quality_class is not in expected set
            if expected_quality:
                irrelevant_context_count = sum(
                    1
                    for row in results
                    if row.get("quality_class", "unknown") not in expected_quality
                )
            else:
                irrelevant_context_count = 0  # For no-answer questions, this doesn't apply

            # No-answer behavior
            top_score = results[0].get("score", 0) if results else 0
            if q.edge_case_type == "no_answer":
                if num_results == 0:
                    no_answer_behavior = "empty"
                elif top_score > score_threshold:
                    no_answer_behavior = "low_score"
                elif results[0].get("quality_class", "") == "unknown":
                    no_answer_behavior = "noise"
                else:
                    no_answer_behavior = "found"
            else:
                if num_results == 0:
                    no_answer_behavior = "empty"
                elif top_score > score_threshold:
                    no_answer_behavior = "low_score"
                else:
                    no_answer_behavior = "found"

        # --- MRR (Mean Reciprocal Rank) ---
        mrr = 0.0
        if q.expected_sources and expected_source_rank > 0:
            mrr = 1.0 / expected_source_rank

        # --- Expected-Source Rank Distribution (all found expected sources) ---
        source_ranks: list[int] = []
        for src in q.expected_sources:
            pattern = src["source_path_pattern"].replace("%", "")
            for idx, row in enumerate(results):
                if pattern in str(row["source_path"]) or pattern in str(row.get("title", "")):
                    source_ranks.append(idx + 1)
                    break

        # --- Recall@5 ---
        recall_at_5 = 0.0
        mode = q.expected_source_mode
        if mode == "single" or (not mode and q.expected_sources):
            # Single expected source — binary: 1 if ANY expected source in top-5
            recall_at_5 = 1.0 if any(
                src["source_path_pattern"].replace("%", "") in str(r["source_path"])
                or src["source_path_pattern"].replace("%", "") in str(r.get("title", ""))
                for r in results[:5]
                for src in q.expected_sources
            ) else 0.0
        elif mode == "any":
            # Any acceptable/required source — binary
            all_sources = q.expected_sources + q.acceptable_sources + q.required_sources
            recall_at_5 = 1.0 if any(
                src["source_path_pattern"].replace("%", "") in str(r["source_path"])
                or src["source_path_pattern"].replace("%", "") in str(r.get("title", ""))
                for r in results[:5]
                for src in all_sources
            ) else 0.0
        elif mode == "all":
            # All required sources — fraction matched / total
            required_paths = [s["source_path_pattern"] for s in q.required_sources]
            if required_paths:
                matched = sum(
                    1
                    for p in required_paths
                    if any(p.replace("%", "") in str(r["source_path"]) for r in results[:5])
                )
                recall_at_5 = matched / len(required_paths)
        elif mode == "none":
            # Expect abstention — recall = 1.0 if NO irrelevant sources in top-5
            all_irrelevant = q.expected_sources + q.required_sources + q.acceptable_sources
            has_irrelevant = any(
                src["source_path_pattern"].replace("%", "") in str(r["source_path"])
                or src["source_path_pattern"].replace("%", "") in str(r.get("title", ""))
                for r in results[:5]
                for src in all_irrelevant
            )
            recall_at_5 = 0.0 if has_irrelevant else 1.0
        # else: mode unset and no expected_sources — defaults to 0.0

        # --- Score-Margin Distribution ---
        # BM25 direction (empirically confirmed): more-negative = BETTER match.
        # ORDER BY bm25(documents_fts) ASC puts most negative (best) first.
        # score_margin = rank_2_score - rank_1_score: positive = rank-1 clearly better.
        score_margin: float | None = None
        if num_results >= 2:
            score_margin = results[1]["score"] - results[0]["score"]

        # --- Canonical-vs-Legacy Conflict Detection (T8) ---
        conflict_detected = False
        conflict_details = None
        canonical_results = [r for r in results[:5] if r.get("quality_class") == "canonical"]
        legacy_results = [r for r in results[:5] if r.get("quality_class") == "legacy"]
        if canonical_results and legacy_results:
            conflict_detected = True
            if q.conflict_expected:
                resolution = "unresolved"
                if len(canonical_results) >= len(legacy_results) * 2:
                    resolution = "resolved_by_canonical"
                elif not q.notes or "contradict" not in q.notes.lower():
                    resolution = "non_contradictory"
                conflict_details = {
                    "type": "known_conflict",
                    "resolution": resolution,
                    "canonical_count": len(canonical_results),
                    "legacy_count": len(legacy_results),
                    "canonical_sources": [r["source_path"] for r in canonical_results[:2]],
                    "legacy_sources": [r["source_path"] for r in legacy_results[:2]],
                }
            else:
                conflict_details = {
                    "type": "unexpected_conflict",
                    "resolution": "unresolved",
                    "canonical_count": len(canonical_results),
                    "legacy_count": len(legacy_results),
                }

        # --- Abstention Classification (T10) ---
        if q.expected_abstention is not None:
            abstention_expected = q.expected_abstention
        elif q.edge_case_type == "no_answer":
            abstention_expected = True
        elif q.edge_case_type == "ambiguous":
            abstention_expected = False
        else:
            abstention_expected = False

        system_abstained = num_results == 0 or (
            results and results[0].get("score", 0) > score_threshold
        )
        if abstention_expected and system_abstained:
            abstention_correct = True
        elif not abstention_expected and system_abstained:
            abstention_correct = False
        elif abstention_expected and not system_abstained:
            abstention_correct = False
        else:
            abstention_correct = None

        # --- No-answer category classification (T4) ---
        no_answer_category = None
        if q.edge_case_type == "no_answer" and q.notes:
            for _cat in (
                "pure_nonsense", "meaningless_request", "undocumented_behavior",
                "low_quality_only", "conflicting_sources", "outside_corpus",
                "descriptive_not_permissive",
            ):
                if _cat in q.notes.lower():
                    no_answer_category = _cat
                    break

        # --- Adversarial Scoring (T11) ---
        adversarial_handled_correctly = None
        if q.adversarial:
            if num_results == 0 or (results and results[0].get("score", 0) > score_threshold):
                adversarial_handled_correctly = True
            else:
                adversarial_handled_correctly = False

        # Build sources_found
        sources_found = []
        for row in results:
            sources_found.append(
                {
                    "rank": len(sources_found) + 1,
                    "title": row.get("title", ""),
                    "source_path": row.get("source_path", ""),
                    "quality_class": row.get("quality_class", "unknown"),
                    "score": row.get("score", 0),
                    "snippet": row.get("snippet", ""),
                }
            )

        per_question.append(
            PerQuestionResult(
                id=q.id,
                question=q.question,
                category=q.category,
                edge_case_type=q.edge_case_type,
                num_results=num_results,
                precision_at_1=precision_at_1,
                precision_at_5=precision_at_5,
                expected_source_rank=expected_source_rank,
                irrelevant_context_count=irrelevant_context_count,
                no_answer_behavior=no_answer_behavior,
                sources_found=sources_found,
                mrr=mrr,
                recall_at_5=recall_at_5,
                expected_source_rank_distribution=source_ranks,
                score_margin=score_margin,
                conflict_detected=conflict_detected,
                conflict_details=conflict_details,
                abstention_correct=abstention_correct,
                abstention_expected=abstention_expected,
                no_answer_category=no_answer_category,
                adversarial_handled_correctly=adversarial_handled_correctly,
                expected_quality_classes=q.expected_quality_classes,
                notes=q.notes,
            )
        )

    # Aggregate metrics
    total = len(per_question)
    avg_p1 = sum(q.precision_at_1 for q in per_question) / total if total else 0.0
    avg_p5 = sum(q.precision_at_5 for q in per_question) / total if total else 0.0

    # Irrelevant context rate: total irrelevant results / total results across all questions
    total_results = sum(q.num_results for q in per_question)
    total_irrelevant = sum(q.irrelevant_context_count for q in per_question)
    irr_rate = total_irrelevant / total_results if total_results else 0.0

    # No-answer behavior counts
    no_answer_counts = {
        "empty": sum(1 for q in per_question if q.no_answer_behavior == "empty"),
        "low_score": sum(1 for q in per_question if q.no_answer_behavior == "low_score"),
        "noise": sum(1 for q in per_question if q.no_answer_behavior == "noise"),
        "found": sum(1 for q in per_question if q.no_answer_behavior == "found"),
    }

    # Per-category breakdown
    categories: dict[str, dict[str, float]] = {}
    for q in per_question:
        cat = q.category
        if cat not in categories:
            categories[cat] = {"count": 0, "sum_p1": 0.0, "sum_p5": 0.0}
        categories[cat]["count"] += 1
        categories[cat]["sum_p1"] += q.precision_at_1
        categories[cat]["sum_p5"] += q.precision_at_5

    per_category = {}
    for cat, data in categories.items():
        per_category[cat] = {
            "count": int(data["count"]),
            "avg_precision_at_1": data["sum_p1"] / data["count"],
            "avg_precision_at_5": data["sum_p5"] / data["count"],
        }

    # Per-quality-class breakdown
    qc_counts: dict[str, Counter] = {}
    for q in per_question:
        for src in q.sources_found:
            qc = src["quality_class"]
            if qc not in qc_counts:
                qc_counts[qc] = Counter()
            qc_counts[qc]["total"] += 1
            if src["rank"] == 1:
                qc_counts[qc]["top1"] += 1

    per_quality_class = {}
    for qc, cnt in qc_counts.items():
        per_quality_class[qc] = {
            "total_results": cnt["total"],
            "top1_results": cnt["top1"],
        }

    # --- MRR aggregates ---
    all_mrr = [q.mrr for q in per_question]
    mean_mrr = sum(all_mrr) / total if total else 0.0

    # Per-category MRR
    mrr_by_cat: dict[str, dict[str, float]] = {}
    for q in per_question:
        cat = q.category
        if cat not in mrr_by_cat:
            mrr_by_cat[cat] = {"sum": 0.0, "count": 0}
        mrr_by_cat[cat]["sum"] += q.mrr
        mrr_by_cat[cat]["count"] += 1
    mrr_by_category_result = {
        cat: d["sum"] / d["count"] if d["count"] else 0.0
        for cat, d in mrr_by_cat.items()
    }

    # Per-quality-class MRR
    mrr_by_qc: dict[str, dict[str, float]] = {}
    for q in per_question:
        for qc in q.expected_quality_classes:
            if qc not in mrr_by_qc:
                mrr_by_qc[qc] = {"sum": 0.0, "count": 0}
            mrr_by_qc[qc]["sum"] += q.mrr
            mrr_by_qc[qc]["count"] += 1
    mrr_by_quality_class_result = {
        qc: d["sum"] / d["count"] if d["count"] else 0.0
        for qc, d in mrr_by_qc.items()
    }

    # --- Expected-Source Rank Distribution (aggregate over first expected source) ---
    rank_dist: dict[str, int] = {
        "rank_1": 0, "rank_2": 0, "rank_3": 0,
        "rank_4": 0, "rank_5": 0, "rank_5_plus": 0, "not_found": 0,
    }
    for q in per_question:
        rank = q.expected_source_rank
        if rank == -1:
            rank_dist["not_found"] += 1
        elif rank <= 5:
            rank_dist[f"rank_{rank}"] += 1
        else:
            rank_dist["rank_5_plus"] += 1

    # --- Recall@5 aggregates ---
    all_recall5 = [q.recall_at_5 for q in per_question]
    mean_recall_at_5 = sum(all_recall5) / total if total else 0.0

    # Per-category recall@5
    recall5_by_cat: dict[str, dict[str, float]] = {}
    for q in per_question:
        cat = q.category
        if cat not in recall5_by_cat:
            recall5_by_cat[cat] = {"sum": 0.0, "count": 0}
        recall5_by_cat[cat]["sum"] += q.recall_at_5
        recall5_by_cat[cat]["count"] += 1
    recall5_by_category_result = {
        cat: d["sum"] / d["count"] if d["count"] else 0.0
        for cat, d in recall5_by_cat.items()
    }

    # Per-quality-class recall@5
    recall5_by_qc: dict[str, dict[str, float]] = {}
    for q in per_question:
        for qc in q.expected_quality_classes:
            if qc not in recall5_by_qc:
                recall5_by_qc[qc] = {"sum": 0.0, "count": 0}
            recall5_by_qc[qc]["sum"] += q.recall_at_5
            recall5_by_qc[qc]["count"] += 1
    recall5_by_quality_class_result = {
        qc: d["sum"] / d["count"] if d["count"] else 0.0
        for qc, d in recall5_by_qc.items()
    }

    # --- Score-Margin Distribution ---
    margins = [q.score_margin for q in per_question if q.score_margin is not None]
    if margins:
        sorted_margins = sorted(margins)
        n = len(sorted_margins)
        score_margin_stats_result = {
            "mean": sum(margins) / n,
            "median": statistics.median(sorted_margins),
            "p25": sorted_margins[int(n * 0.25)],
            "p75": sorted_margins[int(n * 0.75)],
            "p90": sorted_margins[int(n * 0.90)],
            "p99": sorted_margins[int(n * 0.99)],
            "count": n,
            "min": sorted_margins[0],
            "max": sorted_margins[-1],
        }
        score_margin_distribution_result = sorted_margins
    else:
        score_margin_stats_result = {"mean": 0.0, "count": 0}
        score_margin_distribution_result = []

    # --- Expanded Per-Quality-Class Reporting (T9) ---
    per_quality_class_expanded = {}
    all_quality_classes = [
        "canonical", "legacy", "user_notes", "ocr",
        "compiled", "generated", "unknown",
    ]
    for qc_name in all_quality_classes:
        questions_expecting = [q for q in per_question if qc_name in q.expected_quality_classes]
        qc_results = [
            src for q in per_question for src in q.sources_found
            if src["quality_class"] == qc_name
        ]
        top1_count = sum(
            1 for q in per_question
            if any(src["quality_class"] == qc_name and src["rank"] == 1 for src in q.sources_found)
        )
        top5_count = sum(
            1 for q in per_question
            if any(src["quality_class"] == qc_name and src["rank"] <= 5 for src in q.sources_found)
        )
        with_abstention = [q for q in questions_expecting if q.abstention_expected]
        correct_abstentions_qc = sum(1 for q in with_abstention if q.abstention_correct is True)

        n_expect = len(questions_expecting)
        recall_vals = [q.recall_at_5 for q in questions_expecting if q.recall_at_5 is not None]
        total_results_expecting = sum(q.num_results for q in questions_expecting)
        per_quality_class_expanded[qc_name] = {
            "total_questions": n_expect,
            "total_results": len(qc_results),
            "top1_results": top1_count,
            "top5_results": top5_count,
            "precision_at_1": (
                sum(q.precision_at_1 for q in questions_expecting) / n_expect if n_expect else 0.0
            ),
            "precision_at_5": (
                sum(q.precision_at_5 for q in questions_expecting) / n_expect if n_expect else 0.0
            ),
            "recall_at_5": (
                sum(recall_vals) / len(recall_vals) if recall_vals else 0.0
            ),
            "mrr": sum(q.mrr for q in questions_expecting) / n_expect if n_expect else 0.0,
            "irrelevant_context_rate": (
                sum(q.irrelevant_context_count for q in questions_expecting) / total_results_expecting
                if total_results_expecting else 0.0
            ),
            "abstention_count": len(with_abstention),
            "abstention_correct_rate": (
                correct_abstentions_qc / len(with_abstention) if with_abstention else 0.0
            ),
        }

    # --- Expanded Per-Category Reporting (T9) ---
    per_category_expanded = {}
    for cat, data in categories.items():
        cat_questions = [q for q in per_question if q.category == cat]
        cat_pairs = [(dq, q) for dq, q in zip(dataset, per_question) if q.category == cat]
        adv_count = sum(1 for dq, _ in cat_pairs if dq.adversarial)
        conflict_count = sum(1 for dq, _ in cat_pairs if dq.conflict_expected)
        abstain_count = sum(1 for _, q in cat_pairs if q.abstention_expected)
        conf_rate = (
            sum(1 for _, q in cat_pairs if q.no_answer_behavior not in ("empty", "low_score"))
            / len(cat_pairs)
            if cat_pairs else 0.0
        )
        recall_vals = [q.recall_at_5 for q in cat_questions if q.recall_at_5 is not None]
        per_category_expanded[cat] = {
            "count": int(data["count"]),
            "avg_precision_at_1": data["sum_p1"] / data["count"],
            "avg_precision_at_5": data["sum_p5"] / data["count"],
            "mrr": sum(q.mrr for q in cat_questions) / len(cat_questions) if cat_questions else 0.0,
            "recall_at_5": sum(recall_vals) / len(recall_vals) if recall_vals else 0.0,
            "confidence_rate": conf_rate,
            "abstention_rate": abstain_count / len(cat_pairs) if cat_pairs else 0.0,
            "adversarial_count": adv_count,
            "conflict_count": conflict_count,
        }

    # --- Abstention Precision/Recall (T10) ---
    correct_abstentions = sum(1 for q in per_question if q.abstention_correct is True)
    incorrect_abstentions = sum(1 for q in per_question if q.abstention_correct is False)
    unsafe_non_abstentions = sum(
        1 for q in per_question if q.abstention_expected is True and q.abstention_correct is False
    )
    total_needing_abstention = sum(1 for q in per_question if q.abstention_expected is True)
    system_abstained_count = sum(
        1 for q in per_question if q.no_answer_behavior in ("empty", "low_score")
    )
    abstention_precision = (
        correct_abstentions / system_abstained_count if system_abstained_count else 0.0
    )
    abstention_recall = (
        correct_abstentions / total_needing_abstention if total_needing_abstention else 0.0
    )

    # --- Adversarial Metrics (T11) ---
    adversarial_pairs = [(dq, q) for dq, q in zip(dataset, per_question) if dq.adversarial]
    total_adv = len(adversarial_pairs)
    correct_adv = sum(1 for _, q in adversarial_pairs if q.adversarial_handled_correctly is True)
    false_conf = sum(1 for _, q in adversarial_pairs if q.adversarial_handled_correctly is False)
    adversarial_metrics_result = {
        "total_adversarial_questions": total_adv,
        "correct_abstention_rate": correct_adv / total_adv if total_adv else 0.0,
        "false_confidence_rate": false_conf / total_adv if total_adv else 0.0,
        "per_question": [
            {"id": dq.id, "question": dq.question[:60], "handled_correctly": q.adversarial_handled_correctly}
            for dq, q in adversarial_pairs
        ],
    }

    # --- Conflict Metrics (T8) ---
    conflict_qs = [q for q in per_question if q.conflict_detected]
    total_conflicts = len(conflict_qs)
    unresolved = sum(
        1 for q in conflict_qs
        if q.conflict_details and q.conflict_details.get("resolution") == "unresolved"
    )
    resolved = sum(
        1 for q in conflict_qs
        if q.conflict_details and q.conflict_details.get("resolution")
        in ("resolved_by_canonical", "non_contradictory", "insufficient_evidence")
    )
    unexpected = sum(
        1 for q in conflict_qs
        if q.conflict_details and q.conflict_details.get("type") == "unexpected_conflict"
    )
    conflict_metrics_result = {
        "total_conflict_questions": total_conflicts,
        "unresolved_conflicts": unresolved,
        "properly_resolved": resolved,
        "unexpected_conflicts": unexpected,
    }

    # --- No-answer Category Counts (T4) ---
    no_answer_category_counts_result = dict(
        Counter(q.no_answer_category for q in per_question if q.no_answer_category)
    )

    return EvalReport(
        run_id=f"eval-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_questions=total,
        precision_at_1=round(avg_p1, 4),
        precision_at_5=round(avg_p5, 4),
        irrelevant_context_rate=round(irr_rate, 4),
        no_answer_counts=no_answer_counts,
        per_category=per_category_expanded,
        per_question=per_question,
        per_quality_class=per_quality_class_expanded,
        mrr=round(mean_mrr, 4),
        mrr_by_category=mrr_by_category_result,
        mrr_by_quality_class=mrr_by_quality_class_result,
        recall_at_5=round(mean_recall_at_5, 4),
        recall_at_5_by_category=recall5_by_category_result,
        recall_at_5_by_quality_class=recall5_by_quality_class_result,
        expected_source_rank_distribution=rank_dist,
        score_margin_stats=score_margin_stats_result,
        score_margin_distribution=score_margin_distribution_result,
        abstention_precision=round(abstention_precision, 4),
        abstention_recall=round(abstention_recall, 4),
        unsafe_non_abstentions=unsafe_non_abstentions,
        correct_abstentions=correct_abstentions,
        incorrect_abstentions=incorrect_abstentions,
        adversarial_metrics=adversarial_metrics_result,
        conflict_metrics=conflict_metrics_result,
        no_answer_category_counts=no_answer_category_counts_result,
    )
