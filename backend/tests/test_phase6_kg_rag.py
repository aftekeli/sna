from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.baselines.corpus import RetrievalDocument
from app.core.config import Settings
from app.kg_rag.graph import GraphTriple, infer_relation_path, score_triple
from app.kg_rag.lexicon import EntityLexicon
from app.kg_rag.runner import KGInfusedRAGRunner
from app.kg_rag.store import Phase6TraceStore


class Phase6KGInfrastructureTests(unittest.TestCase):
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
                    "entity_id": "QAWARD1",
                    "canonical_name": "Devlet Sanatcisi",
                    "description": "State Artist is an award.",
                    "aliases_json": json.dumps(["Devlet Sanatcisi", "State Artist"]),
                    "aliases_text": "Devlet Sanatcisi | State Artist",
                    "domains_json": json.dumps(["cinema"]),
                    "roles_json": json.dumps(["award"]),
                    "is_turkiye_related": "true",
                }
            )
            writer.writerow(
                {
                    "entity_id": "QFILM1",
                    "canonical_name": "Aci Zafer",
                    "description": "A Turkish film.",
                    "aliases_json": json.dumps(["Aci Zafer", "Acı Zafer"]),
                    "aliases_text": "Aci Zafer | Acı Zafer",
                    "domains_json": json.dumps(["cinema"]),
                    "roles_json": json.dumps(["film"]),
                    "is_turkiye_related": "true",
                }
            )
            writer.writerow(
                {
                    "entity_id": "QFILM2",
                    "canonical_name": "Arabesk",
                    "description": "A Turkish film.",
                    "aliases_json": json.dumps(["Arabesk"]),
                    "aliases_text": "Arabesk",
                    "domains_json": json.dumps(["cinema"]),
                    "roles_json": json.dumps(["film"]),
                    "is_turkiye_related": "true",
                }
            )

    def test_lexicon_matches_multiple_films_in_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            entities_path = Path(tmp_dir) / "entities.csv"
            self.write_entities_csv(entities_path)
            lexicon = EntityLexicon(self.build_settings(), entities_path=entities_path)
            matches = lexicon.match_question(
                "Were the directors of Aci Zafer and Arabesk born in the same country?",
                limit=4,
            )
            matched_ids = [match.entity_id for match in matches]
            self.assertIn("QFILM1", matched_ids)
            self.assertIn("QFILM2", matched_ids)

    def test_relation_path_inference_prefers_director_birth_country(self) -> None:
        relation_path = infer_relation_path(
            "Were the directors of Aci Zafer and Arabesk born in the same country?"
        )
        self.assertEqual(relation_path, ["P57", "P19", "P17"])

    def test_relation_path_inference_supports_turkish_birth_question(self) -> None:
        relation_path = infer_relation_path("Kemal Sunal nerede dogmustur?")
        self.assertEqual(relation_path, ["P19"])

    def test_country_root_is_scored_above_historical_country(self) -> None:
        modern_country = GraphTriple(
            source_id="QCITY1",
            source_name="Izmir",
            source_roles=["birth_place"],
            relation_id="P17",
            relation_label="country",
            target_id="Q43",
            target_name="Turkey",
            target_roles=["country", "country_root"],
        )
        historical_country = GraphTriple(
            source_id="QCITY1",
            source_name="Izmir",
            source_roles=["birth_place"],
            relation_id="P17",
            relation_label="country",
            target_id="Q12560",
            target_name="Ottoman Empire",
            target_roles=["country"],
        )
        modern_score = score_triple(
            modern_country,
            question_text="Were they born in the same country?",
            preferred_path=["P57", "P19", "P17"],
            round_index=2,
            visited_targets=set(),
        )
        historical_score = score_triple(
            historical_country,
            question_text="Were they born in the same country?",
            preferred_path=["P57", "P19", "P17"],
            round_index=2,
            visited_targets=set(),
        )
        self.assertGreater(modern_score, historical_score)

    def test_trace_store_persists_latest_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = Phase6TraceStore(self.build_settings(), root_dir=Path(tmp_dir))
            payload = {
                "created_at": "2026-04-18T00:00:00+00:00",
                "status": "success",
                "method": "kg_infused_rag",
                "question_id": "qa_test",
                "question": "Where was the director of Aci Zafer born?",
                "prediction_text": "Izmir",
            }
            store.save_trace(payload)
            loaded = store.load_trace("qa_test")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["prediction_text"], "Izmir")

    def test_preferred_answer_name_uses_context_friendly_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            entities_path = Path(tmp_dir) / "entities.csv"
            self.write_entities_csv(entities_path)
            lexicon = EntityLexicon(self.build_settings(), entities_path=entities_path)
            preferred = lexicon.preferred_answer_name(
                "QAWARD1",
                context_texts=["Osman Seden received the award State Artist."],
            )
            self.assertEqual(preferred, "State Artist")

    def test_structured_answer_derives_final_entity_for_two_hop_question(self) -> None:
        runner = KGInfusedRAGRunner(self.build_settings())
        structured_answer = runner._derive_structured_answer(
            relation_path=["P57", "P19"],
            seeds=[{"entity_id": "QFILM1", "entity_name": "Aci Zafer"}],
            selected_triples=[
                {
                    "source_id": "QFILM1",
                    "source_name": "Aci Zafer",
                    "relation_id": "P57",
                    "relation_label": "director",
                    "target_id": "QDIR1",
                    "target_name": "Halit Refig",
                },
                {
                    "source_id": "QDIR1",
                    "source_name": "Halit Refig",
                    "relation_id": "P19",
                    "relation_label": "place of birth",
                    "target_id": "QCITY1",
                    "target_name": "Izmir",
                },
            ],
            question_type="two_hop",
        )
        self.assertEqual(structured_answer["answer_text"], "Izmir")
        self.assertEqual(structured_answer["candidate_entity_ids"], ["QCITY1"])

    def test_structured_answer_derives_yes_no_for_comparison(self) -> None:
        runner = KGInfusedRAGRunner(self.build_settings())
        structured_answer = runner._derive_structured_answer(
            relation_path=["P57", "P19", "P17"],
            seeds=[
                {"entity_id": "QFILM1", "entity_name": "Aci Zafer"},
                {"entity_id": "QFILM2", "entity_name": "Arabesk"},
            ],
            selected_triples=[
                {
                    "source_id": "QFILM1",
                    "source_name": "Aci Zafer",
                    "relation_id": "P57",
                    "relation_label": "director",
                    "target_id": "QDIR1",
                    "target_name": "Director One",
                },
                {
                    "source_id": "QDIR1",
                    "source_name": "Director One",
                    "relation_id": "P19",
                    "relation_label": "place of birth",
                    "target_id": "QCITY1",
                    "target_name": "Izmir",
                },
                {
                    "source_id": "QCITY1",
                    "source_name": "Izmir",
                    "relation_id": "P17",
                    "relation_label": "country",
                    "target_id": "QCOUNTRY1",
                    "target_name": "Turkey",
                },
                {
                    "source_id": "QFILM2",
                    "source_name": "Arabesk",
                    "relation_id": "P57",
                    "relation_label": "director",
                    "target_id": "QDIR2",
                    "target_name": "Director Two",
                },
                {
                    "source_id": "QDIR2",
                    "source_name": "Director Two",
                    "relation_id": "P19",
                    "relation_label": "place of birth",
                    "target_id": "QCITY2",
                    "target_name": "Ankara",
                },
                {
                    "source_id": "QCITY2",
                    "source_name": "Ankara",
                    "relation_id": "P17",
                    "relation_label": "country",
                    "target_id": "QCOUNTRY1",
                    "target_name": "Turkey",
                },
            ],
            question_type="comparison",
        )
        self.assertEqual(structured_answer["answer_text"], "yes")

    def test_adjust_relation_path_drops_cast_member_hop_for_cast_entity_seeds(self) -> None:
        runner = KGInfusedRAGRunner(self.build_settings())
        adjusted_path = runner._adjust_relation_path(
            ["P161", "P19", "P17"],
            template="film_cast_birth_place_country",
            seeds=[{"entity_id": "QCAST1", "roles": ["cast_member"]}],
        )
        self.assertEqual(adjusted_path, ["P19", "P17"])

    def test_spreading_activation_stops_when_expected_relation_is_missing(self) -> None:
        runner = KGInfusedRAGRunner(self.build_settings())
        runner.lexicon.display_name = lambda entity_id, fallback_name=None: fallback_name or entity_id  # type: ignore[method-assign]

        class _FakeGraph:
            def fetch_outgoing_triples(self, entity_id: str, *, limit: int = 20) -> list[GraphTriple]:
                return [
                    GraphTriple(
                        source_id=entity_id,
                        source_name="Kemal Sunal",
                        source_roles=["cast_member"],
                        relation_id="P166",
                        relation_label="award received",
                        target_id="QAWARD1",
                        target_name="Golden Orange",
                        target_roles=["award"],
                    )
                ]

        runner.graph = _FakeGraph()  # type: ignore[assignment]
        rounds = runner._spreading_activation(
            question_text="Kemal Sunal nerede dogmustur?",
            relation_path=["P19"],
            seeds=[{"entity_id": "Q735585", "entity_name": "Kemal Sunal", "roles": ["cast_member"]}],
            max_rounds=2,
        )
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0]["selected_triples"], [])

    def test_path_document_answer_extracts_final_surface_form(self) -> None:
        runner = KGInfusedRAGRunner(self.build_settings())
        answer_text = runner._path_document_answer(
            question_id="qa_test",
            relation_path=["P57", "P166"],
            retrieved_documents=[
                RetrievalDocument(
                    doc_id="path::qa_test::1",
                    title="Which award was received by the director of Bir Avuc Toprak?",
                    body="Bir Avuc Toprak was directed by Osman Seden. Osman Seden received the award State Artist.",
                    source_kind="question_support_path",
                    source_entity_id="QFILM1",
                    metadata={"question_id": "qa_test"},
                )
            ],
        )
        self.assertEqual(answer_text, "State Artist")

    def test_answer_meta_explains_missing_relation_in_friendly_text(self) -> None:
        runner = KGInfusedRAGRunner(self.build_settings())
        answer_meta = runner._build_answer_meta(
            canonical_answer="unknown",
            question_text="Kemal Sunal nerede dogmustur?",
            question_type="two_hop",
            seeds=[{"entity_id": "Q735585", "entity_name": "Kemal Sunal"}],
            relation_path=["P19"],
            selected_triples=[],
            structured_answer={"candidate_texts": [], "answer_text": None},
            activation_rounds=[{"round_index": 1, "selected_triples": []}],
        )
        self.assertEqual(answer_meta["reason_code"], "relation_missing")
        self.assertIn("Kemal Sunal", answer_meta["display_text"])
        self.assertIn("birthplace", answer_meta["display_text"])

    def test_run_freeform_returns_trace_for_live_question(self) -> None:
        runner = KGInfusedRAGRunner(self.build_settings())
        runner._select_seeds = lambda *args, **kwargs: [  # type: ignore[method-assign]
            {
                "entity_id": "QFILM1",
                "entity_name": "Aci Zafer",
                "roles": ["film"],
                "source": "lexicon",
                "score": 20.0,
            }
        ]
        runner._spreading_activation = lambda **kwargs: [  # type: ignore[method-assign]
            {
                "round_index": 1,
                "frontier_entity_ids": ["QFILM1"],
                "candidate_count": 1,
                "selected_triples": [
                    {
                        "source_id": "QFILM1",
                        "source_name": "Aci Zafer",
                        "source_roles": ["film"],
                        "relation_id": "P57",
                        "relation_label": "director",
                        "target_id": "QDIR1",
                        "target_name": "Halit Refig",
                        "target_roles": ["director"],
                        "score": 12.0,
                    }
                ],
            },
            {
                "round_index": 2,
                "frontier_entity_ids": ["QDIR1"],
                "candidate_count": 1,
                "selected_triples": [
                    {
                        "source_id": "QDIR1",
                        "source_name": "Halit Refig",
                        "source_roles": ["director"],
                        "relation_id": "P19",
                        "relation_label": "place of birth",
                        "target_id": "QCITY1",
                        "target_name": "Izmir",
                        "target_roles": ["birth_place"],
                        "score": 11.0,
                    }
                ],
            },
        ]
        runner._expand_query = lambda **kwargs: ("aci zafer director birth place", {"remaining_requests": 900})  # type: ignore[method-assign]
        runner._answer_question = lambda **kwargs: (  # type: ignore[method-assign]
            "Izmir",
            {"remaining_requests": 899},
            {
                "status": "answered",
                "reason_code": "answered",
                "confidence": "high",
                "canonical_answer": "Izmir",
                "display_text": "Izmir",
                "memory_text": "Izmir",
            },
        )

        class _FakeCorpus:
            def ensure_built(self) -> dict[str, object]:
                return {"document_count": 1}

            def search(self, query: str, *, limit: int = 6) -> list[RetrievalDocument]:
                self.last_query = query
                return [
                    RetrievalDocument(
                        doc_id="entity::QDIR1",
                        title="Halit Refig",
                        body="Halit Refig was born in Izmir.",
                        source_kind="entity_profile",
                        source_entity_id="QDIR1",
                        metadata={"entity_id": "QDIR1"},
                    )
                ]

        runner.corpus = _FakeCorpus()  # type: ignore[assignment]

        trace = runner.run_freeform(
            question_text="Where was the director of Aci Zafer born?",
            conversation_history=[
                {"role": "user", "content": "Let's stay in Turkish cinema."},
                {"role": "assistant", "content": "Ready for a live KG-RAG question."},
            ],
            turn_id="turn_live",
        )

        self.assertEqual(trace["status"], "success")
        self.assertEqual(trace["prediction_text"], "Izmir")
        self.assertEqual(trace["display_text"], "Izmir")
        self.assertEqual(trace["question_type"], "two_hop")
        self.assertEqual(trace["seed_entities"][0]["entity_name"], "Aci Zafer")
        self.assertGreaterEqual(len(trace["cypher_queries"]), 2)
        self.assertEqual(trace["cypher_queries"][0]["label"], "Expand from Aci Zafer")
        self.assertIn("canonical_name: 'Aci Zafer'", trace["cypher_queries"][0]["query"])
        graph = runner.build_evidence_graph(trace)
        self.assertGreaterEqual(len(graph["nodes"]), 2)
        self.assertEqual(graph["active_node_id"], "QCITY1")

    def test_history_for_question_skips_explicit_standalone_question(self) -> None:
        runner = KGInfusedRAGRunner(self.build_settings())
        history = runner._history_for_question(
            "Where was the director of Aci Zafer born?",
            [
                {"role": "user", "content": "Tell me about Arabesk."},
                {"role": "assistant", "content": "It was directed by Ertem Egilmez."},
            ],
        )
        self.assertEqual(history, [])

    def test_history_for_question_keeps_follow_up_pronoun_question(self) -> None:
        runner = KGInfusedRAGRunner(self.build_settings())
        history = runner._history_for_question(
            "Where was he born?",
            [
                {"role": "user", "content": "Tell me about Halit Refig."},
                {"role": "assistant", "content": "He directed Aci Zafer."},
            ],
        )
        self.assertEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
