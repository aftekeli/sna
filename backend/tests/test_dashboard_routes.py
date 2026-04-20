from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app


class DashboardRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_overview_endpoint_returns_graph_dataset_and_evaluation_sections(self) -> None:
        response = self.client.get("/dashboard/overview")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("graph", payload)
        self.assertIn("dataset", payload)
        self.assertIn("evaluation", payload)
        self.assertEqual(payload["dataset"]["question_count"], 50)

    def test_cypher_library_endpoint_returns_templates(self) -> None:
        response = self.client.get("/dashboard/cypher-library")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload["templates"]), 3)
        self.assertIn("verification", payload)

    def test_question_trace_endpoint_returns_baselines_and_kg_trace(self) -> None:
        response = self.client.get("/dashboard/question-trace", params={"question_id": "qa_104db2fbbec9"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["question_id"], "qa_104db2fbbec9")
        self.assertIn("kg_rag", payload)
        self.assertIn("baselines", payload)
        self.assertIn("vanilla_rag", payload["baselines"])


if __name__ == "__main__":
    unittest.main()
