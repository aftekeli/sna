from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.artifacts import ArtifactStore
from app.core.config import Settings


class Phase6TraceStore:
    def __init__(self, settings: Settings, root_dir: Path | None = None) -> None:
        self.settings = settings
        self.store = ArtifactStore(root_dir or settings.phase6_dir)

    def latest_path(self, question_id: str) -> Path:
        return self.store.resolve(Path("latest") / f"{question_id}.json")

    def load_trace(self, question_id: str) -> dict[str, Any] | None:
        path = self.latest_path(question_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        question_id = trace["question_id"]
        created_at = trace["created_at"]
        history_day = created_at[:10]
        self.store.append_jsonl(Path("history") / f"{history_day}.jsonl", trace)
        latest_path = self.latest_path(question_id)
        latest_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        return trace

    def list_traces(self, *, question_id: str | None = None) -> list[dict[str, Any]]:
        latest_root = self.store.resolve("latest")
        if question_id:
            trace = self.load_trace(question_id)
            return [trace] if trace else []
        if not latest_root.exists():
            return []
        traces = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in latest_root.glob("*.json")
        ]
        traces.sort(key=lambda item: item.get("question_id", ""))
        return traces
