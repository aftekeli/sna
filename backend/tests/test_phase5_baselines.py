from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.baselines.corpus import Phase5CorpusIndex
from app.baselines.results import Phase5ResultStore
from app.core.config import Settings


class Phase5BaselineInfrastructureTests(unittest.TestCase):
    def build_settings(self) -> Settings:
        return Settings(_env_file=None)

    def write_entities_csv(self, path: Path) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "entity_id",
                    "canonical_name",
                    "description",
                    "aliases_json",
                    "aliases_text",
                    "domains_json",
                    "roles_json",
                    "is_turkiye_related",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "entity_id": "QFILM",
                    "canonical_name": "Aci Zafer",
                    "description": "A Turkish film directed by Halit Refig.",
                    "aliases_json": json.dumps(["Aci Zafer"]),
                    "aliases_text": "Aci Zafer",
                    "domains_json": json.dumps(["cinema"]),
                    "roles_json": json.dumps(["film"]),
                    "is_turkiye_related": "true",
                }
            )
            writer.writerow(
                {
                    "entity_id": "QDIR",
                    "canonical_name": "Halit Refig",
                    "description": "Turkish film director.",
                    "aliases_json": json.dumps(["Halit Refig"]),
                    "aliases_text": "Halit Refig",
                    "domains_json": json.dumps(["cinema", "people"]),
                    "roles_json": json.dumps(["director"]),
                    "is_turkiye_related": "true",
                }
            )
            writer.writerow(
                {
                    "entity_id": "QPLACE",
                    "canonical_name": "Izmir",
                    "description": "Izmir is a city in Turkey.",
                    "aliases_json": json.dumps(["Izmir"]),
                    "aliases_text": "Izmir",
                    "domains_json": json.dumps(["cinema", "turkiye"]),
                    "roles_json": json.dumps(["birth_place"]),
                    "is_turkiye_related": "true",
                }
            )

    def write_relationships_csv(self, path: Path) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["source_id", "pid", "relation_label", "target_id"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "source_id": "QFILM",
                    "pid": "P57",
                    "relation_label": "director",
                    "target_id": "QDIR",
                }
            )
            writer.writerow(
                {
                    "source_id": "QDIR",
                    "pid": "P19",
                    "relation_label": "place of birth",
                    "target_id": "QPLACE",
                }
            )

    def test_corpus_index_builds_and_searches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            entities_path = root / "entities.csv"
            relationships_path = root / "relationships.csv"
            database_path = root / "baseline.sqlite3"

            self.write_entities_csv(entities_path)
            self.write_relationships_csv(relationships_path)

            index = Phase5CorpusIndex(
                self.build_settings(),
                entities_path=entities_path,
                relationships_path=relationships_path,
                database_path=database_path,
                dataset_path=root / "missing_dataset.json",
            )
            manifest = index.build()
            self.assertEqual(manifest["document_count"], 5)

            results = index.search("director of Aci Zafer", limit=3)
            self.assertGreaterEqual(len(results), 1)
            joined = " ".join(result.body for result in results)
            self.assertIn("Halit Refig", joined)

    def test_result_store_writes_latest_and_lists_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = Phase5ResultStore(self.build_settings(), root_dir=Path(tmp_dir))
            payload = {
                "created_at": "2026-04-18T00:00:00+00:00",
                "status": "success",
                "method": "no_retrieval",
                "question_id": "qa_test",
                "question": "Where was the director of Aci Zafer born?",
                "prediction_text": "Izmir",
            }
            store.save_result(payload)

            loaded = store.load_result("no_retrieval", "qa_test")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["prediction_text"], "Izmir")

            listed = store.list_results(method="no_retrieval")
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["question_id"], "qa_test")


if __name__ == "__main__":
    unittest.main()
