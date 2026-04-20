from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.baselines.common import normalize_for_match, repair_text
from app.providers.neo4j_provider import Neo4jProvider

RELATION_HINTS = {
    "director": "P57",
    "directors": "P57",
    "yonetmen": "P57",
    "yonetmeni": "P57",
    "yonetmenleri": "P57",
    "cast": "P161",
    "oyuncu": "P161",
    "oynadi": "P161",
    "oynamis": "P161",
    "born": "P19",
    "birth": "P19",
    "dogdu": "P19",
    "dogmustur": "P19",
    "dogum yeri": "P19",
    "nerede dog": "P19",
    "nereli": "P19",
    "award": "P166",
    "awards": "P166",
    "odul": "P166",
    "oduller": "P166",
    "study": "P69",
    "studied": "P69",
    "school": "P69",
    "educated": "P69",
    "okudu": "P69",
    "egitim": "P69",
    "hangi okul": "P69",
    "country": "P17",
    "ulke": "P17",
}

EXPECTED_ROLE_BY_RELATION = {
    "P57": "director",
    "P161": "cast_member",
    "P19": "birth_place",
    "P69": "education_entity",
    "P166": "award",
    "P17": "country",
}


@dataclass(slots=True)
class GraphTriple:
    source_id: str
    source_name: str
    source_roles: list[str]
    relation_id: str
    relation_label: str
    target_id: str
    target_name: str
    target_roles: list[str]
    score: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_roles": self.source_roles,
            "relation_id": self.relation_id,
            "relation_label": self.relation_label,
            "target_id": self.target_id,
            "target_name": self.target_name,
            "target_roles": self.target_roles,
            "score": self.score,
        }


class Neo4jGraphExplorer:
    def __init__(self, provider: Neo4jProvider) -> None:
        self.provider = provider

    def fulltext_search(self, query_text: str, *, limit: int = 8) -> list[dict[str, object]]:
        query = """
        CALL db.index.fulltext.queryNodes('entity_text_search', $query_text)
        YIELD node, score
        RETURN
            node.entity_id AS entity_id,
            node.canonical_name AS canonical_name,
            node.roles AS roles,
            score
        LIMIT $limit
        """
        return self.provider.run_query(query, parameters={"query_text": query_text, "limit": limit})

    def fetch_outgoing_triples(self, entity_id: str, *, limit: int = 20) -> list[GraphTriple]:
        query = """
        MATCH (source:Entity {entity_id: $entity_id})-[r:REL]->(target:Entity)
        RETURN
            source.entity_id AS source_id,
            source.canonical_name AS source_name,
            source.roles AS source_roles,
            r.pid AS relation_id,
            r.label AS relation_label,
            target.entity_id AS target_id,
            target.canonical_name AS target_name,
            target.roles AS target_roles
        LIMIT $limit
        """
        rows = self.provider.run_query(query, parameters={"entity_id": entity_id, "limit": limit})
        return [
            GraphTriple(
                source_id=row["source_id"],
                source_name=repair_text(row["source_name"]),
                source_roles=row.get("source_roles") or [],
                relation_id=row["relation_id"],
                relation_label=repair_text(row["relation_label"]),
                target_id=row["target_id"],
                target_name=repair_text(row["target_name"]),
                target_roles=row.get("target_roles") or [],
            )
            for row in rows
        ]

    def entity_lookup(self, entity_id: str) -> dict[str, object] | None:
        query = """
        MATCH (entity:Entity {entity_id: $entity_id})
        RETURN
            entity.entity_id AS entity_id,
            entity.canonical_name AS canonical_name,
            entity.roles AS roles,
            entity.description AS description
        LIMIT 1
        """
        rows = self.provider.run_query(query, parameters={"entity_id": entity_id})
        return rows[0] if rows else None


def infer_relation_path(question_text: str) -> list[str]:
    normalized = normalize_for_match(question_text)
    asks_country = any(
        token in normalized
        for token in (
            "same country",
            "which country",
            "country was the director",
            "hangi ulke",
            "ayni ulke",
            "ayni ulkede",
            "ulke",
        )
    )
    asks_study = any(
        token in normalized
        for token in (
            "study",
            "studied",
            "school",
            "educated",
            "okudu",
            "egitim",
            "hangi okul",
        )
    )
    asks_birth = any(
        token in normalized
        for token in (
            "born",
            "birth",
            "dogdu",
            "dogmustur",
            "dogum yeri",
            "nerede dog",
            "nereli",
        )
    )
    asks_award = any(token in normalized for token in ("award", "awards", "odul", "oduller"))
    asks_director = any(
        token in normalized
        for token in (
            "directors of",
            "director of",
            "yonetmeni",
            "yonetmenleri",
            "yonetmen",
        )
    )
    asks_cast = any(
        token in normalized
        for token in (
            "cast member of",
            ", a cast member of",
            "cast member",
            "oyuncu",
            "oynadi",
            "oynamis",
        )
    )
    if asks_director:
        if asks_country:
            if asks_study:
                return ["P57", "P69", "P17"]
            if asks_birth:
                return ["P57", "P19", "P17"]
        if asks_study:
            return ["P57", "P69"]
        if asks_award:
            return ["P57", "P166"]
        if asks_birth:
            return ["P57", "P19"]

    if asks_cast:
        if asks_country:
            return ["P161", "P19", "P17"]
        if asks_award:
            return ["P161", "P166"]
        if asks_birth:
            return ["P161", "P19"]

    if asks_birth:
        return ["P19"]
    if asks_study:
        return ["P69"]
    if asks_award:
        return ["P166"]
    if asks_country:
        return ["P17"]

    relation_ids = []
    seen: set[str] = set()
    for token, relation_id in RELATION_HINTS.items():
        if token in normalized and relation_id not in seen:
            seen.add(relation_id)
            relation_ids.append(relation_id)
    return relation_ids


def score_triple(
    triple: GraphTriple,
    *,
    question_text: str,
    preferred_path: list[str],
    round_index: int,
    visited_targets: set[str],
) -> float:
    normalized_question = normalize_for_match(question_text)
    normalized_target = normalize_for_match(triple.target_name)
    score = 0.0
    if triple.target_id in visited_targets:
        score -= 20.0
    if round_index < len(preferred_path) and triple.relation_id == preferred_path[round_index]:
        score += 12.0
    elif triple.relation_id in preferred_path:
        score += 5.0
    expected_role = EXPECTED_ROLE_BY_RELATION.get(triple.relation_id)
    if expected_role and expected_role in triple.target_roles:
        score += 4.0
    if normalized_target and normalized_target in normalized_question:
        score += 5.0
    if triple.relation_label and normalize_for_match(triple.relation_label) in normalized_question:
        score += 3.0
    if "country" in triple.target_roles and "country" in normalized_question:
        score += 2.0
    if "award" in triple.target_roles and "award" in normalized_question:
        score += 2.0
    if triple.relation_id == "P17" and "country_root" in triple.target_roles:
        score += 6.0
    if triple.relation_id == "P17":
        normalized_country = normalize_for_match(triple.target_name)
        if any(token in normalized_country for token in ("empire", "sultanate")):
            score -= 4.0
    return score


def group_triples_by_source(triples: list[GraphTriple]) -> dict[str, list[GraphTriple]]:
    grouped: dict[str, list[GraphTriple]] = defaultdict(list)
    for triple in triples:
        grouped[triple.source_id].append(triple)
    return grouped
