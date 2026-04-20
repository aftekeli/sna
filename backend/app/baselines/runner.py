from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.baselines.common import extract_chat_text, heuristic_match, truncate_text
from app.baselines.corpus import Phase5CorpusIndex, RetrievalDocument
from app.baselines.dataset import Phase4Dataset
from app.baselines.results import Phase5ResultStore
from app.core.artifacts import utc_now_iso
from app.core.config import Settings
from app.providers import get_provider_registry
from app.providers.groq_provider import GroqActionBlockedError, GroqRateLimitedError

SUPPORTED_BASELINES = ("no_retrieval", "vanilla_rag", "vanilla_qe")


@dataclass(slots=True)
class QuestionExecution:
    method: str
    question: dict[str, Any]
    top_k: int


class Phase5BaselineRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = get_provider_registry(settings)
        self.dataset = Phase4Dataset(settings)
        self.corpus = Phase5CorpusIndex(settings)
        self.results = Phase5ResultStore(settings)

    def list_questions(self, *, limit: int | None = None) -> list[dict[str, object]]:
        records = self.dataset.list_questions(limit=limit)
        return [
            {
                "question_id": record["question_id"],
                "question": record["question"],
                "question_type": record["question_type"],
                "template": record["template"],
                "gold_answer": record["gold_answer"]["text"],
            }
            for record in records
        ]

    def build_corpus_index(self, *, force_rebuild: bool = False) -> dict[str, object]:
        return self.corpus.ensure_built(force_rebuild=force_rebuild)

    def corpus_status(self) -> dict[str, object]:
        return self.corpus.status()

    def run_question(
        self,
        *,
        method: str,
        question_id: str,
        top_k: int = 6,
        skip_existing: bool = True,
    ) -> dict[str, object]:
        if method not in SUPPORTED_BASELINES:
            raise ValueError(f"Unsupported baseline method: {method}")

        existing = self.results.load_result(method, question_id)
        if existing and skip_existing and existing.get("status") == "success":
            return {
                "status": "skipped_existing",
                "result": existing,
            }

        question = self.dataset.question(question_id)
        execution = QuestionExecution(method=method, question=question, top_k=top_k)

        try:
            if method == "no_retrieval":
                result = self._run_no_retrieval(execution)
            elif method == "vanilla_rag":
                result = self._run_vanilla_rag(execution)
            elif method == "vanilla_qe":
                result = self._run_vanilla_qe(execution)
            else:  # pragma: no cover - guarded above
                raise ValueError(f"Unsupported baseline method: {method}")
        except (GroqActionBlockedError, GroqRateLimitedError) as exc:
            result = self._failed_result(execution, status="paused", message=str(exc))
        except Exception as exc:  # pragma: no cover - defensive catch for runtime integration
            result = self._failed_result(execution, status="error", message=str(exc))

        self.results.save_result(result)
        return {
            "status": result["status"],
            "result": result,
        }

    def run_dataset(
        self,
        *,
        methods: list[str] | None = None,
        question_ids: list[str] | None = None,
        limit: int | None = None,
        top_k: int = 6,
        skip_existing: bool = True,
    ) -> dict[str, object]:
        selected_methods = methods or list(SUPPORTED_BASELINES)
        for method in selected_methods:
            if method not in SUPPORTED_BASELINES:
                raise ValueError(f"Unsupported baseline method: {method}")

        selected_question_ids = question_ids or self.dataset.ids()
        if limit is not None:
            selected_question_ids = selected_question_ids[:limit]

        results: list[dict[str, object]] = []
        stop_reason: str | None = None
        for method in selected_methods:
            for question_id in selected_question_ids:
                execution_result = self.run_question(
                    method=method,
                    question_id=question_id,
                    top_k=top_k,
                    skip_existing=skip_existing,
                )
                results.append(
                    {
                        "method": method,
                        "question_id": question_id,
                        "status": execution_result["status"],
                    }
                )
                if execution_result["status"] == "paused":
                    stop_reason = "groq_paused_for_rest_of_day"
                    break
            if stop_reason:
                break

        return {
            "status": "paused" if stop_reason else "completed",
            "stop_reason": stop_reason,
            "attempted_runs": len(results),
            "results": results,
        }

    def get_results(
        self,
        *,
        method: str | None = None,
        question_id: str | None = None,
    ) -> list[dict[str, object]]:
        return self.results.list_results(method=method, question_id=question_id)

    def _run_no_retrieval(self, execution: QuestionExecution) -> dict[str, object]:
        question_text = execution.question["question"]
        response = self.registry.groq.chat_completion(
            action_name=f"phase5_no_retrieval_answer_{execution.question['question_id']}",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer factoid Turkish cinema questions with a short answer only. "
                        "If you are unsure, reply with unknown."
                    ),
                },
                {"role": "user", "content": question_text},
            ],
            max_output_tokens=96,
            temperature=0.0,
            metadata={"method": execution.method, "question_id": execution.question["question_id"]},
        )
        prediction_text = extract_chat_text(response["response"])
        return self._success_result(
            execution,
            prediction_text=prediction_text,
            quota_snapshot=response["quota_snapshot"],
            retrieved_documents=[],
            expanded_query=None,
        )

    def _run_vanilla_rag(self, execution: QuestionExecution) -> dict[str, object]:
        self.corpus.ensure_built()
        retrieved_documents = self.corpus.search(execution.question["question"], limit=execution.top_k)
        response = self.registry.groq.chat_completion(
            action_name=f"phase5_vanilla_rag_answer_{execution.question['question_id']}",
            messages=self._rag_messages(
                question_text=execution.question["question"],
                retrieved_documents=retrieved_documents,
            ),
            max_output_tokens=128,
            temperature=0.0,
            metadata={"method": execution.method, "question_id": execution.question["question_id"]},
        )
        prediction_text = extract_chat_text(response["response"])
        return self._success_result(
            execution,
            prediction_text=prediction_text,
            quota_snapshot=response["quota_snapshot"],
            retrieved_documents=retrieved_documents,
            expanded_query=None,
        )

    def _run_vanilla_qe(self, execution: QuestionExecution) -> dict[str, object]:
        self.corpus.ensure_built()
        expansion = self.registry.groq.chat_completion(
            action_name=f"phase5_vanilla_qe_expand_{execution.question['question_id']}",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite the question as a concise retrieval query. "
                        "Preserve named entities, answer type hints, and relation hints. "
                        "Return only one line."
                    ),
                },
                {"role": "user", "content": execution.question["question"]},
            ],
            max_output_tokens=48,
            temperature=0.0,
            metadata={"method": execution.method, "question_id": execution.question["question_id"], "stage": "expand"},
        )
        expanded_query = extract_chat_text(expansion["response"]) or execution.question["question"]
        retrieved_documents = self.corpus.search(expanded_query, limit=execution.top_k)
        response = self.registry.groq.chat_completion(
            action_name=f"phase5_vanilla_qe_answer_{execution.question['question_id']}",
            messages=self._rag_messages(
                question_text=execution.question["question"],
                retrieved_documents=retrieved_documents,
                expanded_query=expanded_query,
            ),
            max_output_tokens=128,
            temperature=0.0,
            metadata={"method": execution.method, "question_id": execution.question["question_id"], "stage": "answer"},
        )
        prediction_text = extract_chat_text(response["response"])
        return self._success_result(
            execution,
            prediction_text=prediction_text,
            quota_snapshot=response["quota_snapshot"],
            retrieved_documents=retrieved_documents,
            expanded_query=expanded_query,
        )

    def _rag_messages(
        self,
        *,
        question_text: str,
        retrieved_documents: list[RetrievalDocument],
        expanded_query: str | None = None,
    ) -> list[dict[str, str]]:
        context_blocks = []
        for index, document in enumerate(retrieved_documents, start=1):
            context_blocks.append(
                f"[Context {index}] {document.title}\n{truncate_text(document.body, limit=500)}"
            )
        context_text = "\n\n".join(context_blocks) if context_blocks else "[No retrieved context]"
        user_lines = [f"Question: {question_text}"]
        if expanded_query:
            user_lines.append(f"Expanded retrieval query: {expanded_query}")
        user_lines.append("Retrieved context:")
        user_lines.append(context_text)
        return [
            {
                "role": "system",
                "content": (
                    "Answer the question using only the retrieved context. "
                    "If the context is insufficient, reply with unknown. "
                    "Return a short answer phrase only."
                ),
            },
            {"role": "user", "content": "\n\n".join(user_lines)},
        ]

    def _success_result(
        self,
        execution: QuestionExecution,
        *,
        prediction_text: str,
        quota_snapshot: dict[str, object] | None,
        retrieved_documents: list[RetrievalDocument],
        expanded_query: str | None,
    ) -> dict[str, object]:
        gold_answer_text = execution.question["gold_answer"]["text"]
        match_details = heuristic_match(prediction_text, gold_answer_text)
        return {
            "created_at": utc_now_iso(),
            "status": "success",
            "method": execution.method,
            "question_id": execution.question["question_id"],
            "question": execution.question["question"],
            "question_type": execution.question["question_type"],
            "template": execution.question["template"],
            "difficulty": execution.question["difficulty"],
            "gold_answer": execution.question["gold_answer"],
            "prediction_text": prediction_text,
            "expanded_query": expanded_query,
            "retrieved_documents": [document.to_dict() for document in retrieved_documents],
            "quota_snapshot": quota_snapshot,
            "provider": {"name": "groq", "model": self.settings.groq_model},
            "match": match_details,
        }

    def _failed_result(
        self,
        execution: QuestionExecution,
        *,
        status: str,
        message: str,
    ) -> dict[str, object]:
        return {
            "created_at": utc_now_iso(),
            "status": status,
            "method": execution.method,
            "question_id": execution.question["question_id"],
            "question": execution.question["question"],
            "question_type": execution.question["question_type"],
            "template": execution.question["template"],
            "difficulty": execution.question["difficulty"],
            "gold_answer": execution.question["gold_answer"],
            "prediction_text": "",
            "expanded_query": None,
            "retrieved_documents": [],
            "provider": {"name": "groq", "model": self.settings.groq_model},
            "error": message,
        }
