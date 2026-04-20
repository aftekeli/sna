from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from app.baselines.common import normalize_for_match, repair_text
from app.core.config import Settings


@dataclass(slots=True)
class LexiconMatch:
    entity_id: str
    canonical_name: str
    matched_alias: str
    roles: list[str]
    score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "entity_id": self.entity_id,
            "canonical_name": self.canonical_name,
            "matched_alias": self.matched_alias,
            "roles": self.roles,
            "score": self.score,
        }


class EntityLexicon:
    def __init__(self, settings: Settings, entities_path: Path | None = None) -> None:
        self.settings = settings
        self.entities_path = entities_path or settings.phase3_entities_path
        self._entities: list[dict[str, object]] | None = None
        self._entities_by_id: dict[str, dict[str, object]] | None = None
        self._display_names: dict[str, str] | None = None

    def match_question(self, question_text: str, *, limit: int = 4) -> list[LexiconMatch]:
        normalized_question = normalize_for_match(question_text)
        if not normalized_question:
            return []

        matches: dict[str, LexiconMatch] = {}
        for entity in self._load_entities():
            best_score = 0.0
            best_alias = ""
            roles = entity["roles"]
            for alias in entity["aliases"]:
                alias_norm = normalize_for_match(alias)
                if len(alias_norm) < 3:
                    continue
                if alias_norm not in normalized_question:
                    continue
                words = alias_norm.split()
                if len(words) == 1 and len(alias_norm) < 5:
                    continue
                score = len(alias_norm) + (len(words) * 2)
                if "film" in roles:
                    score += 5
                if "director" in roles or "cast_member" in roles:
                    score += 2
                if score > best_score:
                    best_score = score
                    best_alias = alias

            if best_score <= 0:
                continue

            existing = matches.get(entity["entity_id"])
            candidate = LexiconMatch(
                entity_id=entity["entity_id"],
                canonical_name=entity["canonical_name"],
                matched_alias=best_alias,
                roles=roles,
                score=best_score,
            )
            if existing is None or candidate.score > existing.score:
                matches[entity["entity_id"]] = candidate

        ordered_matches = sorted(
            matches.values(),
            key=lambda item: (-item.score, item.canonical_name.casefold(), item.entity_id),
        )
        return ordered_matches[:limit]

    def _load_entities(self) -> list[dict[str, object]]:
        if self._entities is not None:
            return self._entities

        entities: list[dict[str, object]] = []
        entities_by_id: dict[str, dict[str, object]] = {}
        with self.entities_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                entity = {
                    "entity_id": row["entity_id"],
                    "canonical_name": repair_text(row["canonical_name"]),
                    "aliases": [repair_text(alias) for alias in json.loads(row["aliases_json"])],
                    "description": repair_text(row["description"]),
                    "roles": json.loads(row["roles_json"]),
                }
                entities.append(entity)
                entities_by_id[entity["entity_id"]] = entity
        self._entities = entities
        self._entities_by_id = entities_by_id
        return self._entities

    def display_name(self, entity_id: str, *, fallback_name: str | None = None) -> str:
        self._ensure_display_names()
        if self._display_names and entity_id in self._display_names:
            return self._display_names[entity_id]
        return repair_text(fallback_name or entity_id)

    def answer_entity_match(self, answer_text: str, candidate_entity_ids: list[str]) -> str | None:
        matched_entity_id = self.match_entity_id(answer_text, candidate_entity_ids)
        if matched_entity_id is None:
            return None
        return self.display_name(matched_entity_id)

    def match_entity_id(self, answer_text: str, candidate_entity_ids: list[str]) -> str | None:
        normalized_answer = normalize_for_match(answer_text)
        if not normalized_answer:
            return None
        self._load_entities()
        assert self._entities_by_id is not None
        for entity_id in candidate_entity_ids:
            entity = self._entities_by_id.get(entity_id)
            if entity is None:
                continue
            alias_candidates = [entity["canonical_name"], *entity["aliases"], self.display_name(entity_id)]
            for alias in alias_candidates:
                normalized_alias = normalize_for_match(alias)
                if not normalized_alias:
                    continue
                if normalized_alias in normalized_answer or normalized_answer in normalized_alias:
                    return entity_id
        return None

    def preferred_answer_name(
        self,
        entity_id: str,
        *,
        context_texts: list[str] | None = None,
    ) -> str:
        self._load_entities()
        assert self._entities_by_id is not None
        entity = self._entities_by_id.get(entity_id)
        if entity is None:
            return self.display_name(entity_id)

        normalized_contexts = [
            normalize_for_match(text)
            for text in (context_texts or [])
            if normalize_for_match(text)
        ]
        candidates = [entity["canonical_name"], *entity["aliases"], self.display_name(entity_id)]
        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            cleaned = repair_text(candidate).strip()
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(cleaned)
        if not deduped:
            return self.display_name(entity_id)
        return min(
            deduped,
            key=lambda item: self._answer_name_score(
                item,
                roles=entity["roles"],
                normalized_contexts=normalized_contexts,
            ),
        )

    def _ensure_display_names(self) -> None:
        if self._display_names is not None:
            return
        self._load_entities()
        assert self._entities is not None
        display_names: dict[str, str] = {}
        for entity in self._entities:
            candidates = [entity["canonical_name"], *entity["aliases"]]
            title = self._description_title(entity["description"])
            if title:
                candidates.append(title)
            deduped: list[str] = []
            seen: set[str] = set()
            for candidate in candidates:
                cleaned = repair_text(candidate).strip()
                if not cleaned:
                    continue
                key = cleaned.casefold()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(cleaned)
            best = min(deduped, key=lambda item: self._display_score(item, entity["roles"]))
            display_names[entity["entity_id"]] = best
        self._display_names = display_names

    def _display_score(self, value: str, roles: list[str]) -> tuple[int, int, str]:
        lowered = value.casefold()
        penalties = 0
        if "," in value:
            penalties += 2
        if any(token in lowered for token in ("history of", "list of", "iso 3166", "current g20", "name of")):
            penalties += 8
        if value == value.lower():
            penalties += 1
        if "birth_place" in roles and "turkey" in lowered and len(value) > 10:
            penalties += 3
        if "country" in roles and any(token in lowered for token in ("republic", "kingdom", "united")):
            penalties -= 1
        return (penalties, len(value), lowered)

    def _answer_name_score(
        self,
        value: str,
        *,
        roles: list[str],
        normalized_contexts: list[str],
    ) -> tuple[int, int, int, str]:
        normalized_value = normalize_for_match(value)
        context_penalty = 0 if any(normalized_value and normalized_value in text for text in normalized_contexts) else 2
        penalties, length, lowered = self._display_score(value, roles)
        if value.isascii():
            penalties -= 1
        if value[:1].isupper():
            penalties -= 1
        return (context_penalty, penalties, length, lowered)

    def _description_title(self, description: str) -> str:
        cleaned = repair_text(description).strip()
        if not cleaned:
            return ""
        separators = [" is ", " was ", " are ", " were ", " (", ",", ";"]
        for separator in separators:
            if separator in cleaned:
                candidate = cleaned.split(separator, 1)[0].strip()
                if 1 < len(candidate) <= 80:
                    return candidate
        return ""
