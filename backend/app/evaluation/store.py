from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.artifacts import ArtifactStore
from app.core.config import Settings


class Phase7EvaluationStore:
    def __init__(self, settings: Settings, root_dir: Path | None = None) -> None:
        self.settings = settings
        self.store = ArtifactStore(root_dir or settings.phase7_dir)

    def latest_path(self, name: str) -> Path:
        return self.store.resolve(Path("latest") / name)

    def save_latest(self, name: str, payload: dict[str, Any]) -> Path:
        path = self.latest_path(name)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_latest(self, name: str) -> dict[str, Any] | None:
        path = self.latest_path(name)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def append_history(self, payload: dict[str, Any]) -> Path:
        created_at = str(payload.get("created_at", ""))
        history_day = created_at[:10] if created_at else "unknown"
        return self.store.append_jsonl(Path("history") / f"{history_day}.jsonl", payload)
