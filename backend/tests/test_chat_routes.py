from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from app.api.routes.chat import get_chat_service
from app.main import app


class _FakeChatService:
    def __init__(self) -> None:
        self.session = {
            "session_id": "chat_test",
            "created_at": "2026-04-18T12:00:00+00:00",
            "updated_at": "2026-04-18T12:00:00+00:00",
            "turns": [],
            "latest_graph": None,
            "latest_evidence": None,
            "latest_turn_id": None,
            "quota_status": {"paused_for_rest_of_day": False},
        }

    def bootstrap(self) -> dict[str, object]:
        return {
            "branding": {"assistant_name": "Graph-RAG AI Assistant"},
            "default_method": "kg_rag",
            "quick_prompts": ["Where was the director of Aci Zafer born?"],
            "graph_legend": [{"key": "film", "label": "Film", "color": "#19e4ff"}],
            "header_stats": [{"label": "Primary Model", "value": "openai/gpt-oss-120b"}],
            "quota_status": {"paused_for_rest_of_day": False, "snapshot": {"remaining_requests": 700}},
        }

    def create_session(self) -> dict[str, object]:
        return self.session

    def get_session(self, session_id: str) -> dict[str, object]:
        assert session_id == "chat_test"
        return self.session

    def run_turn(
        self,
        *,
        session_id: str,
        message: str,
        method: str = "kg_rag",
        emit_event=None,
    ) -> dict[str, object]:
        assert session_id == "chat_test"
        assert method == "kg_rag"
        turn = {
            "turn_id": "turn_test",
            "status": "completed",
            "method": method,
            "user_message": message,
            "assistant_message": "Izmir",
            "quota_snapshot": {"answer_generation": {"remaining_requests": 699}},
            "evidence_graph": {
                "nodes": [{"id": "Q1", "label": "Aci Zafer", "kind": "film", "role": "seed"}],
                "edges": [],
                "active_node_id": "Q1",
                "legend": [{"key": "film", "label": "Film", "color": "#19e4ff"}],
            },
            "evidence_panel": {
                "seed_entities": [{"entity_name": "Aci Zafer"}],
                "selected_triples": [],
                "expanded_query": "aci zafer director birth place",
                "cypher_queries": [
                    {
                        "label": "Answer path",
                        "purpose": "Replay the inferred path.",
                        "query": "MATCH path = (seed:Entity)-[:REL {pid: 'P57'}]->(hop1:Entity)-[:REL {pid: 'P19'}]->(hop2:Entity)",
                        "parameters": {"seed_ids": ["QFILM1"]},
                    }
                ],
                "retrieved_documents": [],
                "answer_basis": "Izmir",
            },
        }
        self.session = {
            **self.session,
            "turns": [turn],
            "latest_graph": turn["evidence_graph"],
            "latest_evidence": turn["evidence_panel"],
            "latest_turn_id": turn["turn_id"],
            "quota_status": {"paused_for_rest_of_day": False, "snapshot": {"remaining_requests": 699}},
        }
        if emit_event is not None:
            emit_event("turn_started", {"session_id": session_id, "turn": turn, "session": self.session})
            emit_event("seed_entities", {"seed_entities": [{"entity_name": "Aci Zafer"}]})
            emit_event("activation_round", {"round": {"round_index": 1, "selected_triples": []}})
            emit_event("graph_patch", {"graph": turn["evidence_graph"]})
            emit_event("expanded_query", {"expanded_query": turn["evidence_panel"]["expanded_query"]})
            emit_event("cypher_trace", {"cypher_queries": turn["evidence_panel"]["cypher_queries"]})
            emit_event("retrieved_documents", {"retrieved_documents": []})
            emit_event("answer_delta", {"delta": "Iz", "assistant_message": "Iz"})
            emit_event("answer_delta", {"delta": "mir", "assistant_message": "Izmir"})
            emit_event("turn_completed", {"session": self.session, "turn": turn})
            emit_event("quota_status", {"quota_status": self.session["quota_status"]})
        return {"session": self.session, "turn": turn}


class ChatRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fake_service = _FakeChatService()
        app.dependency_overrides[get_chat_service] = lambda: cls.fake_service
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()

    def test_bootstrap_endpoint_returns_branding_and_quota(self) -> None:
        response = self.client.get("/chat/bootstrap")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_method"], "kg_rag")
        self.assertIn("quick_prompts", payload)
        self.assertIn("quota_status", payload)

    def test_session_endpoints_create_and_return_session(self) -> None:
        create_response = self.client.post("/chat/sessions")
        self.assertEqual(create_response.status_code, 200)
        payload = create_response.json()
        self.assertEqual(payload["session_id"], "chat_test")

        get_response = self.client.get("/chat/sessions/chat_test")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["session_id"], "chat_test")

    def test_stream_endpoint_emits_expected_event_order(self) -> None:
        response = self.client.post(
            "/chat/sessions/chat_test/messages/stream",
            json={"message": "Where was the director of Aci Zafer born?", "method": "kg_rag", "stream": True},
        )
        self.assertEqual(response.status_code, 200)
        event_names = [
            line.split(": ", 1)[1]
            for line in response.text.splitlines()
            if line.startswith("event: ")
        ]
        self.assertEqual(
            event_names,
            [
                "ack",
                "turn_started",
                "seed_entities",
                "activation_round",
                "graph_patch",
                "expanded_query",
                "cypher_trace",
                "retrieved_documents",
                "answer_delta",
                "answer_delta",
                "turn_completed",
                "quota_status",
            ],
        )
        data_lines = [
            json.loads(line.split(": ", 1)[1])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(data_lines[-1]["quota_status"]["snapshot"]["remaining_requests"], 699)


if __name__ == "__main__":
    unittest.main()
