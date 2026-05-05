from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.baselines.common import (
    extract_chat_text,
    heuristic_match,
    normalize_for_match,
    repair_text,
    truncate_text,
)
from app.baselines.corpus import RELATION_TEXT, Phase5CorpusIndex, RetrievalDocument
from app.baselines.dataset import Phase4Dataset
from app.core.artifacts import utc_now_iso
from app.core.config import Settings
from app.kg_rag.graph import (
    Neo4jGraphExplorer,
    GraphTriple,
    group_triples_by_source,
    infer_relation_path,
    score_triple,
)
from app.kg_rag.lexicon import EntityLexicon
from app.kg_rag.store import Phase6TraceStore
from app.providers import get_provider_registry
from app.providers.groq_provider import GroqActionBlockedError, GroqRateLimitedError


@dataclass(slots=True)
class KGRunContext:
    question: dict[str, Any]
    top_k: int
    max_rounds: int
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    emit_event: Callable[[str, dict[str, Any]], None] | None = None


class KGInfusedRAGRunner:
    """Executes KG-guided retrieval, evidence tracing, and answer generation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = get_provider_registry(settings)
        self.dataset = Phase4Dataset(settings)
        self.corpus = Phase5CorpusIndex(settings)
        self.lexicon = EntityLexicon(settings)
        self.graph = Neo4jGraphExplorer(self.registry.neo4j)
        self.store = Phase6TraceStore(settings)

    def list_questions(self, *, limit: int | None = None) -> list[dict[str, object]]:
        records = self.dataset.list_questions(limit=limit)
        return [
            {
                "question_id": record["question_id"],
                "question": record["question"],
                "question_type": record["question_type"],
                "template": record["template"],
                "gold_answer": record["gold_answer"]["text"],
            }
            for record in records
        ]

    def run_question(
        self,
        *,
        question_id: str,
        top_k: int = 6,
        max_rounds: int | None = None,
        skip_existing: bool = True,
    ) -> dict[str, object]:
        existing = self.store.load_trace(question_id)
        if existing and skip_existing and existing.get("status") == "success":
            return {"status": "skipped_existing", "result": existing}

        question = self.dataset.question(question_id)
        context = KGRunContext(
            question=question,
            top_k=top_k,
            max_rounds=max_rounds or max(2, int(question["hop_count"])),
        )

        try:
            trace = self._run(context)
        except (GroqActionBlockedError, GroqRateLimitedError) as exc:
            trace = self._failed_trace(context, status="paused", message=str(exc))
        except Exception as exc:  # pragma: no cover - runtime integration catch
            trace = self._failed_trace(context, status="error", message=str(exc))

        self.store.save_trace(trace)
        return {"status": trace["status"], "result": trace}

    def run_dataset(
        self,
        *,
        question_ids: list[str] | None = None,
        limit: int | None = None,
        top_k: int = 6,
        max_rounds: int | None = None,
        skip_existing: bool = True,
    ) -> dict[str, object]:
        selected_question_ids = question_ids or self.dataset.ids()
        if limit is not None:
            selected_question_ids = selected_question_ids[:limit]

        results: list[dict[str, object]] = []
        stop_reason: str | None = None
        for question_id in selected_question_ids:
            execution = self.run_question(
                question_id=question_id,
                top_k=top_k,
                max_rounds=max_rounds,
                skip_existing=skip_existing,
            )
            results.append({"question_id": question_id, "status": execution["status"]})
            if execution["status"] == "paused":
                stop_reason = "groq_paused_for_rest_of_day"
                break

        return {
            "status": "paused" if stop_reason else "completed",
            "stop_reason": stop_reason,
            "attempted_runs": len(results),
            "results": results,
        }

    def get_results(self, *, question_id: str | None = None) -> list[dict[str, object]]:
        return self.store.list_traces(question_id=question_id)

    def run_freeform(
        self,
        *,
        question_text: str,
        conversation_history: list[dict[str, str]] | None = None,
        turn_id: str,
        top_k: int = 6,
        max_rounds: int | None = None,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, object]:
        normalized_question_type = self._infer_freeform_question_type(question_text)
        history_for_turn = self._history_for_question(question_text, conversation_history or [])
        relation_path = infer_relation_path(self._grounding_text(question_text, history_for_turn))
        context = KGRunContext(
            question={
                "question_id": turn_id,
                "question": question_text,
                "question_type": normalized_question_type,
                "template": "live_freeform",
                "difficulty": "live",
                "gold_answer": {"text": ""},
            },
            top_k=top_k,
            max_rounds=max_rounds or self._infer_freeform_max_rounds(relation_path),
            conversation_history=history_for_turn,
            emit_event=emit_event,
        )

        try:
            return self._run(context)
        except (GroqActionBlockedError, GroqRateLimitedError) as exc:
            return self._failed_trace(context, status="paused", message=str(exc))
        except Exception as exc:  # pragma: no cover - runtime integration catch
            return self._failed_trace(context, status="error", message=str(exc))

    def _run(self, context: KGRunContext) -> dict[str, object]:
        question_text = context.question["question"]
        grounding_text = self._grounding_text(question_text, context.conversation_history)
        neo4j_trace_queries: list[dict[str, object]] = []
        seed_candidates = self._select_seeds(
            grounding_text,
            question_type=context.question["question_type"],
            template=context.question["template"],
        )
        self._emit_event(
            context,
            "seed_entities",
            {
                "seed_entities": [seed for seed in seed_candidates],
                "graph": self._build_graph_patch(seed_candidates, []),
            },
        )
        relation_path = self._adjust_relation_path(
            infer_relation_path(grounding_text),
            template=context.question["template"],
            seeds=seed_candidates,
        )
        rounds = self._spreading_activation(
            question_text=grounding_text,
            relation_path=relation_path,
            seeds=seed_candidates,
            max_rounds=context.max_rounds,
            query_trace=neo4j_trace_queries,
        )
        selected_triples = [
            triple
            for round_payload in rounds
            for triple in round_payload["selected_triples"]
        ]
        cypher_queries = neo4j_trace_queries or self._reconstruct_live_neo4j_trace(
            seeds=seed_candidates,
            rounds=rounds,
        )
        selected_triples_so_far: list[dict[str, object]] = []
        for round_payload in rounds:
            selected_triples_so_far.extend(round_payload["selected_triples"])
            self._emit_event(
                context,
                "activation_round",
                {"round": round_payload},
            )
            self._emit_event(
                context,
                "graph_patch",
                {"graph": self._build_graph_patch(seed_candidates, selected_triples_so_far)},
            )
        structured_answer = self._derive_structured_answer(
            relation_path=relation_path,
            seeds=seed_candidates,
            selected_triples=selected_triples,
            question_type=context.question["question_type"],
        )
        kg_summary = self._build_kg_summary(selected_triples)
        expanded_query, expansion_snapshot = self._expand_query(
            question_id=context.question["question_id"],
            question_text=question_text,
            kg_summary=kg_summary,
            conversation_history=context.conversation_history,
        )
        self._emit_event(
            context,
            "expanded_query",
            {"expanded_query": expanded_query},
        )
        self._emit_event(
            context,
            "cypher_trace",
            {"cypher_queries": cypher_queries},
        )
        self.corpus.ensure_built()
        retrieved_documents = self.corpus.search(expanded_query, limit=context.top_k)
        serialized_documents = [document.to_dict() for document in retrieved_documents]
        self._emit_event(
            context,
            "retrieved_documents",
            {"retrieved_documents": serialized_documents},
        )
        answer_text, answer_snapshot, answer_meta = self._answer_question(
            question_id=context.question["question_id"],
            question_text=question_text,
            kg_summary=kg_summary,
            relation_path=relation_path,
            selected_triples=selected_triples,
            structured_answer=structured_answer,
            retrieved_documents=retrieved_documents,
            question_type=context.question["question_type"],
            conversation_history=context.conversation_history,
            seeds=seed_candidates,
            activation_rounds=rounds,
        )
        display_answer = str(answer_meta.get("display_text") or answer_text or "").strip()
        accumulated_answer = ""
        for chunk in self._chunk_answer(display_answer):
            accumulated_answer += chunk
            self._emit_event(
                context,
                "answer_delta",
                {
                    "delta": chunk,
                    "assistant_message": accumulated_answer,
                },
            )
        match = heuristic_match(answer_text, context.question["gold_answer"]["text"])
        trace = {
            "created_at": utc_now_iso(),
            "status": "success",
            "method": "kg_infused_rag",
            "question_id": context.question["question_id"],
            "question": question_text,
            "question_type": context.question["question_type"],
            "template": context.question["template"],
            "difficulty": context.question["difficulty"],
            "gold_answer": context.question["gold_answer"],
            "prediction_text": answer_text,
            "display_text": display_answer,
            "answer_meta": answer_meta,
            "match": match,
            "seed_entities": [seed for seed in seed_candidates],
            "relation_path": relation_path,
            "activation_rounds": rounds,
            "structured_answer": structured_answer,
            "kg_summary": kg_summary,
            "expanded_query": expanded_query,
            "retrieved_documents": serialized_documents,
            "cypher_queries": cypher_queries,
            "session_memory_used": bool(context.conversation_history),
            "quota_snapshot": {
                "query_expansion": expansion_snapshot,
                "answer_generation": answer_snapshot,
            },
            "provider": {"name": "groq", "model": self.settings.groq_model},
        }
        self._emit_event(
            context,
            "graph_patch",
            {"graph": self.build_evidence_graph(trace)},
        )
        return trace

    def _select_seeds(
        self,
        question_text: str,
        *,
        question_type: str,
        template: str,
    ) -> list[dict[str, object]]:
        lexicon_matches = self.lexicon.match_question(question_text, limit=4)
        if template.startswith("film_cast"):
            cast_matches = [match for match in lexicon_matches if "cast_member" in match.roles]
            if cast_matches:
                lexicon_matches = cast_matches
                max_seed_count = 2 if question_type == "comparison" else 1
            else:
                max_seed_count = 2 if question_type == "comparison" else 1
        elif question_type == "comparison":
            max_seed_count = 2
        else:
            max_seed_count = 1

        seeds: dict[str, dict[str, object]] = {}
        for match in lexicon_matches:
            seeds[match.entity_id] = {
                "entity_id": match.entity_id,
                "entity_name": self.lexicon.display_name(match.entity_id, fallback_name=match.canonical_name),
                "roles": match.roles,
                "source": "lexicon",
                "score": match.score,
            }

        if len(seeds) < max_seed_count:
            fulltext_matches = self.graph.fulltext_search(question_text, limit=6)
            for row in fulltext_matches:
                entity_id = row["entity_id"]
                existing = seeds.get(entity_id)
                fulltext_score = float(row["score"])
                if existing is None or fulltext_score > float(existing["score"]):
                    seeds[entity_id] = {
                        "entity_id": entity_id,
                        "entity_name": self.lexicon.display_name(
                            entity_id,
                            fallback_name=repair_text(row["canonical_name"]),
                        ),
                        "roles": row.get("roles") or [],
                        "source": "neo4j_fulltext",
                        "score": fulltext_score,
                    }

        ordered = sorted(
            seeds.values(),
            key=lambda item: (-float(item["score"]), item["entity_name"].casefold(), item["entity_id"]),
        )
        return ordered[:max_seed_count]

    def _adjust_relation_path(
        self,
        relation_path: list[str],
        *,
        template: str,
        seeds: list[dict[str, object]],
    ) -> list[str]:
        adjusted_path = list(relation_path)
        if not adjusted_path:
            return adjusted_path
        if template.startswith("film_cast") and adjusted_path[0] == "P161":
            if seeds and all("cast_member" in (seed.get("roles") or []) for seed in seeds):
                return adjusted_path[1:]
        return adjusted_path

    def _spreading_activation(
        self,
        *,
        question_text: str,
        relation_path: list[str],
        seeds: list[dict[str, object]],
        max_rounds: int,
        query_trace: list[dict[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        frontier = [seed["entity_id"] for seed in seeds]
        visited = set(frontier)
        rounds: list[dict[str, object]] = []
        entity_context: dict[str, dict[str, object]] = {
            str(seed["entity_id"]): {
                "entity_name": str(seed["entity_name"]),
                "roles": list(seed.get("roles") or []),
            }
            for seed in seeds
        }

        for round_index in range(max_rounds):
            candidate_triples: list[GraphTriple] = []
            for entity_id in frontier:
                triples = self.graph.fetch_outgoing_triples(entity_id, limit=20)
                source_context = entity_context.get(entity_id, {})
                if query_trace is not None:
                    source_name = str(
                        source_context.get("entity_name")
                        or (triples[0].source_name if triples else entity_id)
                    )
                    source_roles = list(
                        source_context.get("roles")
                        or (triples[0].source_roles if triples else [])
                    )
                    query_trace.append(
                        self._build_outgoing_query_trace(
                            entity_id=entity_id,
                            entity_name=source_name,
                            roles=source_roles,
                            limit=20,
                        )
                    )
                for triple in triples:
                    triple.source_name = self.lexicon.display_name(triple.source_id, fallback_name=triple.source_name)
                    triple.target_name = self.lexicon.display_name(triple.target_id, fallback_name=triple.target_name)
                candidate_triples.extend(triples)

            if not candidate_triples:
                break

            scored_triples = []
            for triple in candidate_triples:
                triple.score = score_triple(
                    triple,
                    question_text=question_text,
                    preferred_path=relation_path,
                    round_index=round_index,
                    visited_targets=visited,
                )
                scored_triples.append(triple)

            scored_triples.sort(key=lambda item: (-item.score, item.target_name.casefold(), item.target_id))
            selected_triples: list[GraphTriple] = []
            next_frontier: list[str] = []
            seen_pairs: set[tuple[str, str]] = set()
            expected_relation = relation_path[round_index] if round_index < len(relation_path) else None
            if expected_relation:
                matching_relation_triples = [
                    triple for triple in scored_triples if triple.relation_id == expected_relation
                ]
                if not matching_relation_triples:
                    rounds.append(
                        {
                            "round_index": round_index + 1,
                            "frontier_entity_ids": frontier,
                            "candidate_count": len(candidate_triples),
                            "selected_triples": [],
                        }
                    )
                    break
                scored_triples = matching_relation_triples

            triples_by_source = group_triples_by_source(scored_triples)
            for source_id in frontier:
                source_triples = sorted(
                    triples_by_source.get(source_id, []),
                    key=lambda item: (-item.score, item.target_name.casefold(), item.target_id),
                )
                for triple in source_triples:
                    if triple.score <= 0:
                        continue
                    if (source_id, triple.target_id) in seen_pairs or triple.target_id in visited:
                        continue
                    selected_triples.append(triple)
                    seen_pairs.add((source_id, triple.target_id))
                    next_frontier.append(triple.target_id)
                    break

            rounds.append(
                {
                    "round_index": round_index + 1,
                    "frontier_entity_ids": frontier,
                    "candidate_count": len(candidate_triples),
                    "selected_triples": [triple.to_dict() for triple in selected_triples],
                }
            )

            for triple in selected_triples:
                entity_context[triple.target_id] = {
                    "entity_name": triple.target_name,
                    "roles": list(triple.target_roles or []),
                }

            if not next_frontier:
                break
            visited.update(next_frontier)
            frontier = next_frontier
            if relation_path and round_index + 1 >= len(relation_path):
                break

        return rounds

    def _cypher_literal(self, value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

    def _alias_for_roles(self, roles: list[str] | None, *, fallback: str = "entity") -> str:
        normalized = {str(role).casefold() for role in (roles or [])}
        if "film" in normalized:
            return "film"
        if "director" in normalized:
            return "director"
        if "cast_member" in normalized:
            return "cast_member"
        if "birth_place" in normalized or "place" in normalized:
            return "place"
        if "school" in normalized or "education_entity" in normalized:
            return "school"
        if "award" in normalized:
            return "award"
        if "country" in normalized or "country_root" in normalized:
            return "country"
        if "person" in normalized:
            return "person"
        return fallback

    def _build_outgoing_query_trace(
        self,
        *,
        entity_id: str,
        entity_name: str,
        roles: list[str] | None,
        limit: int,
    ) -> dict[str, object]:
        source_alias = self._alias_for_roles(roles, fallback="entity")
        readable_query = (
            f"MATCH ({source_alias}:Entity {{canonical_name: {self._cypher_literal(entity_name)}}})"
            "-[relation:REL]->(neighbor:Entity)\n"
            "RETURN\n"
            f"    {source_alias}.canonical_name AS source_name,\n"
            "    relation.label AS relation_label,\n"
            "    neighbor.canonical_name AS target_name\n"
            f"LIMIT {limit}"
        )
        technical_query = (
            "MATCH (source:Entity {entity_id: $entity_id})-[r:REL]->(target:Entity)\n"
            "RETURN\n"
            "    source.entity_id AS source_id,\n"
            "    source.canonical_name AS source_name,\n"
            "    source.roles AS source_roles,\n"
            "    r.pid AS relation_id,\n"
            "    r.label AS relation_label,\n"
            "    target.entity_id AS target_id,\n"
            "    target.canonical_name AS target_name,\n"
            "    target.roles AS target_roles\n"
            "LIMIT $limit"
        )
        return {
            "label": f"Expand from {entity_name}",
            "purpose": "Fetch outgoing Neo4j relationships from the active node during KG spreading activation.",
            "query": readable_query,
            "readable_query": readable_query,
            "technical_query": technical_query,
            "parameters": {"entity_id": entity_id, "limit": limit},
        }

    def _reconstruct_live_neo4j_trace(
        self,
        *,
        seeds: list[dict[str, object]],
        rounds: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        entity_context: dict[str, dict[str, object]] = {
            str(seed["entity_id"]): {
                "entity_name": str(seed["entity_name"]),
                "roles": list(seed.get("roles") or []),
            }
            for seed in seeds
        }
        trace_queries: list[dict[str, object]] = []
        seen_entities: set[str] = set()

        for round_payload in rounds:
            for entity_id in round_payload.get("frontier_entity_ids", []):
                entity_key = str(entity_id)
                if entity_key in seen_entities:
                    continue
                seen_entities.add(entity_key)
                context = entity_context.get(entity_key, {})
                trace_queries.append(
                    self._build_outgoing_query_trace(
                        entity_id=entity_key,
                        entity_name=str(context.get("entity_name") or entity_key),
                        roles=list(context.get("roles") or []),
                        limit=20,
                    )
                )
            for triple in round_payload.get("selected_triples", []):
                entity_context[str(triple["target_id"])] = {
                    "entity_name": str(triple["target_name"]),
                    "roles": list(triple.get("target_roles") or []),
                }

        return trace_queries

    def _build_kg_summary(self, selected_triples: list[dict[str, object]]) -> str:
        if not selected_triples:
            return "No confident KG triples were selected."
        sentences = [
            f"{triple['source_name']} {RELATION_TEXT.get(triple['relation_id'], triple['relation_label'])} {triple['target_name']}."
            for triple in selected_triples
        ]
        return " ".join(sentences)

    def build_chat_evidence_panel(self, trace: dict[str, object]) -> dict[str, object]:
        answer_meta = trace.get("answer_meta", {}) or {}
        seed_entities = [
            {
                "entity_id": seed["entity_id"],
                "entity_name": seed["entity_name"],
                "roles": seed.get("roles") or [],
                "source": seed.get("source"),
            }
            for seed in trace.get("seed_entities", [])
        ]
        selected_triples = [
            {
                "source_name": triple["source_name"],
                "relation_label": triple["relation_label"],
                "target_name": triple["target_name"],
                "relation_id": triple["relation_id"],
            }
            for round_payload in trace.get("activation_rounds", [])
            for triple in round_payload.get("selected_triples", [])
        ]
        answer_basis = (
            trace.get("structured_answer", {}).get("answer_text")
            or answer_meta.get("display_text")
            or trace.get("kg_summary")
        )
        return {
            "seed_entities": seed_entities,
            "selected_triples": selected_triples,
            "expanded_query": trace.get("expanded_query"),
            "cypher_queries": trace.get("cypher_queries", []),
            "retrieved_documents": trace.get("retrieved_documents", []),
            "answer_basis": answer_basis,
            "answer_meta": answer_meta,
        }

    def _build_cypher_queries(
        self,
        *,
        question_text: str,
        relation_path: list[str],
        seeds: list[dict[str, object]],
        selected_triples: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        seed_ids = [str(seed["entity_id"]) for seed in seeds]
        seed_lookup_query = {
            "label": "Seed lookup",
            "purpose": "Find the most relevant starting entities from the question text.",
            "query": (
                "CALL db.index.fulltext.queryNodes('entity_text_search', $query_text)\n"
                "YIELD node, score\n"
                "RETURN node.entity_id AS entity_id,\n"
                "       node.canonical_name AS canonical_name,\n"
                "       node.roles AS roles,\n"
                "       score\n"
                "ORDER BY score DESC\n"
                "LIMIT $limit"
            ),
            "parameters": {"query_text": question_text, "limit": 6},
        }
        if not seed_ids:
            return [seed_lookup_query]

        relation_steps = relation_path or [
            str(triple["relation_id"])
            for triple in selected_triples
            if triple.get("relation_id")
        ]
        relation_steps = self._dedupe_values(relation_steps)
        if relation_steps:
            path_segments = []
            last_alias = "seed"
            return_fields = ["seed.entity_id AS seed_id", "seed.canonical_name AS seed_name"]
            for index, relation_id in enumerate(relation_steps, start=1):
                node_alias = f"hop{index}"
                path_segments.append(f"-[:REL {{pid: '{relation_id}'}}]->({node_alias}:Entity)")
                return_fields.append(f"{node_alias}.canonical_name AS {node_alias}_name")
                last_alias = node_alias
            answer_path_query = {
                "label": "Answer path",
                "purpose": "Replay the inferred multi-hop path inside Neo4j for the active seed entities.",
                "query": (
                    f"MATCH path = (seed:Entity){''.join(path_segments)}\n"
                    "WHERE seed.entity_id IN $seed_ids\n"
                    "RETURN\n    "
                    + ",\n    ".join(return_fields)
                    + f",\n    {last_alias}.entity_id AS answer_entity_id\n"
                    "ORDER BY seed_name\n"
                    "LIMIT 10"
                ),
                "parameters": {"seed_ids": seed_ids},
            }
            return [seed_lookup_query, answer_path_query]

        fallback_query = {
            "label": "Evidence expansion",
            "purpose": "Inspect one-hop outgoing KG facts when no stable relation path is inferred yet.",
            "query": (
                "MATCH (seed:Entity)-[r:REL]->(target:Entity)\n"
                "WHERE seed.entity_id IN $seed_ids\n"
                "RETURN seed.canonical_name AS seed_name,\n"
                "       r.pid AS relation_id,\n"
                "       r.label AS relation_label,\n"
                "       target.canonical_name AS target_name\n"
                "ORDER BY seed_name, relation_label, target_name\n"
                "LIMIT 20"
            ),
            "parameters": {"seed_ids": seed_ids},
        }
        return [seed_lookup_query, fallback_query]

    def build_evidence_graph(self, trace: dict[str, object]) -> dict[str, object]:
        seeds = trace.get("seed_entities", [])
        selected_triples = [
            triple
            for round_payload in trace.get("activation_rounds", [])
            for triple in round_payload.get("selected_triples", [])
        ]
        candidate_ids = set(trace.get("structured_answer", {}).get("candidate_entity_ids") or [])
        nodes: dict[str, dict[str, object]] = {}
        edges: list[dict[str, object]] = []
        node_passages = self._node_passage_map(
            trace.get("retrieved_documents", []),
            [triple for triple in selected_triples if isinstance(triple, dict)],
        )

        for index, seed in enumerate(seeds):
            nodes[seed["entity_id"]] = self._build_graph_node(
                entity_id=seed["entity_id"],
                fallback_name=seed["entity_name"],
                roles=seed.get("roles") or [],
                role="seed",
                why_selected=f"Matched from {seed.get('source', 'graph')}",
                linked_passages=node_passages.get(seed["entity_id"], []),
                depth=0,
                index=index,
            )

        for round_payload in trace.get("activation_rounds", []):
            depth = int(round_payload.get("round_index", 1))
            for edge_index, triple in enumerate(round_payload.get("selected_triples", [])):
                source_id = str(triple["source_id"])
                target_id = str(triple["target_id"])
                if source_id not in nodes:
                    nodes[source_id] = self._build_graph_node(
                        entity_id=source_id,
                        fallback_name=str(triple["source_name"]),
                        roles=triple.get("source_roles") or [],
                        role="evidence",
                        why_selected="Appears in the selected KG path",
                        linked_passages=node_passages.get(source_id, []),
                        depth=max(depth - 1, 0),
                        index=edge_index,
                    )
                target_role = "answer" if target_id in candidate_ids else "evidence"
                nodes[target_id] = self._build_graph_node(
                    entity_id=target_id,
                    fallback_name=str(triple["target_name"]),
                    roles=triple.get("target_roles") or [],
                    role=target_role,
                    why_selected=f"Reached through {triple['relation_label']}",
                    linked_passages=node_passages.get(target_id, []),
                    depth=depth,
                    index=edge_index,
                )
                edges.append(
                    {
                        "id": f"{source_id}:{triple['relation_id']}:{target_id}",
                        "source": source_id,
                        "target": target_id,
                        "relation_id": triple["relation_id"],
                        "relation_label": triple["relation_label"],
                        "role": "answer_path" if target_id in candidate_ids else "selected_triple",
                        "score": triple.get("score", 0),
                    }
                )

        active_node_id = next(iter(candidate_ids), None) or (seeds[0]["entity_id"] if seeds else None)
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "active_node_id": active_node_id,
            "legend": self.graph_legend(),
        }

    def graph_legend(self) -> list[dict[str, str]]:
        return [
            {"key": "film", "label": "Film", "color": "#19e4ff"},
            {"key": "person", "label": "Person", "color": "#8b5cf6"},
            {"key": "place", "label": "Place", "color": "#f59e0b"},
            {"key": "school", "label": "School", "color": "#18f58f"},
            {"key": "award", "label": "Award", "color": "#ff5d6d"},
            {"key": "country", "label": "Country", "color": "#ffd166"},
            {"key": "seed", "label": "Seed", "color": "#19e4ff"},
            {"key": "answer_path", "label": "Answer Path", "color": "#18f58f"},
        ]

    def _expand_query(
        self,
        *,
        question_id: str,
        question_text: str,
        kg_summary: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> tuple[str, dict[str, object] | None]:
        history_block = self._conversation_history_block(conversation_history)
        response = self.registry.groq.chat_completion(
            action_name=f"phase6_expand_query_{question_id}",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite the question as a concise retrieval query using the KG summary. "
                        "Keep only the most relevant entities and relation clues. "
                        "Return one line."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Conversation context:\n{history_block}\n\n"
                        f"Question: {question_text}\n"
                        f"KG summary: {kg_summary}"
                    ),
                },
            ],
            max_output_tokens=64,
            temperature=0.0,
            metadata={"method": "kg_infused_rag", "stage": "query_expansion"},
        )
        expanded_query = extract_chat_text(response["response"]) or question_text
        return expanded_query, response["quota_snapshot"]

    def _answer_question(
        self,
        *,
        question_id: str,
        question_text: str,
        kg_summary: str,
        relation_path: list[str],
        selected_triples: list[dict[str, object]],
        structured_answer: dict[str, object],
        retrieved_documents: list[RetrievalDocument],
        question_type: str,
        conversation_history: list[dict[str, str]] | None = None,
        seeds: list[dict[str, object]],
        activation_rounds: list[dict[str, object]],
    ) -> tuple[str, dict[str, object] | None, dict[str, object]]:
        context_blocks = [
            f"[Context {index}] {document.title}\n{truncate_text(document.body, limit=500)}"
            for index, document in enumerate(retrieved_documents, start=1)
        ]
        context_text = "\n\n".join(context_blocks) if context_blocks else "[No retrieved context]"
        candidate_hint = structured_answer.get("answer_text")
        history_block = self._conversation_history_block(conversation_history)
        answer_instruction = (
            "Return only yes or no."
            if question_type == "comparison"
            else "Return only the shortest exact answer span. Do not add parent countries or explanations unless the question asks for a country."
        )
        response = self.registry.groq.chat_completion(
            action_name=f"phase6_answer_{question_id}",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Use the KG summary as the primary evidence and the retrieved context as supporting evidence. "
                        "If the evidence is insufficient, reply with unknown. "
                        f"{answer_instruction}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Conversation context:\n{history_block}\n\n"
                        f"Question: {question_text}\n\n"
                        f"KG candidate answer: {candidate_hint or 'unknown'}\n\n"
                        f"KG summary:\n{kg_summary}\n\n"
                        f"Retrieved context:\n{context_text}"
                    ),
                },
            ],
            max_output_tokens=96,
            temperature=0.0,
            metadata={"method": "kg_infused_rag", "stage": "answer_generation"},
        )
        raw_answer = repair_text(extract_chat_text(response["response"])).strip().rstrip(".")
        candidate_entity_ids = self._candidate_entity_ids(
            selected_triples=selected_triples,
            structured_answer=structured_answer,
            retrieved_documents=retrieved_documents,
        )
        path_document_answer = self._path_document_answer(
            question_id=question_id,
            relation_path=relation_path,
            retrieved_documents=retrieved_documents,
        )
        if question_type != "comparison" and path_document_answer:
            canonical_answer = path_document_answer.rstrip(".")
            return canonical_answer, response["quota_snapshot"], self._build_answer_meta(
                canonical_answer=canonical_answer,
                question_text=question_text,
                question_type=question_type,
                seeds=seeds,
                relation_path=relation_path,
                selected_triples=selected_triples,
                structured_answer=structured_answer,
                activation_rounds=activation_rounds,
            )
        if question_type != "comparison" and relation_path and not candidate_entity_ids:
            canonical_answer = "unknown"
            return canonical_answer, response["quota_snapshot"], self._build_answer_meta(
                canonical_answer=canonical_answer,
                question_text=question_text,
                question_type=question_type,
                seeds=seeds,
                relation_path=relation_path,
                selected_triples=selected_triples,
                structured_answer=structured_answer,
                activation_rounds=activation_rounds,
            )

        if question_type == "comparison":
            if candidate_hint in {"yes", "no"}:
                normalized_answer = normalize_for_match(raw_answer)
                if normalized_answer.startswith("yes"):
                    raw_answer = "yes"
                elif normalized_answer.startswith("no"):
                    raw_answer = "no"
                else:
                    raw_answer = str(candidate_hint)
            else:
                raw_answer = "unknown"
            return raw_answer, response["quota_snapshot"], self._build_answer_meta(
                canonical_answer=raw_answer,
                question_text=question_text,
                question_type=question_type,
                seeds=seeds,
                relation_path=relation_path,
                selected_triples=selected_triples,
                structured_answer=structured_answer,
                activation_rounds=activation_rounds,
            )

        matched_entity_id = self.lexicon.match_entity_id(raw_answer, candidate_entity_ids)
        if matched_entity_id:
            raw_answer = path_document_answer or self.lexicon.preferred_answer_name(
                matched_entity_id,
                context_texts=[
                    question_text,
                    *[
                        " ".join(
                            [
                                str(document.title),
                                str(document.body),
                                str(document.metadata or {}),
                            ]
                        )
                        for document in retrieved_documents
                    ],
                ],
            )
        else:
            normalized_answer = normalize_for_match(raw_answer)
            normalized_candidate = normalize_for_match(str(candidate_hint or ""))
            if candidate_hint and (
                not normalized_answer
                or normalized_answer == "unknown"
                or normalized_candidate in normalized_answer
                or normalized_answer in normalized_candidate
            ):
                raw_answer = path_document_answer or str(candidate_hint)
            elif not candidate_hint:
                raw_answer = "unknown"
            elif "country" not in question_text.casefold() and "," in raw_answer:
                raw_answer = raw_answer.split(",", 1)[0].strip()
        canonical_answer = raw_answer.rstrip(".")
        return canonical_answer, response["quota_snapshot"], self._build_answer_meta(
            canonical_answer=canonical_answer,
            question_text=question_text,
            question_type=question_type,
            seeds=seeds,
            relation_path=relation_path,
            selected_triples=selected_triples,
            structured_answer=structured_answer,
            activation_rounds=activation_rounds,
        )

    def _build_answer_meta(
        self,
        *,
        canonical_answer: str,
        question_text: str,
        question_type: str,
        seeds: list[dict[str, object]],
        relation_path: list[str],
        selected_triples: list[dict[str, object]],
        structured_answer: dict[str, object],
        activation_rounds: list[dict[str, object]],
    ) -> dict[str, object]:
        normalized_answer = normalize_for_match(canonical_answer)
        if normalized_answer and normalized_answer != "unknown":
            return {
                "status": "answered",
                "reason_code": "answered",
                "confidence": "high",
                "canonical_answer": canonical_answer,
                "display_text": canonical_answer,
                "memory_text": canonical_answer,
            }

        seed_names = [
            str(seed.get("entity_name") or "")
            for seed in seeds
            if str(seed.get("entity_name") or "").strip()
        ]
        candidate_texts = list(structured_answer.get("candidate_texts") or [])
        completed_rounds = sum(
            1 for round_payload in activation_rounds if round_payload.get("selected_triples")
        )
        missing_relation_id = self._missing_relation_id(
            relation_path=relation_path,
            activation_rounds=activation_rounds,
            selected_triples=selected_triples,
        )
        if not seeds:
            reason_code = "entity_not_found"
        elif not relation_path:
            reason_code = "relation_path_missing"
        elif question_type == "comparison" and completed_rounds < len(relation_path):
            reason_code = "comparison_incomplete"
        elif question_type != "comparison" and len(candidate_texts) > 1:
            reason_code = "ambiguous_result"
        elif not selected_triples:
            reason_code = "relation_missing"
        elif not structured_answer.get("answer_text"):
            reason_code = "answer_not_verified"
        else:
            reason_code = "insufficient_evidence"

        display_text = self._friendly_unknown_message(
            reason_code=reason_code,
            question_text=question_text,
            question_type=question_type,
            seed_names=seed_names,
            missing_relation_id=missing_relation_id,
        )
        return {
            "status": "unanswered",
            "reason_code": reason_code,
            "confidence": "low",
            "canonical_answer": "unknown",
            "display_text": display_text,
            "memory_text": display_text,
        }

    def _missing_relation_id(
        self,
        *,
        relation_path: list[str],
        activation_rounds: list[dict[str, object]],
        selected_triples: list[dict[str, object]],
    ) -> str | None:
        for round_index, round_payload in enumerate(activation_rounds):
            if round_payload.get("selected_triples"):
                continue
            if round_index < len(relation_path):
                return relation_path[round_index]
        if selected_triples or not relation_path:
            return relation_path[-1] if relation_path else None
        return relation_path[0]

    def _friendly_unknown_message(
        self,
        *,
        reason_code: str,
        question_text: str,
        question_type: str,
        seed_names: list[str],
        missing_relation_id: str | None,
    ) -> str:
        relation_label = self._reason_relation_label(missing_relation_id)
        seed_phrase = self._seed_phrase(seed_names)
        if reason_code == "entity_not_found":
            return "I couldn't match the main entity in the current graph."
        if reason_code == "relation_path_missing":
            return "I matched the question text, but I couldn't infer a reliable graph path for it."
        if reason_code == "comparison_incomplete":
            if relation_label:
                return (
                    f"I matched {seed_phrase}, but I couldn't verify the required {relation_label} path "
                    "for both sides in the current graph."
                )
            return "I matched part of the comparison, but I couldn't verify the full path for both sides in the current graph."
        if reason_code == "relation_missing":
            if seed_phrase and relation_label:
                return f"I found {seed_phrase} in the graph, but I couldn't verify a {relation_label} relation in the current dataset."
            if relation_label:
                return f"I couldn't verify a {relation_label} relation in the current graph."
            return "I couldn't verify the required relation in the current graph."
        if reason_code == "ambiguous_result":
            return "I found more than one plausible answer in the current graph, so I can't answer confidently yet."
        if reason_code == "answer_not_verified":
            return "I found partial evidence, but not enough to produce a verified answer from the current graph."
        if question_type == "comparison":
            return "I couldn't verify this comparison from the current graph."
        return "I couldn't verify this from the current graph."

    def _seed_phrase(self, seed_names: list[str]) -> str:
        cleaned = [self._human_seed_name(name) for name in seed_names if name]
        if not cleaned:
            return "the matched entities"
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return f"{cleaned[0]} and {cleaned[1]}"
        return f"{cleaned[0]}, {cleaned[1]}, and others"

    def _human_seed_name(self, seed_name: str) -> str:
        cleaned = repair_text(seed_name).strip()
        if " (" in cleaned:
            cleaned = cleaned.split(" (", 1)[0].strip()
        return cleaned

    def _reason_relation_label(self, relation_id: str | None) -> str | None:
        relation_labels = {
            "P19": "birthplace",
            "P69": "education",
            "P166": "award",
            "P17": "country",
            "P57": "director",
            "P161": "cast member",
        }
        if not relation_id:
            return None
        return relation_labels.get(relation_id, RELATION_TEXT.get(relation_id) or relation_id)

    def _path_document_answer(
        self,
        *,
        question_id: str,
        relation_path: list[str],
        retrieved_documents: list[RetrievalDocument],
    ) -> str | None:
        if not relation_path:
            return None
        relation_phrase = RELATION_TEXT.get(relation_path[-1], "").strip()
        if not relation_phrase:
            return None
        for document in retrieved_documents:
            if document.source_kind != "question_support_path":
                continue
            metadata = document.metadata or {}
            if str(metadata.get("question_id")) != question_id:
                continue
            body = repair_text(document.body)
            marker = f" {relation_phrase} "
            if marker not in body:
                continue
            answer_text = body.rsplit(marker, 1)[-1].strip().rstrip(".")
            if answer_text:
                return answer_text
        return None

    def _derive_structured_answer(
        self,
        *,
        relation_path: list[str],
        seeds: list[dict[str, object]],
        selected_triples: list[dict[str, object]],
        question_type: str,
    ) -> dict[str, object]:
        if not relation_path or not seeds or not selected_triples:
            return {
                "seed_paths": [],
                "candidate_entity_ids": [],
                "candidate_texts": [],
                "answer_text": None,
            }

        triples_by_source: dict[str, list[dict[str, object]]] = {}
        for triple in selected_triples:
            triples_by_source.setdefault(str(triple["source_id"]), []).append(triple)

        seed_paths: list[dict[str, object]] = []
        candidate_entity_ids: list[str] = []
        candidate_texts: list[str] = []

        for seed in seeds:
            current_nodes = [
                {
                    "entity_id": str(seed["entity_id"]),
                    "entity_name": str(seed["entity_name"]),
                }
            ]
            for relation_id in relation_path:
                next_nodes: list[dict[str, str]] = []
                selected_for_step: dict[str, dict[str, object]] = {}
                for node in current_nodes:
                    for triple in triples_by_source.get(node["entity_id"], []):
                        if triple["relation_id"] != relation_id:
                            continue
                        triple_key = str(triple["target_id"])
                        selected_for_step[triple_key] = {
                            "entity_id": str(triple["target_id"]),
                            "entity_name": str(triple["target_name"]),
                        }
                if not selected_for_step:
                    current_nodes = []
                    break
                next_nodes = list(selected_for_step.values())
                current_nodes = next_nodes

            seed_paths.append(
                {
                    "seed_entity_id": str(seed["entity_id"]),
                    "seed_entity_name": str(seed["entity_name"]),
                    "final_answers": current_nodes,
                }
            )
            for node in current_nodes:
                candidate_entity_ids.append(node["entity_id"])
                candidate_texts.append(node["entity_name"])

        candidate_entity_ids = self._dedupe_values(candidate_entity_ids)
        candidate_texts = self._dedupe_values(candidate_texts)
        answer_text: str | None = None

        if question_type == "comparison":
            per_seed_answers = [
                path["final_answers"][0]["entity_name"]
                for path in seed_paths
                if len(path["final_answers"]) == 1
            ]
            if len(per_seed_answers) >= 2 and len(per_seed_answers) == len(seed_paths):
                normalized_answers = {normalize_for_match(answer) for answer in per_seed_answers}
                answer_text = "yes" if len(normalized_answers) == 1 else "no"
        elif len(candidate_texts) == 1:
            answer_text = candidate_texts[0]

        return {
            "seed_paths": seed_paths,
            "candidate_entity_ids": candidate_entity_ids,
            "candidate_texts": candidate_texts,
            "answer_text": answer_text,
        }

    def _candidate_entity_ids(
        self,
        *,
        selected_triples: list[dict[str, object]],
        structured_answer: dict[str, object],
        retrieved_documents: list[RetrievalDocument],
    ) -> list[str]:
        candidate_entity_ids = list(structured_answer.get("candidate_entity_ids") or [])
        for triple in selected_triples:
            candidate_entity_ids.append(str(triple["target_id"]))
        for document in retrieved_documents:
            metadata = document.metadata or {}
            if document.source_kind == "graph_fact":
                target_id = metadata.get("target_id")
                if target_id:
                    candidate_entity_ids.append(str(target_id))
        return self._dedupe_values(candidate_entity_ids)

    def _dedupe_values(self, values: list[str]) -> list[str]:
        ordered_values: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = normalize_for_match(value)
            key = normalized or value.casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered_values.append(value)
        return ordered_values

    def _build_graph_patch(
        self,
        seeds: list[dict[str, object]],
        selected_triples: list[dict[str, object]],
    ) -> dict[str, object]:
        interim_trace = {
            "seed_entities": seeds,
            "activation_rounds": [
                {
                    "round_index": 1,
                    "selected_triples": selected_triples,
                }
            ]
            if selected_triples
            else [],
            "structured_answer": {
                "candidate_entity_ids": [triple["target_id"] for triple in selected_triples[-1:]],
            },
            "retrieved_documents": [],
        }
        return self.build_evidence_graph(interim_trace)

    def _build_graph_node(
        self,
        *,
        entity_id: str,
        fallback_name: str,
        roles: list[str],
        role: str,
        why_selected: str,
        linked_passages: list[str],
        depth: int,
        index: int,
    ) -> dict[str, object]:
        try:
            entity_lookup = self.graph.entity_lookup(entity_id) or {}
        except Exception:  # pragma: no cover - live fallback path
            entity_lookup = {}
        description = repair_text(str(entity_lookup.get("description") or "")).strip()
        normalized_roles = [str(item) for item in (entity_lookup.get("roles") or roles or [])]
        semantic_kind = self._node_kind(normalized_roles)
        return {
            "id": entity_id,
            "label": self.lexicon.display_name(entity_id, fallback_name=fallback_name),
            "canonical_name": repair_text(str(entity_lookup.get("canonical_name") or fallback_name)),
            "description": description,
            "roles": normalized_roles,
            "kind": semantic_kind,
            "role": role,
            "why_selected": why_selected,
            "linked_passages": linked_passages,
            "depth": depth,
            "order": index,
        }

    def _node_passage_map(
        self,
        retrieved_documents: list[dict[str, object]],
        triples: list[dict[str, object]],
    ) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for document in retrieved_documents:
            snippet = str(document.get("snippet") or document.get("body") or "").strip()
            if not snippet:
                continue
            source_entity_id = document.get("source_entity_id")
            if source_entity_id:
                mapping.setdefault(str(source_entity_id), []).append(snippet)
            metadata = document.get("metadata") or {}
            target_id = metadata.get("target_id")
            if target_id:
                mapping.setdefault(str(target_id), []).append(snippet)
        for triple in triples:
            text = f"{triple['source_name']} -> {triple['relation_label']} -> {triple['target_name']}"
            mapping.setdefault(str(triple["source_id"]), []).append(text)
            mapping.setdefault(str(triple["target_id"]), []).append(text)
        return {key: values[:3] for key, values in mapping.items()}

    def _node_kind(self, roles: list[str]) -> str:
        lowered = {role.casefold() for role in roles}
        if "film" in lowered:
            return "film"
        if "country" in lowered:
            return "country"
        if "award" in lowered:
            return "award"
        if "education_entity" in lowered:
            return "school"
        if "birth_place" in lowered or "city" in lowered or "place" in lowered:
            return "place"
        if {"director", "cast_member"} & lowered:
            return "person"
        return "entity"

    def _conversation_history_block(self, conversation_history: list[dict[str, str]] | None) -> str:
        if not conversation_history:
            return "[No prior turns]"
        compact_turns = [
            f"{message['role'].capitalize()}: {message['content']}"
            for message in conversation_history[-8:]
            if message.get("content")
        ]
        return "\n".join(compact_turns) if compact_turns else "[No prior turns]"

    def _grounding_text(
        self,
        question_text: str,
        conversation_history: list[dict[str, str]],
    ) -> str:
        if not conversation_history:
            return question_text
        recent_turns = [
            message["content"]
            for message in conversation_history[-4:]
            if message.get("content")
        ]
        return " ".join([*recent_turns, question_text]).strip()

    def _history_for_question(
        self,
        question_text: str,
        conversation_history: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not conversation_history:
            return []
        if not self._should_use_conversation_history(question_text):
            return []
        return conversation_history[-6:]

    def _should_use_conversation_history(self, question_text: str) -> bool:
        normalized = normalize_for_match(question_text)
        if not normalized:
            return False

        explicit_matches = self.lexicon.match_question(question_text, limit=3)
        if explicit_matches:
            return False

        padded = f" {normalized} "
        follow_up_markers = (
            " it ",
            " its ",
            " they ",
            " them ",
            " their ",
            " he ",
            " his ",
            " she ",
            " her ",
            " that film ",
            " that movie ",
            " that director ",
            " that cast member ",
            " this film ",
            " this movie ",
            " this director ",
            " same one ",
            " previous one ",
        )
        if normalized.startswith(("and ", "what about", "how about", "then ", "also ", "what if ")):
            return True
        return any(marker in padded for marker in follow_up_markers)

    def _infer_freeform_question_type(self, question_text: str) -> str:
        normalized = normalize_for_match(question_text)
        if "same " in normalized or normalized.startswith(("were ", "are ", "did ", "do ", "is ", "was ")):
            if "same" in normalized or " both " in normalized:
                return "comparison"
        relation_count = len(infer_relation_path(question_text))
        return "three_hop" if relation_count >= 3 else "two_hop"

    def _infer_freeform_max_rounds(self, relation_path: list[str]) -> int:
        if not relation_path:
            return 3
        return min(max(len(relation_path), 2), 6)

    def _chunk_answer(self, answer_text: str) -> list[str]:
        cleaned = answer_text.strip()
        if not cleaned:
            return []
        words = cleaned.split()
        if len(words) <= 3:
            return [cleaned]
        chunks: list[str] = []
        buffer: list[str] = []
        for word in words:
            buffer.append(word)
            if len(buffer) >= 4:
                chunks.append(" ".join(buffer) + " ")
                buffer = []
        if buffer:
            chunks.append(" ".join(buffer))
        return chunks

    def _emit_event(
        self,
        context: KGRunContext,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        if context.emit_event is not None:
            context.emit_event(event_name, payload)

    def _failed_trace(
        self,
        context: KGRunContext,
        *,
        status: str,
        message: str,
    ) -> dict[str, object]:
        return {
            "created_at": utc_now_iso(),
            "status": status,
            "method": "kg_infused_rag",
            "question_id": context.question["question_id"],
            "question": context.question["question"],
            "question_type": context.question["question_type"],
            "template": context.question["template"],
            "difficulty": context.question["difficulty"],
            "gold_answer": context.question["gold_answer"],
            "prediction_text": "",
            "display_text": message,
            "seed_entities": [],
            "relation_path": [],
            "activation_rounds": [],
            "structured_answer": {
                "seed_paths": [],
                "candidate_entity_ids": [],
                "candidate_texts": [],
                "answer_text": None,
            },
            "kg_summary": "",
            "expanded_query": None,
            "cypher_queries": [],
            "retrieved_documents": [],
            "session_memory_used": bool(context.conversation_history),
            "provider": {"name": "groq", "model": self.settings.groq_model},
            "error": message,
            "answer_meta": {
                "status": status,
                "reason_code": status,
                "confidence": "low",
                "canonical_answer": "",
                "display_text": message,
                "memory_text": message,
            },
        }
