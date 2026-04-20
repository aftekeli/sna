from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings


class Phase4Dataset:
    def __init__(self, settings: Settings, dataset_path: Path | None = None) -> None:
        self.settings = settings
        self.dataset_path = dataset_path or settings.phase4_dataset_path
        self._records: list[dict[str, object]] | None = None
        self._index: dict[str, dict[str, object]] | None = None

    def load(self) -> list[dict[str, object]]:
        if self._records is None:
            self._records = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        return self._records

    def question_index(self) -> dict[str, dict[str, object]]:
        if self._index is None:
            self._index = {
                record["question_id"]: record
                for record in self.load()
            }
        return self._index

    def question(self, question_id: str) -> dict[str, object]:
        index = self.question_index()
        if question_id not in index:
            raise KeyError(f"Unknown question_id: {question_id}")
        return index[question_id]

    def ids(self) -> list[str]:
        return [record["question_id"] for record in self.load()]

    def list_questions(self, *, limit: int | None = None) -> list[dict[str, object]]:
        records = self.load()
        return records[:limit] if limit is not None else records
