from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: str | Path) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_json(self, relative_path: str | Path, payload: dict[str, Any]) -> Path:
        path = self.resolve(relative_path)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_json(self, relative_path: str | Path) -> dict[str, Any] | None:
        path = self.resolve(relative_path)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def append_jsonl(self, relative_path: str | Path, payload: dict[str, Any]) -> Path:
        path = self.resolve(relative_path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def iter_jsonl(self, relative_path: str | Path) -> Iterable[dict[str, Any]]:
        path = self.resolve(relative_path)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
