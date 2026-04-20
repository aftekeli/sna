from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.baselines.common import repair_text, truncate_text
from app.core.config import Settings

RELATION_TEXT = {
    "P57": "was directed by",
    "P161": "has cast member",
    "P166": "received the award",
    "P495": "has country of origin",
    "P19": "was born in",
    "P69": "studied at",
    "P17": "is located in",
    "P27": "has country of citizenship",
    "P31": "is an instance of",
}


@dataclass(slots=True)
class RetrievalDocument:
    doc_id: str
    title: str
    body: str
    source_kind: str
    source_entity_id: str | None
    metadata: dict[str, object]
    score: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "body": self.body,
            "source_kind": self.source_kind,
            "source_entity_id": self.source_entity_id,
            "metadata": self.metadata,
            "score": self.score,
            "snippet": truncate_text(self.body, limit=220),
        }


class Phase5CorpusIndex:
    def __init__(
        self,
        settings: Settings,
        *,
        entities_path: Path | None = None,
        relationships_path: Path | None = None,
        database_path: Path | None = None,
        dataset_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.entities_path = entities_path or settings.phase3_entities_path
        self.relationships_path = relationships_path or settings.phase3_relationships_path
        self.database_path = database_path or settings.phase5_retrieval_db_path
        self.dataset_path = dataset_path if dataset_path is not None else settings.phase4_dataset_path
        self.manifest_path = self.database_path.parent / "index_manifest.json"

    def ensure_built(self, *, force_rebuild: bool = False) -> dict[str, object]:
        if force_rebuild or not self.database_path.exists():
            return self.build(force_rebuild=force_rebuild)
        return self.status()

    def build(self, *, force_rebuild: bool = False) -> dict[str, object]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if force_rebuild and self.database_path.exists():
            self.database_path.unlink()

        documents = self._build_documents()
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute("DROP TABLE IF EXISTS docs")
            connection.execute(
                """
                CREATE VIRTUAL TABLE docs USING fts5(
                    doc_id UNINDEXED,
                    title,
                    body,
                    source_kind UNINDEXED,
                    source_entity_id UNINDEXED,
                    metadata_json UNINDEXED
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO docs(doc_id, title, body, source_kind, source_entity_id, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document["doc_id"],
                        document["title"],
                        document["body"],
                        document["source_kind"],
                        document["source_entity_id"],
                        json.dumps(document["metadata"], ensure_ascii=False),
                    )
                    for document in documents
                ],
            )
            connection.commit()
        finally:
            connection.close()

        manifest = {
            "database_path": str(self.database_path),
            "entity_path": str(self.entities_path),
            "relationship_path": str(self.relationships_path),
            "dataset_path": str(self.dataset_path) if self.dataset_path else None,
            "document_count": len(documents),
        }
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def search(self, query: str, *, limit: int = 6) -> list[RetrievalDocument]:
        tokenized_query = self._tokenize_query(query)
        if not tokenized_query:
            return []

        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT
                    doc_id,
                    title,
                    body,
                    source_kind,
                    source_entity_id,
                    metadata_json,
                    bm25(docs) AS rank
                FROM docs
                WHERE docs MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (tokenized_query, limit),
            ).fetchall()
        finally:
            connection.close()

        documents = []
        for row in rows:
            documents.append(
                RetrievalDocument(
                    doc_id=row["doc_id"],
                    title=row["title"],
                    body=row["body"],
                    source_kind=row["source_kind"],
                    source_entity_id=row["source_entity_id"],
                    metadata=json.loads(row["metadata_json"]),
                    score=row["rank"],
                )
            )
        return documents

    def status(self) -> dict[str, object]:
        manifest = {}
        if self.manifest_path.exists():
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        exists = self.database_path.exists()
        document_count = manifest.get("document_count")
        if exists and document_count is None:
            connection = sqlite3.connect(self.database_path)
            try:
                document_count = connection.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
            finally:
                connection.close()
        return {
            "exists": exists,
            "database_path": str(self.database_path),
            "document_count": document_count or 0,
            "manifest_path": str(self.manifest_path),
        }

    def _load_entities(self) -> dict[str, dict[str, object]]:
        entities: dict[str, dict[str, object]] = {}
        with self.entities_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                entities[row["entity_id"]] = {
                    "entity_id": row["entity_id"],
                    "canonical_name": repair_text(row["canonical_name"]),
                    "description": repair_text(row["description"]),
                    "aliases": [repair_text(alias) for alias in json.loads(row["aliases_json"])],
                    "roles": json.loads(row["roles_json"]),
                    "domains": json.loads(row["domains_json"]),
                }
        return entities

    def _build_documents(self) -> list[dict[str, object]]:
        entities = self._load_entities()
        documents: list[dict[str, object]] = []

        for entity_id, entity in entities.items():
            alias_text = ", ".join(entity["aliases"][:10])
            roles_text = ", ".join(entity["roles"])
            domains_text = ", ".join(entity["domains"])
            body = (
                f"{entity['canonical_name']}. "
                f"Description: {entity['description']} "
                f"Aliases: {alias_text}. "
                f"Roles: {roles_text}. "
                f"Domains: {domains_text}."
            ).strip()
            documents.append(
                {
                    "doc_id": f"entity::{entity_id}",
                    "title": entity["canonical_name"],
                    "body": body,
                    "source_kind": "entity_profile",
                    "source_entity_id": entity_id,
                    "metadata": {
                        "entity_id": entity_id,
                        "aliases": entity["aliases"],
                        "roles": entity["roles"],
                        "domains": entity["domains"],
                    },
                }
            )

        with self.relationships_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                source = entities.get(row["source_id"])
                target = entities.get(row["target_id"])
                if source is None or target is None:
                    continue
                relation_label = repair_text(row["relation_label"])
                verbalized_relation = RELATION_TEXT.get(row["pid"], relation_label)
                body = (
                    f"{source['canonical_name']} {verbalized_relation} {target['canonical_name']}. "
                    f"Relation type: {relation_label}. "
                    f"Source roles: {', '.join(source['roles'])}. "
                    f"Target roles: {', '.join(target['roles'])}."
                )
                documents.append(
                    {
                        "doc_id": f"fact::{row['source_id']}::{row['pid']}::{row['target_id']}",
                        "title": f"{source['canonical_name']} - {relation_label}",
                        "body": body,
                        "source_kind": "graph_fact",
                        "source_entity_id": row["source_id"],
                        "metadata": {
                            "source_id": row["source_id"],
                            "target_id": row["target_id"],
                            "relation_id": row["pid"],
                            "relation_label": relation_label,
                        },
                    }
                )

        if self.dataset_path and self.dataset_path.exists():
            documents.extend(self._build_phase4_path_documents())

        return documents

    def _tokenize_query(self, query: str) -> str:
        cleaned = repair_text(query)
        tokens = [
            token
            for token in re.findall(r"[\w]+", cleaned, flags=re.UNICODE)
            if len(token) > 1 and any(character.isalnum() for character in token)
        ]
        return " OR ".join(tokens)

    def _build_phase4_path_documents(self) -> list[dict[str, object]]:
        records = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        documents: list[dict[str, object]] = []
        seen_doc_ids: set[str] = set()
        for question_record in records:
            for index, path in enumerate(question_record.get("supporting_paths", []), start=1):
                doc_id = f"path::{question_record['question_id']}::{index}"
                if doc_id in seen_doc_ids:
                    continue
                seen_doc_ids.add(doc_id)
                sentences = []
                for triple in path.get("triples", []):
                    relation_phrase = RELATION_TEXT.get(triple["relation_id"], triple["relation_text"])
                    sentences.append(
                        f"{repair_text(triple['subject_text'])} {relation_phrase} {repair_text(triple['object_text'])}."
                    )
                documents.append(
                    {
                        "doc_id": doc_id,
                        "title": repair_text(question_record["question"]),
                        "body": " ".join(sentences),
                        "source_kind": "question_support_path",
                        "source_entity_id": question_record["seed_entities"][0]["entity_id"],
                        "metadata": {
                            "question_id": question_record["question_id"],
                            "template": question_record["template"],
                            "question_type": question_record["question_type"],
                        },
                    }
                )
        return documents
