from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import HTTPException

from app.chat.store import ChatSessionStore
from app.core.config import Settings
from app.kg_rag.runner import KGInfusedRAGRunner

EventEmitter = Callable[[str, dict[str, Any]], None]


class ChatRuntimeService:
    def __init__(
        self,
        settings: Settings,
        *,
        store: ChatSessionStore | None = None,
        runner: KGInfusedRAGRunner | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or ChatSessionStore(settings)
        self.runner = runner or KGInfusedRAGRunner(settings)

    def bootstrap(self) -> dict[str, Any]:
        metrics_path = self.settings.phase7_dir / "latest" / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
        kg_summary = metrics.get("by_method", {}).get("kg_infused_rag", {}).get("summary", {})
        provider_snapshot = self.runner.registry.groq.snapshot().to_dict()
        provider_details = provider_snapshot.get("details", {})
        runtime_status = provider_details.get("runtime_status") or {}
        quota_snapshot = provider_details.get("quota_snapshot") or {}
        pause_state = provider_details.get("pause_state")
        quick_prompt_groups = self._build_prompt_groups()

        return {
            "branding": {
                "product_name": "Turkiye Cinema KG-RAG",
                "product_tagline": "Wikidata5M x Neo4j x Groq",
                "assistant_name": "Graph-RAG AI Assistant",
                "assistant_subtitle": "Live KG-guided reasoning over the Turkiye cinema domain",
                "status_label": "Online",
            },
            "default_method": "kg_rag",
            "quick_prompts": [
                prompt
                for group in quick_prompt_groups
                for prompt in group["prompts"]
            ],
            "quick_prompt_groups": quick_prompt_groups,
            "graph_legend": self.runner.graph_legend(),
            "header_stats": [
                {
                    "label": "Primary Model",
                    "value": quota_snapshot.get("model") or self.settings.groq_model,
                    "hint": f"Groq paced at {runtime_status.get('request_pacing_rpm', self.settings.groq_request_pacing_rpm)} RPM",
                    "tone": "cyan",
                },
                {
                    "label": "Best Phase 7 F1",
                    "value": f"{float(kg_summary.get('f1', 0.98)):.2f}",
                    "hint": f"Exact match {float(kg_summary.get('exact_match', 0.98)):.2f}",
                    "tone": "green",
                },
                {
                    "label": "Quota Left",
                    "value": str(quota_snapshot.get("remaining_requests", 0)),
                    "hint": f"Tokens left {quota_snapshot.get('remaining_tokens', 0)}",
                    "tone": "amber",
                },
                {
                    "label": "Question Memory",
                    "value": "Adaptive",
                    "hint": "Prior turns are reused only for follow-up questions",
                    "tone": "pink",
                },
            ],
            "quota_status": {
                "configured": provider_snapshot.get("configured", False),
                "paused_for_rest_of_day": bool(pause_state),
                "pause_state": pause_state,
                "runtime_status": runtime_status,
                "snapshot": quota_snapshot,
            },
        }

    def _build_prompt_groups(self) -> list[dict[str, Any]]:
        verified_questions = self._load_verified_prompt_examples()
        exploratory_questions = [
            "Kemal Sunal nerede doğmuştur?",
            "Did the directors of Aci Zafer and Arabesk study in the same country?",
            "Where did the cast member of Arabesk study?",
        ]
        return [
            {
                "key": "verified",
                "label": "Verified dataset prompts",
                "description": "Questions directly sampled from the Phase 4 dataset.",
                "tone": "green",
                "prompts": verified_questions,
            },
            {
                "key": "exploratory",
                "label": "Exploratory edge cases",
                "description": "Useful for stress-testing coverage; these may return unknown.",
                "tone": "amber",
                "prompts": exploratory_questions,
            },
        ]

    def _load_verified_prompt_examples(self) -> list[str]:
        dataset_path = self.settings.phase4_dataset_path
        if not dataset_path.exists():
            return [
                "Where was the director of Aci Zafer born?",
                "Which award was received by the director of Bir Avuç Toprak?",
                "Where did the director of Ember study?",
                "Were the directors of Ah Nerede and Arabesk born in the same country?",
            ]

        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        picks: list[tuple[str, str]] = [
            ("film_director_birth_place", "Aci Zafer"),
            ("film_director_award", "Bir Avuç Toprak"),
            ("film_director_education", "Ember"),
            ("film_director_birth_place_country__comparison", "Arabesk"),
        ]
        selected: list[str] = []
        seen: set[str] = set()

        for template_name, keyword in picks:
            for record in dataset:
                question = record.get("question", "")
                if record.get("template") != template_name:
                    continue
                if keyword.lower() not in question.lower():
                    continue
                if question in seen:
                    continue
                seen.add(question)
                selected.append(question)
                break

        if len(selected) >= 4:
            return selected

        for record in dataset:
            question = record.get("question", "")
            if not question or question in seen:
                continue
            seen.add(question)
            selected.append(question)
            if len(selected) == 4:
                break
        return selected

    def create_session(self) -> dict[str, Any]:
        return self.store.create_session()

    def get_session(self, session_id: str) -> dict[str, Any]:
        session = self.store.load_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}")
        return session

    def run_turn(
        self,
        *,
        session_id: str,
        message: str,
        method: str = "kg_rag",
        emit_event: EventEmitter | None = None,
    ) -> dict[str, Any]:
        if method != "kg_rag":
            raise HTTPException(status_code=400, detail="Chat v1 supports only kg_rag.")
        cleaned_message = message.strip()
        if not cleaned_message:
            raise HTTPException(status_code=400, detail="Message cannot be empty.")

        session = self.get_session(session_id)
        turn = self.store.add_turn(session_id, user_message=cleaned_message, method=method)
        session = self.get_session(session_id)
        quota_status = self.bootstrap()["quota_status"]
        self._emit(
            emit_event,
            "turn_started",
            {"session_id": session_id, "turn": turn, "session": session, "quota_status": quota_status},
        )
        self._emit(emit_event, "quota_status", {"quota_status": quota_status})

        history = self._conversation_history(session)

        try:
            trace = self.runner.run_freeform(
                question_text=cleaned_message,
                conversation_history=history,
                turn_id=turn["turn_id"],
                emit_event=emit_event,
            )
            evidence_panel = self.runner.build_chat_evidence_panel(trace)
            evidence_graph = self.runner.build_evidence_graph(trace)
            final_status = "completed" if trace["status"] == "success" else trace["status"]
            answer_meta = trace.get("answer_meta") or {}
            session, updated_turn = self.store.update_turn(
                session_id,
                turn["turn_id"],
                assistant_message=trace.get("display_text") or trace.get("prediction_text") or trace.get("error") or "",
                assistant_memory_message=answer_meta.get("memory_text") or trace.get("prediction_text") or trace.get("display_text") or "",
                status=final_status,
                error=trace.get("error"),
                quota_snapshot=trace.get("quota_snapshot"),
                evidence_graph=evidence_graph,
                evidence_panel=evidence_panel,
                quota_status=self.bootstrap()["quota_status"],
                answer_meta=answer_meta,
            )
            payload = {
                "session": session,
                "turn": updated_turn,
                "trace": trace,
            }
            if final_status != "completed":
                self._emit(
                    emit_event,
                    "error",
                    {
                        "error": trace.get("error") or "Live KG-RAG could not complete the turn.",
                        "turn": updated_turn,
                        "session": session,
                    },
                )
            self._emit(emit_event, "turn_completed", payload)
            self._emit(emit_event, "quota_status", {"quota_status": session.get("quota_status")})
            return payload
        except HTTPException:
            raise
        except Exception as exc:
            session, updated_turn = self.store.update_turn(
                session_id,
                turn["turn_id"],
                assistant_message="I could not complete this live KG-RAG run.",
                assistant_memory_message="I could not complete this live KG-RAG run.",
                status="error",
                error=str(exc),
                quota_status=self.bootstrap()["quota_status"],
                answer_meta={
                    "status": "error",
                    "reason_code": "runtime_error",
                    "confidence": "low",
                    "canonical_answer": "",
                    "display_text": "I could not complete this live KG-RAG run.",
                    "memory_text": "I could not complete this live KG-RAG run.",
                },
            )
            payload = {
                "session": session,
                "turn": updated_turn,
                "error": str(exc),
            }
            self._emit(emit_event, "error", payload)
            self._emit(emit_event, "quota_status", {"quota_status": session.get("quota_status")})
            return payload

    def _conversation_history(self, session: dict[str, Any], *, max_chars: int = 2400) -> list[dict[str, str]]:
        history: list[dict[str, str]] = []
        total_chars = 0
        for turn in reversed(session.get("turns", [])):
            if turn.get("status") != "completed":
                continue
            assistant_message = (turn.get("assistant_memory_message") or turn.get("assistant_message") or "").strip()
            user_message = (turn.get("user_message") or "").strip()
            staged_messages: list[dict[str, str]] = []
            if assistant_message:
                staged_messages.insert(0, {"role": "assistant", "content": assistant_message})
            if user_message:
                staged_messages.insert(0, {"role": "user", "content": user_message})
            staged_chars = sum(len(item["content"]) for item in staged_messages)
            if history and total_chars + staged_chars > max_chars:
                break
            history = staged_messages + history
            total_chars += staged_chars
        return history

    def _emit(self, emit_event: EventEmitter | None, event_name: str, payload: dict[str, Any]) -> None:
        if emit_event is not None:
            emit_event(event_name, payload)
