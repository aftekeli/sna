from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from explore_turkiye_cinema import (
    RELATION_ALIAS_PATH,
    TRIPLES_PATH,
    iter_tsv_rows,
    load_relation_labels,
    normalize_text,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE2_SUMMARY_PATH = REPO_ROOT / "artifacts" / "phase-2" / "turkiye_cinema_summary.json"
PHASE3_ENTITIES_PATH = REPO_ROOT / "artifacts" / "phase-3" / "neo4j_import" / "entities.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "phase-4"
APPEND_ONLY_PATH = DEFAULT_OUTPUT_DIR / "accepted_questions.jsonl"
FINAL_DATASET_JSON_PATH = DEFAULT_OUTPUT_DIR / "turkiye_cinema_multihop_qa.json"
FINAL_DATASET_JSONL_PATH = DEFAULT_OUTPUT_DIR / "turkiye_cinema_multihop_qa.jsonl"
RAW_VERIFICATION_PATH = DEFAULT_OUTPUT_DIR / "raw_triple_verification.json"
DATASET_SUMMARY_JSON_PATH = DEFAULT_OUTPUT_DIR / "dataset_summary.json"
DATASET_SUMMARY_MD_PATH = DEFAULT_OUTPUT_DIR / "dataset_summary.md"
SELECTION_AUDIT_PATH = DEFAULT_OUTPUT_DIR / "selection_audit.json"

DOMAIN_TAG = "turkish_cinema"
LANGUAGE_TAG = "en"
MOJIBAKE_MARKERS = ("Ã", "Ä", "Å", "â", "Ë", "Ê", "Æ", "œ", "Ð", "Ñ", "¤", "�")
BAD_NAME_PARTS = {
    "iso 3166",
    "p:",
    "history of",
    "list of",
    "current g20",
    "name of",
    "culture of",
}
BAD_PLACE_NAMES = {
    "history of",
    "list of",
    "bishop of",
    "name of",
}
BAD_COUNTRY_DISPLAY_NAMES = {
    "ottoman empire",
    "allied occupation of germany",
    "current g20 countries",
}
PLACE_TYPE_KEYWORDS = {
    "city",
    "town",
    "district",
    "province",
    "village",
    "municipality",
    "county",
    "region",
    "capital",
    "settlement",
    "port",
    "administrative center",
}
EDUCATION_TYPE_KEYWORDS = {
    "university",
    "school",
    "college",
    "lyceum",
    "academy",
    "institute",
    "faculty",
}
AWARD_TYPE_KEYWORDS = {
    "award",
    "prize",
    "medal",
    "honour",
    "honor",
    "state artist",
}
TEMPLATE_QUOTAS_2_HOP = {
    "film_director_birth_place": 8,
    "film_director_award": 4,
    "film_director_education": 5,
    "film_cast_birth_place": 8,
    "film_cast_award": 5,
}
TEMPLATE_QUOTAS_3_HOP = {
    "film_director_birth_place_country": 5,
    "film_director_education_country": 5,
    "film_cast_birth_place_country": 5,
}
COMPARISON_REQUESTS = [
    ("film_director_birth_place_country", True),
    ("film_director_birth_place_country", False),
    ("film_director_education_country", False),
    ("film_cast_birth_place_country", True),
    ("film_cast_birth_place_country", False),
]


@dataclass(slots=True)
class EntityRecord:
    entity_id: str
    canonical_name: str
    aliases: list[str]
    description: str
    roles: list[str]
    domains: list[str]


@dataclass(slots=True)
class CandidatePath:
    template: str
    entity_ids: list[str]
    relation_ids: list[str]

    def key(self) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        return (self.template, tuple(self.entity_ids), tuple(self.relation_ids))


def repair_text(value: str) -> str:
    if not value:
        return ""
    if any(marker in value for marker in MOJIBAKE_MARKERS):
        for encoding in ("latin1", "cp1252"):
            try:
                return value.encode(encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
    return value


def extract_title_from_description(description: str) -> str:
    cleaned = repair_text(description).strip()
    if not cleaned:
        return ""

    parts = re.split(r"\s*\(|\s*[,;]\s*|\s+(?:is|was|are|were)\s+", cleaned, maxsplit=1)
    title = parts[0].strip() if parts else cleaned
    if 1 < len(title) <= 80:
        return title
    return ""


def weirdness_score(value: str) -> int:
    cleaned = repair_text(value).strip()
    lowered = cleaned.casefold()
    score = 0
    if not cleaned or re.fullmatch(r"Q\d+", cleaned):
        return 999
    if any(part in lowered for part in BAD_NAME_PARTS):
        score += 8
    if any(char in cleaned for char in "?�"):
        score += 10
    if sum(character.isalpha() for character in cleaned) < 2:
        score += 10
    if len(cleaned) > 80:
        score += 4
    if cleaned == cleaned.lower():
        score += 1
    if cleaned.count("(") != cleaned.count(")"):
        score += 3
    return score


def smart_capitalize_name(value: str) -> str:
    parts = re.split(r"(\s+)", value)
    transformed_parts: list[str] = []
    for part in parts:
        if not part or part.isspace():
            transformed_parts.append(part)
            continue
        if any(character.isupper() for character in part):
            transformed_parts.append(part)
            continue
        transformed_parts.append(part[0].upper() + part[1:])
    return "".join(transformed_parts)


def load_phase2_summary(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_entity_catalog(path: Path) -> dict[str, EntityRecord]:
    catalog: dict[str, EntityRecord] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            catalog[row["entity_id"]] = EntityRecord(
                entity_id=row["entity_id"],
                canonical_name=row["canonical_name"],
                aliases=json.loads(row["aliases_json"]),
                description=row["description"],
                roles=json.loads(row["roles_json"]),
                domains=json.loads(row["domains_json"]),
            )
    return catalog


def pick_display_name(entity: EntityRecord) -> str:
    description_title = extract_title_from_description(entity.description)
    candidate_names = [repair_text(entity.canonical_name)] + [repair_text(alias) for alias in entity.aliases[:10]]
    if description_title:
        candidate_names.append(description_title)

    deduped_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidate_names:
        stripped = candidate.strip()
        if not stripped:
            continue
        key = stripped.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped_candidates.append(stripped)

    def score(candidate: str) -> int:
        lowered = candidate.casefold()
        score_value = weirdness_score(candidate)
        if description_title and candidate == description_title:
            score_value -= 2
        if (
            description_title
            and normalize_text(candidate) == normalize_text(description_title)
            and candidate == candidate.lower()
            and description_title != description_title.lower()
        ):
            score_value += 2
        if description_title and "country" in entity.roles and candidate == description_title:
            score_value -= 2
        if entity.roles and "country" in entity.roles:
            if any(
                keyword in lowered
                for keyword in (
                    "turkey",
                    "france",
                    "germany",
                    "south korea",
                    "cyprus",
                    "australia",
                    "japan",
                    "azerbaijan",
                    "israel",
                    "syria",
                    "iraq",
                    "greece",
                    "iran",
                    "united states",
                    "united kingdom",
                    "republic of",
                )
            ):
                score_value -= 1
        return score_value

    best_candidate = min(deduped_candidates, key=score)
    if (
        description_title
        and weirdness_score(description_title) < 8
        and any(role in entity.roles for role in ("country", "birth_place", "education_entity", "award"))
    ):
        return description_title
    if (
        description_title
        and normalize_text(best_candidate) == normalize_text(description_title)
        and description_title != description_title.lower()
    ):
        return description_title
    if best_candidate == best_candidate.lower():
        return smart_capitalize_name(best_candidate)
    return best_candidate


def is_display_name_usable(entity: EntityRecord, display_name: str) -> bool:
    return weirdness_score(display_name) < 8


def description_prefix(entity: EntityRecord) -> str:
    return repair_text(entity.description)[:220].casefold()


def is_valid_place_entity(entity: EntityRecord, display_name: str) -> bool:
    lowered_name = display_name.casefold()
    if "birth_place" not in entity.roles:
        return False
    if any(part in lowered_name for part in BAD_PLACE_NAMES):
        return False
    return any(keyword in description_prefix(entity) for keyword in PLACE_TYPE_KEYWORDS)


def is_valid_country_entity(entity: EntityRecord, display_name: str) -> bool:
    lowered_name = display_name.casefold()
    if "country" not in entity.roles:
        return False
    if lowered_name in BAD_COUNTRY_DISPLAY_NAMES:
        return False
    if "iso 3166" in lowered_name:
        return False
    return True


def is_valid_education_entity(entity: EntityRecord, display_name: str) -> bool:
    lowered_name = display_name.casefold()
    if "education_entity" not in entity.roles:
        return False
    if "list of" in lowered_name:
        return False
    return any(keyword in lowered_name for keyword in EDUCATION_TYPE_KEYWORDS) or any(
        keyword in description_prefix(entity)
        for keyword in EDUCATION_TYPE_KEYWORDS
    )


def is_valid_award_entity(entity: EntityRecord, display_name: str) -> bool:
    lowered_name = display_name.casefold()
    if "award" not in entity.roles:
        return False
    return any(keyword in lowered_name for keyword in AWARD_TYPE_KEYWORDS) or any(
        keyword in description_prefix(entity)
        for keyword in AWARD_TYPE_KEYWORDS
    )


def candidate_is_valid(
    candidate: CandidatePath,
    catalog: dict[str, EntityRecord],
    display_names: dict[str, str],
) -> bool:
    entities = [catalog[entity_id] for entity_id in candidate.entity_ids]
    names = [display_names[entity.entity_id] for entity in entities]
    if not all(is_display_name_usable(entity, display_name) for entity, display_name in zip(entities, names, strict=True)):
        return False

    target_entity = entities[-1]
    target_name = names[-1]

    if candidate.template == "film_director_birth_place":
        return is_valid_place_entity(entities[2], names[2])
    if candidate.template == "film_director_award":
        return is_valid_award_entity(target_entity, target_name)
    if candidate.template == "film_director_education":
        return is_valid_education_entity(target_entity, target_name)
    if candidate.template == "film_cast_birth_place":
        return is_valid_place_entity(entities[2], names[2])
    if candidate.template == "film_cast_award":
        return is_valid_award_entity(target_entity, target_name)
    if candidate.template == "film_director_birth_place_country":
        return (
            candidate.entity_ids[2] != candidate.entity_ids[3]
            and is_valid_place_entity(entities[2], names[2])
            and is_valid_country_entity(entities[3], names[3])
        )
    if candidate.template == "film_director_education_country":
        return is_valid_education_entity(entities[2], names[2]) and is_valid_country_entity(entities[3], names[3])
    if candidate.template == "film_cast_birth_place_country":
        return (
            candidate.entity_ids[2] != candidate.entity_ids[3]
            and is_valid_place_entity(entities[2], names[2])
            and is_valid_country_entity(entities[3], names[3])
        )
    raise ValueError(f"Unsupported template: {candidate.template}")


def candidate_sort_key(candidate: CandidatePath, display_names: dict[str, str]) -> tuple[str, ...]:
    return tuple(display_names[entity_id].casefold() for entity_id in candidate.entity_ids) + tuple(candidate.entity_ids)


def parse_candidate_pool(phase2_summary: dict[str, object]) -> list[CandidatePath]:
    pool: list[CandidatePath] = []
    for candidates in phase2_summary["path_candidates"].values():
        for item in candidates:
            pool.append(
                CandidatePath(
                    template=item["template"],
                    entity_ids=item["entity_ids"],
                    relation_ids=item["relation_ids"],
                )
            )
    return pool


def build_filtered_pools(
    candidates: list[CandidatePath],
    catalog: dict[str, EntityRecord],
    display_names: dict[str, str],
) -> dict[str, list[CandidatePath]]:
    grouped: dict[str, list[CandidatePath]] = defaultdict(list)
    for candidate in candidates:
        if candidate_is_valid(candidate, catalog, display_names):
            grouped[candidate.template].append(candidate)

    for template, template_candidates in grouped.items():
        template_candidates.sort(key=lambda item: candidate_sort_key(item, display_names))
    return grouped


def choose_candidates_for_quota(
    template: str,
    target_count: int,
    pool: list[CandidatePath],
    film_usage: Counter[str],
    person_usage: Counter[str],
    answer_usage: Counter[str],
) -> list[CandidatePath]:
    chosen: list[CandidatePath] = []
    chosen_keys: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    chosen_question_keys: set[tuple[str, ...]] = set()

    def question_uniqueness_key(candidate: CandidatePath) -> tuple[str, ...]:
        if candidate.template.startswith("film_director"):
            return (candidate.template, candidate.entity_ids[0])
        if candidate.template.startswith("film_cast"):
            return (candidate.template, candidate.entity_ids[0], candidate.entity_ids[1])
        return (candidate.template, *candidate.entity_ids)

    for pass_index in range(3):
        film_limit = 2 if pass_index == 0 else 3 if pass_index == 1 else 999
        person_limit = 2 if pass_index == 0 else 3 if pass_index == 1 else 999
        answer_limit = 2 if pass_index == 0 else 3 if pass_index == 1 else 999

        for candidate in pool:
            candidate_key = candidate.key()
            if candidate_key in chosen_keys:
                continue
            question_key = question_uniqueness_key(candidate)
            if question_key in chosen_question_keys:
                continue

            film_id = candidate.entity_ids[0]
            person_id = candidate.entity_ids[1]
            answer_id = candidate.entity_ids[-1]
            if film_usage[film_id] >= film_limit:
                continue
            if person_usage[person_id] >= person_limit:
                continue
            if answer_usage[answer_id] >= answer_limit:
                continue

            chosen.append(candidate)
            chosen_keys.add(candidate_key)
            chosen_question_keys.add(question_key)
            film_usage[film_id] += 1
            person_usage[person_id] += 1
            answer_usage[answer_id] += 1
            if len(chosen) == target_count:
                return chosen

    return chosen


def build_comparison_candidates(
    pools: dict[str, list[CandidatePath]],
) -> list[dict[str, object]]:
    comparison_records: list[dict[str, object]] = []
    used_signatures: set[tuple[object, ...]] = set()

    def select_pair(template: str, same_answer: bool) -> tuple[CandidatePath, CandidatePath] | None:
        grouped_by_answer: dict[str, list[CandidatePath]] = defaultdict(list)
        for candidate in pools[template]:
            grouped_by_answer[candidate.entity_ids[-1]].append(candidate)

        if same_answer:
            for answer_id, candidates in grouped_by_answer.items():
                if len(candidates) < 2:
                    continue
                first, second = candidates[0], candidates[1]
                if len({first.entity_ids[0], second.entity_ids[0], first.entity_ids[1], second.entity_ids[1]}) < 4:
                    continue
                signature = (template, tuple(first.entity_ids), tuple(second.entity_ids), same_answer, answer_id)
                if signature in used_signatures:
                    continue
                used_signatures.add(signature)
                return first, second
            return None

        representatives = [(answer_id, candidates[0]) for answer_id, candidates in grouped_by_answer.items()]
        for index, (answer_a, candidate_a) in enumerate(representatives):
            for answer_b, candidate_b in representatives[index + 1 :]:
                if answer_a == answer_b:
                    continue
                if len({candidate_a.entity_ids[0], candidate_b.entity_ids[0], candidate_a.entity_ids[1], candidate_b.entity_ids[1]}) < 4:
                    continue
                signature = (template, tuple(candidate_a.entity_ids), tuple(candidate_b.entity_ids), same_answer, answer_a, answer_b)
                if signature in used_signatures:
                    continue
                used_signatures.add(signature)
                return candidate_a, candidate_b
        return None

    for template, same_answer in COMPARISON_REQUESTS:
        pair = select_pair(template, same_answer)
        if pair is None:
            raise RuntimeError(f"Could not build the required comparison question for {template} same_answer={same_answer}.")
        comparison_records.append(
            {
                "template": template,
                "same_answer": same_answer,
                "candidates": [pair[0], pair[1]],
            }
        )

    return comparison_records


def build_path_payload(
    candidate: CandidatePath,
    display_names: dict[str, str],
    relation_labels: dict[str, str],
) -> dict[str, object]:
    triples = []
    for index, relation_id in enumerate(candidate.relation_ids):
        subject_id = candidate.entity_ids[index]
        object_id = candidate.entity_ids[index + 1]
        triples.append(
            {
                "subject_id": subject_id,
                "subject_text": display_names[subject_id],
                "relation_id": relation_id,
                "relation_text": relation_labels.get(relation_id, relation_id),
                "object_id": object_id,
                "object_text": display_names[object_id],
            }
        )

    return {
        "template": candidate.template,
        "entity_ids": candidate.entity_ids,
        "entity_texts": [display_names[entity_id] for entity_id in candidate.entity_ids],
        "relation_ids": candidate.relation_ids,
        "relation_texts": [relation_labels.get(relation_id, relation_id) for relation_id in candidate.relation_ids],
        "triples": triples,
    }


def make_question_id(seed: str) -> str:
    return f"qa_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"


def standard_question_payload(
    candidate: CandidatePath,
    display_names: dict[str, str],
    relation_labels: dict[str, str],
) -> dict[str, object]:
    film_name = display_names[candidate.entity_ids[0]]
    person_name = display_names[candidate.entity_ids[1]]
    answer_name = display_names[candidate.entity_ids[-1]]

    if candidate.template == "film_director_birth_place":
        question = f"Where was the director of {film_name} born?"
        question_type = "two_hop"
        difficulty = "medium"
    elif candidate.template == "film_director_award":
        question = f"Which award was received by the director of {film_name}?"
        question_type = "two_hop"
        difficulty = "medium"
    elif candidate.template == "film_director_education":
        question = f"Where did the director of {film_name} study?"
        question_type = "two_hop"
        difficulty = "medium"
    elif candidate.template == "film_cast_birth_place":
        question = f"Where was {person_name}, a cast member of {film_name}, born?"
        question_type = "two_hop"
        difficulty = "medium"
    elif candidate.template == "film_cast_award":
        question = f"Which award was received by {person_name}, a cast member of {film_name}?"
        question_type = "two_hop"
        difficulty = "medium"
    elif candidate.template == "film_director_birth_place_country":
        question = f"In which country was the director of {film_name} born?"
        question_type = "three_hop"
        difficulty = "hard"
    elif candidate.template == "film_director_education_country":
        question = f"In which country is the school attended by the director of {film_name} located?"
        question_type = "three_hop"
        difficulty = "hard"
    elif candidate.template == "film_cast_birth_place_country":
        question = f"In which country was {person_name}, a cast member of {film_name}, born?"
        question_type = "three_hop"
        difficulty = "hard"
    else:
        raise ValueError(f"Unsupported standard template: {candidate.template}")

    question_id = make_question_id(f"standard|{candidate.template}|{'|'.join(candidate.entity_ids)}")
    return {
        "question_id": question_id,
        "language": LANGUAGE_TAG,
        "domain": DOMAIN_TAG,
        "question_type": question_type,
        "template": candidate.template,
        "difficulty": difficulty,
        "hop_count": len(candidate.relation_ids),
        "reasoning_path_count": 1,
        "question": question,
        "gold_answer": {
            "entity_id": candidate.entity_ids[-1],
            "text": answer_name,
        },
        "seed_entities": [
            {
                "entity_id": candidate.entity_ids[0],
                "text": film_name,
            }
        ],
        "supporting_paths": [
            build_path_payload(candidate, display_names, relation_labels),
        ],
    }


def comparison_question_payload(
    record: dict[str, object],
    display_names: dict[str, str],
    relation_labels: dict[str, str],
) -> dict[str, object]:
    first, second = record["candidates"]
    answer_is_same = record["same_answer"]
    first_country_name = display_names[first.entity_ids[-1]]
    second_country_name = display_names[second.entity_ids[-1]]
    boolean_answer = "yes" if first.entity_ids[-1] == second.entity_ids[-1] else "no"

    if record["template"] == "film_director_birth_place_country":
        question = (
            f"Were the directors of {display_names[first.entity_ids[0]]} and {display_names[second.entity_ids[0]]} "
            f"born in the same country?"
        )
    elif record["template"] == "film_director_education_country":
        question = (
            f"Were the directors of {display_names[first.entity_ids[0]]} and {display_names[second.entity_ids[0]]} "
            f"educated in the same country?"
        )
    elif record["template"] == "film_cast_birth_place_country":
        question = (
            f"Were {display_names[first.entity_ids[1]]} from {display_names[first.entity_ids[0]]} and "
            f"{display_names[second.entity_ids[1]]} from {display_names[second.entity_ids[0]]} born in the same country?"
        )
    else:
        raise ValueError(f"Unsupported comparison template: {record['template']}")

    question_id = make_question_id(
        "comparison|"
        + record["template"]
        + "|"
        + "|".join(first.entity_ids)
        + "|"
        + "|".join(second.entity_ids)
        + f"|{answer_is_same}"
    )
    return {
        "question_id": question_id,
        "language": LANGUAGE_TAG,
        "domain": DOMAIN_TAG,
        "question_type": "comparison",
        "template": f"{record['template']}__comparison",
        "comparison_base_template": record["template"],
        "difficulty": "very_hard",
        "hop_count": len(first.relation_ids),
        "reasoning_path_count": 2,
        "question": question,
        "gold_answer": {
            "entity_id": None,
            "text": boolean_answer,
        },
        "comparison_metadata": {
            "same_answer_requested": answer_is_same,
            "left_answer_text": first_country_name,
            "right_answer_text": second_country_name,
            "left_answer_id": first.entity_ids[-1],
            "right_answer_id": second.entity_ids[-1],
        },
        "seed_entities": [
            {"entity_id": first.entity_ids[0], "text": display_names[first.entity_ids[0]]},
            {"entity_id": second.entity_ids[0], "text": display_names[second.entity_ids[0]]},
        ],
        "supporting_paths": [
            build_path_payload(first, display_names, relation_labels),
            build_path_payload(second, display_names, relation_labels),
        ],
    }


def gather_required_triples(question_records: list[dict[str, object]]) -> set[tuple[str, str, str]]:
    required_triples: set[tuple[str, str, str]] = set()
    for question_record in question_records:
        for path in question_record["supporting_paths"]:
            for triple in path["triples"]:
                required_triples.add((triple["subject_id"], triple["relation_id"], triple["object_id"]))
    return required_triples


def verify_against_raw_triples(question_records: list[dict[str, object]]) -> dict[str, object]:
    required_triples = gather_required_triples(question_records)
    seen_triples: set[tuple[str, str, str]] = set()

    for row in iter_tsv_rows(TRIPLES_PATH):
        triple = (row[0], row[1], row[2])
        if triple in required_triples:
            seen_triples.add(triple)
            if len(seen_triples) == len(required_triples):
                break

    question_verification: list[dict[str, object]] = []
    for question_record in question_records:
        missing_triples = []
        for path in question_record["supporting_paths"]:
            for triple in path["triples"]:
                triple_key = (triple["subject_id"], triple["relation_id"], triple["object_id"])
                if triple_key not in seen_triples:
                    missing_triples.append(triple)
        question_record["raw_triple_verified"] = not missing_triples
        question_verification.append(
            {
                "question_id": question_record["question_id"],
                "verified": not missing_triples,
                "missing_triples": missing_triples,
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "required_triple_count": len(required_triples),
        "verified_triple_count": len(seen_triples),
        "question_verification": question_verification,
    }


def read_existing_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            records.append(json.loads(stripped))
    return records


def append_jsonl(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.write("\n")


def write_json(path: Path, payload: dict[str, object] | list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, payloads: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def compile_dataset_summary(
    question_records: list[dict[str, object]],
    verification_payload: dict[str, object],
    pool_counts: dict[str, int],
    selected_counts: dict[str, int],
) -> dict[str, object]:
    question_type_counts = Counter(record["question_type"] for record in question_records)
    template_counts = Counter(record["template"] for record in question_records)
    difficulty_counts = Counter(record["difficulty"] for record in question_records)
    hop_counts = Counter(str(record["hop_count"]) for record in question_records)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "question_count": len(question_records),
        "distribution": {
            "question_type": dict(question_type_counts),
            "template": dict(template_counts),
            "difficulty": dict(difficulty_counts),
            "hop_count": dict(hop_counts),
        },
        "pool_counts": pool_counts,
        "selected_counts": selected_counts,
        "validation": {
            "verified_questions": sum(
                1
                for question_result in verification_payload["question_verification"]
                if question_result["verified"]
            ),
            "failed_questions": sum(
                1
                for question_result in verification_payload["question_verification"]
                if not question_result["verified"]
            ),
            "required_triple_count": verification_payload["required_triple_count"],
            "verified_triple_count": verification_payload["verified_triple_count"],
        },
        "paths": {
            "append_only_jsonl": str(APPEND_ONLY_PATH),
            "dataset_json": str(FINAL_DATASET_JSON_PATH),
            "dataset_jsonl": str(FINAL_DATASET_JSONL_PATH),
            "raw_verification": str(RAW_VERIFICATION_PATH),
        },
    }


def generate_summary_markdown(summary: dict[str, object], question_records: list[dict[str, object]]) -> str:
    lines = [
        "# Phase 4 Verified Multi-Hop QA Dataset",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Total questions: `{summary['question_count']}`",
        f"- Verified questions: `{summary['validation']['verified_questions']}`",
        f"- Failed questions: `{summary['validation']['failed_questions']}`",
        "",
        "## Distribution",
        "",
    ]
    for category, values in summary["distribution"].items():
        lines.append(f"### {category.replace('_', ' ').title()}")
        lines.append("")
        for key, value in values.items():
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")

    lines.extend(["## Sample Questions", ""])
    for record in question_records[:10]:
        lines.append(
            f"- `{record['question_id']}` [{record['question_type']}] {record['question']} -> `{record['gold_answer']['text']}`"
        )
    lines.append("")
    return "\n".join(lines)


def persist_append_only_records(planned_records: list[dict[str, object]], append_only_path: Path) -> list[dict[str, object]]:
    existing_records = read_existing_jsonl(append_only_path)
    existing_by_id = {record["question_id"]: record for record in existing_records}

    for record in planned_records:
        if record["question_id"] in existing_by_id:
            continue
        append_jsonl(append_only_path, record)
        existing_by_id[record["question_id"]] = record

    ordered_records = [existing_by_id[record["question_id"]] for record in planned_records]
    return ordered_records


def run_generation(output_dir: Path) -> dict[str, object]:
    phase2_summary = load_phase2_summary(PHASE2_SUMMARY_PATH)
    relation_labels = load_relation_labels(RELATION_ALIAS_PATH)
    catalog = load_entity_catalog(PHASE3_ENTITIES_PATH)
    display_names = {
        entity_id: pick_display_name(entity)
        for entity_id, entity in catalog.items()
    }

    parsed_candidates = parse_candidate_pool(phase2_summary)
    filtered_pools = build_filtered_pools(parsed_candidates, catalog, display_names)
    pool_counts = {template: len(candidates) for template, candidates in filtered_pools.items()}

    film_usage: Counter[str] = Counter()
    person_usage: Counter[str] = Counter()
    answer_usage: Counter[str] = Counter()
    standard_candidates: list[CandidatePath] = []
    selected_counts: dict[str, int] = {}

    for template, quota in TEMPLATE_QUOTAS_2_HOP.items():
        chosen = choose_candidates_for_quota(
            template=template,
            target_count=quota,
            pool=filtered_pools.get(template, []),
            film_usage=film_usage,
            person_usage=person_usage,
            answer_usage=answer_usage,
        )
        if len(chosen) != quota:
            raise RuntimeError(f"Template {template} could not satisfy the quota {quota}; selected {len(chosen)}.")
        standard_candidates.extend(chosen)
        selected_counts[template] = len(chosen)

    for template, quota in TEMPLATE_QUOTAS_3_HOP.items():
        chosen = choose_candidates_for_quota(
            template=template,
            target_count=quota,
            pool=filtered_pools.get(template, []),
            film_usage=film_usage,
            person_usage=person_usage,
            answer_usage=answer_usage,
        )
        if len(chosen) != quota:
            raise RuntimeError(f"Template {template} could not satisfy the quota {quota}; selected {len(chosen)}.")
        standard_candidates.extend(chosen)
        selected_counts[template] = len(chosen)

    comparison_candidates = build_comparison_candidates(filtered_pools)
    selected_counts["comparison"] = len(comparison_candidates)

    question_records = [
        standard_question_payload(candidate, display_names, relation_labels)
        for candidate in standard_candidates
    ]
    question_records.extend(
        comparison_question_payload(record, display_names, relation_labels)
        for record in comparison_candidates
    )

    verification_payload = verify_against_raw_triples(question_records)
    failed_questions = [
        question_result["question_id"]
        for question_result in verification_payload["question_verification"]
        if not question_result["verified"]
    ]
    if failed_questions:
        raise RuntimeError(f"Raw triple verification failed for questions: {failed_questions}")

    ordered_records = persist_append_only_records(question_records, output_dir / APPEND_ONLY_PATH.name)
    write_json(output_dir / FINAL_DATASET_JSON_PATH.name, ordered_records)
    write_jsonl(output_dir / FINAL_DATASET_JSONL_PATH.name, ordered_records)
    write_json(output_dir / RAW_VERIFICATION_PATH.name, verification_payload)

    dataset_summary = compile_dataset_summary(
        question_records=ordered_records,
        verification_payload=verification_payload,
        pool_counts=pool_counts,
        selected_counts=selected_counts,
    )
    write_json(output_dir / DATASET_SUMMARY_JSON_PATH.name, dataset_summary)
    write_text(output_dir / DATASET_SUMMARY_MD_PATH.name, generate_summary_markdown(dataset_summary, ordered_records))

    selection_audit = {
        "generated_at": datetime.now(UTC).isoformat(),
        "pool_counts": pool_counts,
        "selected_counts": selected_counts,
        "selected_question_ids": [record["question_id"] for record in ordered_records],
    }
    write_json(output_dir / SELECTION_AUDIT_PATH.name, selection_audit)

    return {
        "question_count": len(ordered_records),
        "question_type_counts": dataset_summary["distribution"]["question_type"],
        "template_counts": dataset_summary["distribution"]["template"],
        "output_dir": str(output_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a verified, graph-first, append-only Phase 4 multi-hop QA dataset for Turkiye cinema.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where Phase 4 artifacts will be written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_generation(args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
