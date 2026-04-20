from __future__ import annotations

from typing import Any

from app.baselines import Phase5BaselineRunner, SUPPORTED_BASELINES
from app.baselines.common import normalize_for_match
from app.baselines.dataset import Phase4Dataset
from app.core.artifacts import utc_now_iso
from app.core.config import Settings
from app.evaluation.metrics import aggregate_metrics, evaluate_result
from app.evaluation.store import Phase7EvaluationStore
from app.kg_rag import KGInfusedRAGRunner
from app.providers import get_provider_registry

EVALUATION_METHODS = [*SUPPORTED_BASELINES, "kg_infused_rag"]


class Phase7EvaluationRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dataset = Phase4Dataset(settings)
        self.baselines = Phase5BaselineRunner(settings)
        self.kg_rag = KGInfusedRAGRunner(settings)
        self.registry = get_provider_registry(settings)
        self.store = Phase7EvaluationStore(settings)

    def list_questions(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self.dataset.list_questions(limit=limit)

    def coverage(
        self,
        *,
        methods: list[str] | None = None,
        question_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        selected_methods = self._selected_methods(methods)
        questions = self._selected_questions(question_ids=question_ids, limit=limit)
        question_id_list = [str(question["question_id"]) for question in questions]
        by_method: dict[str, Any] = {}
        for method in selected_methods:
            available = 0
            success = 0
            paused = 0
            error = 0
            missing_ids: list[str] = []
            for question_id in question_id_list:
                result = self._load_latest_result(method, question_id)
                if result is None:
                    missing_ids.append(question_id)
                    continue
                available += 1
                status = result.get("status")
                if status == "success":
                    success += 1
                elif status == "paused":
                    paused += 1
                elif status == "error":
                    error += 1
            by_method[method] = {
                "method": method,
                "expected_total": len(question_id_list),
                "available_results": available,
                "coverage": available / len(question_id_list) if question_id_list else 0.0,
                "success_count": success,
                "paused_count": paused,
                "error_count": error,
                "missing_question_ids": missing_ids,
            }

        payload = {
            "created_at": utc_now_iso(),
            "question_count": len(question_id_list),
            "question_ids": question_id_list,
            "methods": selected_methods,
            "by_method": by_method,
        }
        self.store.save_latest("coverage.json", payload)
        self.store.append_history({"created_at": payload["created_at"], "action": "coverage", **payload})
        return payload

    def run_experiments(
        self,
        *,
        methods: list[str] | None = None,
        question_ids: list[str] | None = None,
        limit: int | None = None,
        top_k: int = 6,
        max_rounds: int | None = None,
        skip_existing: bool = True,
    ) -> dict[str, Any]:
        selected_methods = self._selected_methods(methods)
        questions = self._selected_questions(question_ids=question_ids, limit=limit)
        runs: list[dict[str, Any]] = []
        stop_reason: str | None = None

        for question in questions:
            question_id = str(question["question_id"])
            for method in selected_methods:
                execution = self._run_method(
                    method=method,
                    question_id=question_id,
                    top_k=top_k,
                    max_rounds=max_rounds,
                    skip_existing=skip_existing,
                )
                runs.append(
                    {
                        "question_id": question_id,
                        "method": method,
                        "status": execution["status"],
                    }
                )
                if execution["status"] == "paused":
                    stop_reason = "groq_paused_for_rest_of_day"
                    break
            if stop_reason:
                break

        coverage = self.coverage(
            methods=selected_methods,
            question_ids=[str(question["question_id"]) for question in questions],
        )
        quota_snapshot = self.registry.groq.snapshot().details.get("quota_snapshot")
        payload = {
            "created_at": utc_now_iso(),
            "status": "paused" if stop_reason else "completed",
            "stop_reason": stop_reason,
            "methods": selected_methods,
            "question_ids": [str(question["question_id"]) for question in questions],
            "attempted_runs": len(runs),
            "runs": runs,
            "coverage": coverage,
            "quota_snapshot": quota_snapshot,
        }
        self.store.save_latest("run_summary.json", payload)
        self.store.append_history({"created_at": payload["created_at"], "action": "run_experiments", **payload})
        return payload

    def compute_metrics(
        self,
        *,
        methods: list[str] | None = None,
        question_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        selected_methods = self._selected_methods(methods)
        questions = self._selected_questions(question_ids=question_ids, limit=limit)
        by_method: dict[str, Any] = {}

        for method in selected_methods:
            records: list[dict[str, Any]] = []
            missing_question_ids: list[str] = []
            for question in questions:
                question_id = str(question["question_id"])
                result = self._load_latest_result(method, question_id)
                if result is None:
                    missing_question_ids.append(question_id)
                    continue
                metrics = evaluate_result(question, result)
                records.append(
                    {
                        "question_id": question_id,
                        "question": question["question"],
                        "metrics": metrics,
                        "result_status": result.get("status"),
                    }
                )

            by_method[method] = {
                "summary": aggregate_metrics(method, records=records, expected_total=len(questions)),
                "missing_question_ids": missing_question_ids,
                "questions": records,
            }

        payload = {
            "created_at": utc_now_iso(),
            "question_count": len(questions),
            "question_ids": [str(question["question_id"]) for question in questions],
            "methods": selected_methods,
            "by_method": by_method,
        }
        self.store.save_latest("metrics.json", payload)
        self.store.append_history({"created_at": payload["created_at"], "action": "compute_metrics", **payload})
        return payload

    def export_case_studies(
        self,
        *,
        methods: list[str] | None = None,
        question_ids: list[str] | None = None,
        limit: int | None = None,
        success_limit: int = 5,
        failure_limit: int = 5,
    ) -> dict[str, Any]:
        metrics_payload = self.compute_metrics(methods=methods, question_ids=question_ids, limit=limit)
        question_index = {
            str(question["question_id"]): question
            for question in self._selected_questions(question_ids=question_ids, limit=limit)
        }

        success_entries: list[dict[str, Any]] = []
        failure_entries: list[dict[str, Any]] = []
        for method in metrics_payload["methods"]:
            method_payload = metrics_payload["by_method"][method]
            for record in method_payload["questions"]:
                question_id = str(record["question_id"])
                result = self._load_latest_result(method, question_id)
                if result is None:
                    continue
                case_entry = self._build_case_entry(
                    method=method,
                    question=question_index[question_id],
                    result=result,
                    metrics=record["metrics"],
                )
                if record["metrics"]["exact_match"]:
                    success_entries.append(case_entry)
                else:
                    failure_entries.append(case_entry)

        success_entries.sort(key=lambda item: (-float(item["metrics"]["f1"]), item["method"], item["question_id"]))
        failure_entries.sort(key=lambda item: (float(item["metrics"]["f1"]), item["method"], item["question_id"]))
        payload = {
            "created_at": utc_now_iso(),
            "methods": metrics_payload["methods"],
            "requested_success_limit": success_limit,
            "requested_failure_limit": failure_limit,
            "available_successes": len(success_entries),
            "available_failures": len(failure_entries),
            "success_cases": success_entries[:success_limit],
            "failure_cases": failure_entries[:failure_limit],
        }
        self.store.save_latest("case_studies.json", payload)
        self.store.append_history({"created_at": payload["created_at"], "action": "export_case_studies", **payload})
        return payload

    def latest_results(self) -> dict[str, Any]:
        return {
            "coverage": self.store.load_latest("coverage.json"),
            "run_summary": self.store.load_latest("run_summary.json"),
            "metrics": self.store.load_latest("metrics.json"),
            "case_studies": self.store.load_latest("case_studies.json"),
        }

    def _run_method(
        self,
        *,
        method: str,
        question_id: str,
        top_k: int,
        max_rounds: int | None,
        skip_existing: bool,
    ) -> dict[str, Any]:
        if method == "kg_infused_rag":
            return self.kg_rag.run_question(
                question_id=question_id,
                top_k=top_k,
                max_rounds=max_rounds,
                skip_existing=skip_existing,
            )
        return self.baselines.run_question(
            method=method,
            question_id=question_id,
            top_k=top_k,
            skip_existing=skip_existing,
        )

    def _load_latest_result(self, method: str, question_id: str) -> dict[str, Any] | None:
        if method == "kg_infused_rag":
            return self.kg_rag.store.load_trace(question_id)
        return self.baselines.results.load_result(method, question_id)

    def _selected_methods(self, methods: list[str] | None) -> list[str]:
        selected_methods = methods or list(EVALUATION_METHODS)
        for method in selected_methods:
            if method not in EVALUATION_METHODS:
                raise ValueError(f"Unsupported evaluation method: {method}")
        return selected_methods

    def _selected_questions(
        self,
        *,
        question_ids: list[str] | None,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        if question_ids:
            questions = [self.dataset.question(question_id) for question_id in question_ids]
        else:
            questions = self.dataset.list_questions(limit=limit)
        if limit is not None:
            questions = questions[:limit]
        return questions

    def _build_case_entry(
        self,
        *,
        method: str,
        question: dict[str, Any],
        result: dict[str, Any],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        expected_answer = str((question.get("gold_answer") or {}).get("text", ""))
        system_answer = str(result.get("prediction_text", ""))
        retrieved_documents = result.get("retrieved_documents") or []
        pipeline_analysis = self._pipeline_analysis(method=method, result=result)
        return {
            "method": method,
            "question_id": str(question["question_id"]),
            "question": question["question"],
            "expected_answer": expected_answer,
            "system_answer": system_answer,
            "metrics": metrics,
            "pipeline_analysis": pipeline_analysis,
            "success_or_failure_reason": self._case_reason(
                method=method,
                result=result,
                metrics=metrics,
            ),
            "improvement_suggestion": self._improvement_suggestion(
                method=method,
                question=question,
                result=result,
                metrics=metrics,
            ),
            "retrieved_document_count": len(retrieved_documents),
        }

    def _pipeline_analysis(self, *, method: str, result: dict[str, Any]) -> str:
        if method == "kg_infused_rag":
            return (
                f"Seed entities: {len(result.get('seed_entities') or [])}, "
                f"activation rounds: {len(result.get('activation_rounds') or [])}, "
                f"retrieved documents: {len(result.get('retrieved_documents') or [])}."
            )
        expanded_query = result.get("expanded_query")
        if expanded_query:
            return (
                f"Expanded query was used and {len(result.get('retrieved_documents') or [])} "
                "documents were retrieved."
            )
        return f"Retrieved documents: {len(result.get('retrieved_documents') or [])}."

    def _case_reason(
        self,
        *,
        method: str,
        result: dict[str, Any],
        metrics: dict[str, Any],
    ) -> str:
        if result.get("status") != "success":
            return "The run did not complete successfully, so the answer was not reliable."
        if metrics["exact_match"]:
            if method == "no_retrieval":
                return "The model answered correctly without retrieval support."
            if method == "kg_infused_rag":
                return "The KG path and retrieved evidence aligned with the expected answer."
            return "The retrieved context was sufficient to recover the expected answer."

        normalized_prediction = normalize_for_match(str(result.get("prediction_text", "")))
        if not normalized_prediction or normalized_prediction == "unknown":
            return "The system could not ground a confident final answer."
        if method == "kg_infused_rag" and not (result.get("activation_rounds") or []):
            return "KG seed selection or spreading activation did not produce enough evidence."
        if method != "no_retrieval" and len(result.get("retrieved_documents") or []) == 0:
            return "The retrieval stage failed to return useful evidence."
        return "The answer generation stage produced a mismatch against the gold answer."

    def _improvement_suggestion(
        self,
        *,
        method: str,
        question: dict[str, Any],
        result: dict[str, Any],
        metrics: dict[str, Any],
    ) -> str:
        if metrics["exact_match"]:
            return "Keep this trace as a positive reference example for the final report."
        if method == "kg_infused_rag":
            if not (result.get("activation_rounds") or []):
                return "Tighten seed-entity linking and relation-path inference for this question template."
            return "Refine KG answer normalization so the final span matches the gold entity surface form more closely."
        if method == "vanilla_qe":
            return "Improve query expansion constraints so retrieval stays closer to the verified graph path."
        if method == "vanilla_rag":
            return "Increase retrieval precision by promoting path-support documents for this template."
        if method == "no_retrieval":
            return "Use this failure to show why retrieval is needed for multi-hop questions."
        if question.get("question_type") == "comparison":
            return "Preserve separate evidence chains for both sides of the comparison."
        return "Add more answer-format control to reduce generation drift."
