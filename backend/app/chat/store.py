from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.artifacts import ArtifactStore, utc_now_iso
from app.core.config import Settings


class ChatSessionStore:
    def __init__(self, settings: Settings, root_dir: Path | None = None) -> None:
        self.settings = settings
        self.store = ArtifactStore(root_dir or settings.chat_runtime_dir)

    def _session_relative_path(self, session_id: str) -> Path:
        return Path("sessions") / f"{session_id}.json"

    def _history_relative_path(self) -> Path:
        return Path("history") / f"{utc_now_iso()[:10]}.jsonl"

    def create_session(self) -> dict[str, Any]:
        now = utc_now_iso()
        session = {
            "session_id": f"chat_{uuid4().hex[:12]}",
            "created_at": now,
            "updated_at": now,
            "turns": [],
            "latest_graph": None,
            "latest_evidence": None,
            "latest_turn_id": None,
            "quota_status": None,
        }
        self.save_session(session)
        self.record_event("session_created", session_id=session["session_id"], payload={"created_at": now})
        return session

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        payload = self.store.read_json(self._session_relative_path(session_id))
        if not payload:
            return None
        return payload

    def save_session(self, session: dict[str, Any]) -> dict[str, Any]:
        session = deepcopy(session)
        session["updated_at"] = utc_now_iso()
        self.store.write_json(self._session_relative_path(session["session_id"]), session)
        return session

    def add_turn(self, session_id: str, *, user_message: str, method: str) -> dict[str, Any]:
        session = self.require_session(session_id)
        now = utc_now_iso()
        turn = {
            "turn_id": f"turn_{uuid4().hex[:12]}",
            "created_at": now,
            "updated_at": now,
            "status": "running",
            "method": method,
            "user_message": user_message,
            "assistant_message": "",
            "assistant_memory_message": "",
            "error": None,
            "quota_snapshot": None,
            "evidence_graph": None,
            "evidence_panel": None,
            "answer_meta": None,
        }
        session["turns"].append(turn)
        session["latest_turn_id"] = turn["turn_id"]
        self.save_session(session)
        self.record_event(
            "turn_started",
            session_id=session_id,
            payload={"turn_id": turn["turn_id"], "method": method, "user_message": user_message},
        )
        return deepcopy(turn)

    def update_turn(
        self,
        session_id: str,
        turn_id: str,
        *,
        assistant_message: str | None = None,
        assistant_memory_message: str | None = None,
        status: str | None = None,
        error: str | None = None,
        quota_snapshot: dict[str, Any] | None = None,
        evidence_graph: dict[str, Any] | None = None,
        evidence_panel: dict[str, Any] | None = None,
        quota_status: dict[str, Any] | None = None,
        answer_meta: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        session = self.require_session(session_id)
        target_turn: dict[str, Any] | None = None
        for turn in session["turns"]:
            if turn["turn_id"] == turn_id:
                target_turn = turn
                break
        if target_turn is None:
            raise KeyError(f"Unknown turn_id: {turn_id}")

        if assistant_message is not None:
            target_turn["assistant_message"] = assistant_message
        if assistant_memory_message is not None:
            target_turn["assistant_memory_message"] = assistant_memory_message
        if status is not None:
            target_turn["status"] = status
        if error is not None:
            target_turn["error"] = error
        if quota_snapshot is not None:
            target_turn["quota_snapshot"] = quota_snapshot
        if evidence_graph is not None:
            target_turn["evidence_graph"] = evidence_graph
            session["latest_graph"] = evidence_graph
        if evidence_panel is not None:
            target_turn["evidence_panel"] = evidence_panel
            session["latest_evidence"] = evidence_panel
        if answer_meta is not None:
            target_turn["answer_meta"] = answer_meta
        if quota_status is not None:
            session["quota_status"] = quota_status
        target_turn["updated_at"] = utc_now_iso()
        session["latest_turn_id"] = turn_id
        self.save_session(session)
        self.record_event(
            "turn_updated",
            session_id=session_id,
            payload={
                "turn_id": turn_id,
                "status": target_turn["status"],
                "has_graph": evidence_graph is not None,
                "has_evidence_panel": evidence_panel is not None,
            },
        )
        return deepcopy(session), deepcopy(target_turn)

    def require_session(self, session_id: str) -> dict[str, Any]:
        session = self.load_session(session_id)
        if session is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return session

    def record_event(self, event_name: str, *, session_id: str, payload: dict[str, Any]) -> Path:
        return self.store.append_jsonl(
            self._history_relative_path(),
            {
                "timestamp": utc_now_iso(),
                "event": event_name,
                "session_id": session_id,
                "payload": payload,
            },
        )

    def export_session(self, session_id: str) -> str:
        session = self.require_session(session_id)
        return json.dumps(session, ensure_ascii=False, indent=2)
