from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.artifacts import ArtifactStore
from app.core.config import Settings


class Phase5ResultStore:
    def __init__(self, settings: Settings, root_dir: Path | None = None) -> None:
        self.settings = settings
        self.store = ArtifactStore(root_dir or settings.phase5_dir)

    def latest_path(self, method: str, question_id: str) -> Path:
        return self.store.resolve(Path("latest") / method / f"{question_id}.json")

    def load_result(self, method: str, question_id: str) -> dict[str, Any] | None:
        path = self.latest_path(method, question_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_result(self, result: dict[str, Any]) -> dict[str, Any]:
        method = result["method"]
        question_id = result["question_id"]
        timestamp = datetime.now(UTC).isoformat()
        history_day = timestamp[:10]

        self.store.append_jsonl(Path("history") / f"{history_day}.jsonl", result)
        self.store.append_jsonl(Path("by_method") / f"{method}.jsonl", result)

        latest_path = self.latest_path(method, question_id)
        latest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def list_results(
        self,
        *,
        method: str | None = None,
        question_id: str | None = None,
    ) -> list[dict[str, Any]]:
        latest_root = self.store.resolve("latest")
        results: list[dict[str, Any]] = []
        if question_id and method:
            result = self.load_result(method, question_id)
            return [result] if result else []
        if not latest_root.exists():
            return []

        method_dirs = [latest_root / method] if method else [path for path in latest_root.iterdir() if path.is_dir()]
        for method_dir in method_dirs:
            if not method_dir.exists():
                continue
            for path in method_dir.glob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if question_id and payload.get("question_id") != question_id:
                    continue
                results.append(payload)
        results.sort(key=lambda item: (item.get("method", ""), item.get("question_id", "")))
        return results
