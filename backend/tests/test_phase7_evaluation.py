from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.config import Settings
from app.evaluation.metrics import aggregate_metrics, evaluate_result, retrieval_recall, token_f1
from app.evaluation.store import Phase7EvaluationStore


class Phase7EvaluationInfrastructureTests(unittest.TestCase):
    def build_settings(self) -> Settings:
        return Settings(_env_file=None)

    def sample_question(self) -> dict[str, object]:
        return {
            "question_id": "qa_test",
            "question": "Where was the director of Aci Zafer born?",
            "question_type": "two_hop",
            "gold_answer": {"entity_id": "QPLACE", "text": "Izmir"},
            "reasoning_path_count": 1,
            "supporting_paths": [
                {
                    "template": "film_director_birth_place",
                    "triples": [],
                }
            ],
        }

    def sample_result(self) -> dict[str, object]:
        return {
            "status": "success",
            "prediction_text": "Izmir",
            "retrieved_documents": [
                {
                    "doc_id": "path::qa_test::1",
                    "title": "Where was the director of Aci Zafer born?",
                    "body": "Aci Zafer was directed by Halit Refig. Halit Refig was born in Izmir.",
                    "source_kind": "question_support_path",
                    "source_entity_id": "QFILM",
                    "metadata": {"question_id": "qa_test"},
                }
            ],
            "match": {
                "prediction_normalized": "izmir",
                "gold_normalized": "izmir",
                "exact_match": True,
                "contains_match": True,
            },
        }

    def test_token_f1_is_one_for_identical_single_span_answers(self) -> None:
        self.assertEqual(token_f1("Izmir", "Izmir"), 1.0)

    def test_retrieval_recall_uses_support_path_documents(self) -> None:
        self.assertEqual(retrieval_recall(self.sample_question(), self.sample_result()), 1.0)

    def test_evaluate_result_returns_expected_metrics(self) -> None:
        metrics = evaluate_result(self.sample_question(), self.sample_result())
        self.assertTrue(metrics["accuracy"])
        self.assertTrue(metrics["exact_match"])
        self.assertEqual(metrics["f1"], 1.0)

    def test_aggregate_metrics_computes_coverage(self) -> None:
        aggregate = aggregate_metrics(
            "vanilla_rag",
            expected_total=2,
            records=[
                {
                    "question_id": "qa_test",
                    "metrics": evaluate_result(self.sample_question(), self.sample_result()),
                }
            ],
        )
        self.assertEqual(aggregate["available_results"], 1)
        self.assertEqual(aggregate["coverage"], 0.5)

    def test_evaluation_store_persists_latest_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = Phase7EvaluationStore(self.build_settings(), root_dir=Path(tmp_dir))
            payload = {"created_at": "2026-04-18T00:00:00+00:00", "status": "ok"}
            store.save_latest("metrics.json", payload)
            loaded = store.load_latest("metrics.json")
            self.assertEqual(loaded, payload)


if __name__ == "__main__":
    unittest.main()
