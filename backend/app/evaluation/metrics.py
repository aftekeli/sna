from __future__ import annotations

from typing import Any

from app.baselines.common import heuristic_match, normalize_for_match


def token_f1(prediction: str, gold_answer: str) -> float:
    prediction_tokens = normalize_for_match(prediction).split()
    gold_tokens = normalize_for_match(gold_answer).split()
    if not prediction_tokens or not gold_tokens:
        return 0.0
    prediction_counts: dict[str, int] = {}
    gold_counts: dict[str, int] = {}
    for token in prediction_tokens:
        prediction_counts[token] = prediction_counts.get(token, 0) + 1
    for token in gold_tokens:
        gold_counts[token] = gold_counts.get(token, 0) + 1
    overlap = 0
    for token, prediction_count in prediction_counts.items():
        overlap += min(prediction_count, gold_counts.get(token, 0))
    if overlap <= 0:
        return 0.0
    precision = overlap / len(prediction_tokens)
    recall = overlap / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def retrieval_recall(question: dict[str, Any], result: dict[str, Any]) -> float:
    retrieved_documents = result.get("retrieved_documents") or []
    if not retrieved_documents:
        return 0.0

    question_id = str(question["question_id"])
    supporting_paths = question.get("supporting_paths") or []
    total_support_paths = len(supporting_paths)
    if total_support_paths > 0:
        matched_path_docs = {
            str(document.get("doc_id", ""))
            for document in retrieved_documents
            if str(document.get("doc_id", "")).startswith(f"path::{question_id}::")
        }
        if matched_path_docs:
            return min(len(matched_path_docs), total_support_paths) / total_support_paths

    gold_answer = question.get("gold_answer") or {}
    gold_entity_id = gold_answer.get("entity_id")
    gold_text_normalized = normalize_for_match(str(gold_answer.get("text", "")))
    for document in retrieved_documents:
        metadata = document.get("metadata") or {}
        if gold_entity_id and metadata.get("target_id") == gold_entity_id:
            return 1.0
        if gold_entity_id and document.get("source_entity_id") == gold_entity_id:
            return 1.0
        haystack = normalize_for_match(
            " ".join(
                [
                    str(document.get("title", "")),
                    str(document.get("body", "")),
                    str(document.get("snippet", "")),
                ]
            )
        )
        if gold_text_normalized and gold_text_normalized in haystack:
            return 1.0
    return 0.0


def evaluate_result(question: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    prediction_text = str(result.get("prediction_text", "")).strip()
    gold_answer_text = str((question.get("gold_answer") or {}).get("text", "")).strip()
    match = result.get("match") or heuristic_match(prediction_text, gold_answer_text)
    exact_match = bool(match.get("exact_match", False))
    contains_match = bool(match.get("contains_match", False))
    return {
        "status": result.get("status", "missing"),
        "prediction_text": prediction_text,
        "gold_answer_text": gold_answer_text,
        "accuracy": contains_match,
        "exact_match": exact_match,
        "contains_match": contains_match,
        "f1": token_f1(prediction_text, gold_answer_text),
        "retrieval_recall": retrieval_recall(question, result),
    }


def aggregate_metrics(
    method: str,
    *,
    records: list[dict[str, Any]],
    expected_total: int,
) -> dict[str, Any]:
    available_count = len(records)
    if available_count == 0:
        return {
            "method": method,
            "expected_total": expected_total,
            "available_results": 0,
            "coverage": 0.0,
            "accuracy": 0.0,
            "exact_match": 0.0,
            "f1": 0.0,
            "retrieval_recall": 0.0,
            "status_breakdown": {},
        }

    status_breakdown: dict[str, int] = {}
    accuracy_sum = 0.0
    exact_match_sum = 0.0
    f1_sum = 0.0
    retrieval_recall_sum = 0.0
    for record in records:
        metrics = record["metrics"]
        status = str(metrics["status"])
        status_breakdown[status] = status_breakdown.get(status, 0) + 1
        accuracy_sum += float(metrics["accuracy"])
        exact_match_sum += float(metrics["exact_match"])
        f1_sum += float(metrics["f1"])
        retrieval_recall_sum += float(metrics["retrieval_recall"])

    return {
        "method": method,
        "expected_total": expected_total,
        "available_results": available_count,
        "coverage": available_count / expected_total if expected_total else 0.0,
        "accuracy": accuracy_sum / available_count,
        "exact_match": exact_match_sum / available_count,
        "f1": f1_sum / available_count,
        "retrieval_recall": retrieval_recall_sum / available_count,
        "status_breakdown": status_breakdown,
    }
