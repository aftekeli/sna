from __future__ import annotations

import argparse
import json
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = REPO_ROOT / "wikidata5m" / "wikidata5m_raw_data"
ENTITY_ALIAS_PATH = RAW_DATA_DIR / "wikidata5m_alias" / "wikidata5m_entity.txt"
RELATION_ALIAS_PATH = RAW_DATA_DIR / "wikidata5m_alias" / "wikidata5m_relation.txt"
TRIPLES_PATH = RAW_DATA_DIR / "wikidata5m_all_triplet.txt"
TEXT_PATH = RAW_DATA_DIR / "wikidata5m_text.txt"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "phase-2"

RELATION_IDS = {
    "director": "P57",
    "cast_member": "P161",
    "award_received": "P166",
    "country_of_origin": "P495",
    "place_of_birth": "P19",
    "educated_at": "P69",
    "country": "P17",
    "country_of_citizenship": "P27",
    "instance_of": "P31",
}

FILM_RELATION_IDS = {
    RELATION_IDS["director"],
    RELATION_IDS["cast_member"],
    RELATION_IDS["award_received"],
    RELATION_IDS["country_of_origin"],
    RELATION_IDS["instance_of"],
}
PERSON_RELATION_IDS = {
    RELATION_IDS["place_of_birth"],
    RELATION_IDS["educated_at"],
    RELATION_IDS["award_received"],
    RELATION_IDS["country_of_citizenship"],
    RELATION_IDS["instance_of"],
}
LOCATION_RELATION_IDS = {
    RELATION_IDS["country"],
    RELATION_IDS["instance_of"],
}
TURKEY_ALIASES = {
    "turkiye",
    "tuerkiye",
    "turkey",
    "republic of turkey",
    "turkiye cumhuriyeti",
    "tuerkiye cumhuriyeti",
}
PATH_TEMPLATE_ORDER = [
    "film_director_birth_place",
    "film_director_award",
    "film_director_education",
    "film_cast_birth_place",
    "film_cast_award",
    "film_director_birth_place_country",
    "film_director_education_country",
    "film_cast_birth_place_country",
]
FILM_INCLUDE_KEYWORDS = (
    "film",
    "movie",
    "documentary",
    "short film",
    "feature film",
    "cinema",
)
FILM_EXCLUDE_KEYWORDS = (
    "television series",
    "tv series",
    "television program",
    "episode",
    "season",
    "soap opera",
    "soundtrack",
    "discography",
)
PERSON_INCLUDE_KEYWORDS = (
    "human",
    "person",
    "actor",
    "actress",
    "director",
    "filmmaker",
    "screenwriter",
    "producer",
    "cinematographer",
)
PERSON_EXCLUDE_KEYWORDS = (
    "filmography",
    "discography",
    "television work",
    "short story collection",
    "award",
    "fictional character",
    "album",
)


@dataclass(slots=True)
class PathCandidate:
    template: str
    entity_ids: list[str]
    relation_ids: list[str]

    def key(self) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        return (self.template, tuple(self.entity_ids), tuple(self.relation_ids))


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_only.strip().casefold()


def iter_tsv_rows(path: Path) -> Iterable[list[str]]:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            yield line.split("\t")


def load_relation_labels(path: Path) -> dict[str, str]:
    relation_labels: dict[str, str] = {}
    for row in iter_tsv_rows(path):
        relation_id = row[0]
        aliases = [alias for alias in row[1:] if alias]
        relation_labels[relation_id] = aliases[0] if aliases else relation_id
    return relation_labels


def find_turkey_candidates(path: Path) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = {}
    for row in iter_tsv_rows(path):
        entity_id = row[0]
        aliases = [alias for alias in row[1:] if alias]
        normalized_aliases = {normalize_text(alias) for alias in aliases}
        if normalized_aliases & TURKEY_ALIASES:
            candidates[entity_id] = aliases
    return candidates


def choose_turkey_root(triples_path: Path, candidate_ids: set[str]) -> tuple[str, dict[str, dict[str, int]]]:
    if not candidate_ids:
        raise RuntimeError("No Turkiye candidate entities were found in the alias file.")

    candidate_stats: dict[str, Counter[str]] = {entity_id: Counter() for entity_id in candidate_ids}
    country_relations = {
        RELATION_IDS["country"],
        RELATION_IDS["country_of_citizenship"],
        RELATION_IDS["country_of_origin"],
    }
    for row in iter_tsv_rows(triples_path):
        subject_id, relation_id, object_id = row[:3]
        if subject_id in candidate_ids:
            candidate_stats[subject_id]["outgoing_edges"] += 1
            candidate_stats[subject_id][f"outgoing::{relation_id}"] += 1
        if object_id in candidate_ids:
            candidate_stats[object_id]["incoming_edges"] += 1
            candidate_stats[object_id][f"incoming::{relation_id}"] += 1
            if relation_id in country_relations:
                candidate_stats[object_id]["country_signal"] += 1

    scored = []
    for entity_id, stats in candidate_stats.items():
        score = (
            stats["country_signal"] * 20
            + stats["incoming_edges"] * 2
            + stats["outgoing_edges"]
        )
        scored.append((score, entity_id))

    scored.sort(reverse=True)
    selected_id = scored[0][1]
    serializable_stats = {
        entity_id: dict(counter)
        for entity_id, counter in candidate_stats.items()
    }
    return selected_id, serializable_stats


def collect_turkey_context(
    triples_path: Path,
    turkey_id: str,
) -> tuple[set[str], set[str], Counter[str], Counter[str]]:
    turkey_origin_subjects: set[str] = set()
    turkey_citizenship_subjects: set[str] = set()
    turkey_relation_counts: Counter[str] = Counter()
    turkey_neighbor_counts: Counter[str] = Counter()

    for row in iter_tsv_rows(triples_path):
        subject_id, relation_id, object_id = row[:3]
        if relation_id == RELATION_IDS["country_of_origin"] and object_id == turkey_id:
            turkey_origin_subjects.add(subject_id)
        if relation_id == RELATION_IDS["country_of_citizenship"] and object_id == turkey_id:
            turkey_citizenship_subjects.add(subject_id)
        if subject_id == turkey_id:
            turkey_relation_counts[f"outgoing::{relation_id}"] += 1
            turkey_neighbor_counts[object_id] += 1
        elif object_id == turkey_id:
            turkey_relation_counts[f"incoming::{relation_id}"] += 1
            turkey_neighbor_counts[subject_id] += 1

    return (
        turkey_origin_subjects,
        turkey_citizenship_subjects,
        turkey_relation_counts,
        turkey_neighbor_counts,
    )


def collect_film_edges(
    triples_path: Path,
    turkey_origin_subjects: set[str],
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, set[str]], dict[str, set[str]]]:
    film_edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
    film_to_directors: dict[str, set[str]] = defaultdict(set)
    film_to_cast: dict[str, set[str]] = defaultdict(set)

    for row in iter_tsv_rows(triples_path):
        subject_id, relation_id, object_id = row[:3]
        if subject_id not in turkey_origin_subjects:
            continue
        if relation_id not in FILM_RELATION_IDS:
            continue

        film_edges[subject_id].append((relation_id, object_id))
        if relation_id == RELATION_IDS["director"]:
            film_to_directors[subject_id].add(object_id)
        elif relation_id == RELATION_IDS["cast_member"]:
            film_to_cast[subject_id].add(object_id)

    return film_edges, film_to_directors, film_to_cast


def identify_turkish_films(
    film_edges: dict[str, list[tuple[str, str]]],
    film_to_directors: dict[str, set[str]],
    film_to_cast: dict[str, set[str]],
) -> set[str]:
    turkish_films: set[str] = set()
    for entity_id, edges in film_edges.items():
        has_cinema_edge = bool(film_to_directors.get(entity_id) or film_to_cast.get(entity_id))
        has_award_signal = any(relation_id == RELATION_IDS["award_received"] for relation_id, _ in edges)
        if has_cinema_edge or has_award_signal:
            turkish_films.add(entity_id)
    return turkish_films


def collect_instance_targets(
    edges_by_entity: dict[str, list[tuple[str, str]]],
) -> dict[str, set[str]]:
    instance_targets: dict[str, set[str]] = defaultdict(set)
    for entity_id, edges in edges_by_entity.items():
        for relation_id, target_id in edges:
            if relation_id == RELATION_IDS["instance_of"]:
                instance_targets[entity_id].add(target_id)
    return instance_targets


def contains_any_keyword(value: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in value for keyword in keywords)


def is_valid_film_entity(
    entity_id: str,
    instance_targets: dict[str, set[str]],
    labels: dict[str, str],
    descriptions: dict[str, str],
) -> bool:
    description = normalize_text(descriptions.get(entity_id, ""))
    instance_labels = [
        normalize_text(labels.get(instance_id, instance_id))
        for instance_id in instance_targets.get(entity_id, set())
    ]
    combined_instance_text = " | ".join(instance_labels)

    has_include_signal = contains_any_keyword(description, FILM_INCLUDE_KEYWORDS) or contains_any_keyword(
        combined_instance_text,
        FILM_INCLUDE_KEYWORDS,
    )
    has_exclude_signal = contains_any_keyword(description, FILM_EXCLUDE_KEYWORDS) or contains_any_keyword(
        combined_instance_text,
        FILM_EXCLUDE_KEYWORDS,
    )
    return has_include_signal and not has_exclude_signal


def is_valid_person_entity(
    entity_id: str,
    instance_targets: dict[str, set[str]],
    labels: dict[str, str],
    descriptions: dict[str, str],
) -> bool:
    label = normalize_text(labels.get(entity_id, entity_id))
    description = normalize_text(descriptions.get(entity_id, ""))
    instance_labels = [
        normalize_text(labels.get(instance_id, instance_id))
        for instance_id in instance_targets.get(entity_id, set())
    ]
    combined_text = " | ".join([label, description, *instance_labels])
    has_include_signal = contains_any_keyword(combined_text, PERSON_INCLUDE_KEYWORDS)
    has_exclude_signal = contains_any_keyword(combined_text, PERSON_EXCLUDE_KEYWORDS)
    return has_include_signal and not has_exclude_signal


def filter_film_relationships(
    turkish_films: set[str],
    film_to_directors: dict[str, set[str]],
    film_to_cast: dict[str, set[str]],
    valid_people: set[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    filtered_directors: dict[str, set[str]] = {}
    filtered_cast: dict[str, set[str]] = {}

    for film_id in turkish_films:
        directors = {
            entity_id
            for entity_id in film_to_directors.get(film_id, set())
            if entity_id in valid_people
        }
        cast_members = {
            entity_id
            for entity_id in film_to_cast.get(film_id, set())
            if entity_id in valid_people
        }
        if directors:
            filtered_directors[film_id] = directors
        if cast_members:
            filtered_cast[film_id] = cast_members

    return filtered_directors, filtered_cast


def collect_person_edges(
    triples_path: Path,
    people_of_interest: set[str],
) -> tuple[dict[str, list[tuple[str, str]]], set[str]]:
    person_edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
    second_hop_nodes: set[str] = set()

    for row in iter_tsv_rows(triples_path):
        subject_id, relation_id, object_id = row[:3]
        if subject_id not in people_of_interest or relation_id not in PERSON_RELATION_IDS:
            continue
        person_edges[subject_id].append((relation_id, object_id))
        if relation_id in {RELATION_IDS["place_of_birth"], RELATION_IDS["educated_at"]}:
            second_hop_nodes.add(object_id)

    return person_edges, second_hop_nodes


def collect_location_edges(
    triples_path: Path,
    location_nodes: set[str],
) -> dict[str, list[tuple[str, str]]]:
    location_edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in iter_tsv_rows(triples_path):
        subject_id, relation_id, object_id = row[:3]
        if subject_id not in location_nodes or relation_id not in LOCATION_RELATION_IDS:
            continue
        location_edges[subject_id].append((relation_id, object_id))
    return location_edges


def count_relation_frequency(
    film_edges: dict[str, list[tuple[str, str]]],
    person_edges: dict[str, list[tuple[str, str]]],
) -> Counter[str]:
    relation_counts: Counter[str] = Counter()
    for edges in film_edges.values():
        for relation_id, _ in edges:
            relation_counts[relation_id] += 1
    for edges in person_edges.values():
        for relation_id, _ in edges:
            relation_counts[relation_id] += 1
    return relation_counts


def build_path_candidates(
    film_to_directors: dict[str, set[str]],
    film_to_cast: dict[str, set[str]],
    person_edges: dict[str, list[tuple[str, str]]],
    location_edges: dict[str, list[tuple[str, str]]],
) -> dict[str, list[PathCandidate]]:
    deduped: dict[str, dict[tuple[str, tuple[str, ...], tuple[str, ...]], PathCandidate]] = {
        template: {}
        for template in PATH_TEMPLATE_ORDER
    }

    def add_candidate(template: str, entity_ids: list[str], relation_ids: list[str]) -> None:
        candidate = PathCandidate(
            template=template,
            entity_ids=entity_ids,
            relation_ids=relation_ids,
        )
        deduped[template][candidate.key()] = candidate

    def unique_country_target(node_id: str) -> str | None:
        country_targets = {
            target_id
            for relation_id, target_id in location_edges.get(node_id, [])
            if relation_id == RELATION_IDS["country"]
        }
        if len(country_targets) != 1:
            return None
        return next(iter(country_targets))

    for film_id, directors in film_to_directors.items():
        for director_id in directors:
            for relation_id, target_id in person_edges.get(director_id, []):
                if relation_id == RELATION_IDS["place_of_birth"]:
                    add_candidate(
                        "film_director_birth_place",
                        [film_id, director_id, target_id],
                        [RELATION_IDS["director"], RELATION_IDS["place_of_birth"]],
                    )
                    location_target = unique_country_target(target_id)
                    if location_target:
                        add_candidate(
                            "film_director_birth_place_country",
                            [film_id, director_id, target_id, location_target],
                            [
                                RELATION_IDS["director"],
                                RELATION_IDS["place_of_birth"],
                                RELATION_IDS["country"],
                            ],
                        )
                elif relation_id == RELATION_IDS["award_received"]:
                    add_candidate(
                        "film_director_award",
                        [film_id, director_id, target_id],
                        [RELATION_IDS["director"], RELATION_IDS["award_received"]],
                    )
                elif relation_id == RELATION_IDS["educated_at"]:
                    add_candidate(
                        "film_director_education",
                        [film_id, director_id, target_id],
                        [RELATION_IDS["director"], RELATION_IDS["educated_at"]],
                    )
                    location_target = unique_country_target(target_id)
                    if location_target:
                        add_candidate(
                            "film_director_education_country",
                            [film_id, director_id, target_id, location_target],
                            [
                                RELATION_IDS["director"],
                                RELATION_IDS["educated_at"],
                                RELATION_IDS["country"],
                            ],
                        )

    for film_id, cast_members in film_to_cast.items():
        for cast_id in cast_members:
            for relation_id, target_id in person_edges.get(cast_id, []):
                if relation_id == RELATION_IDS["place_of_birth"]:
                    add_candidate(
                        "film_cast_birth_place",
                        [film_id, cast_id, target_id],
                        [RELATION_IDS["cast_member"], RELATION_IDS["place_of_birth"]],
                    )
                    location_target = unique_country_target(target_id)
                    if location_target:
                        add_candidate(
                            "film_cast_birth_place_country",
                            [film_id, cast_id, target_id, location_target],
                            [
                                RELATION_IDS["cast_member"],
                                RELATION_IDS["place_of_birth"],
                                RELATION_IDS["country"],
                            ],
                        )
                elif relation_id == RELATION_IDS["award_received"]:
                    add_candidate(
                        "film_cast_award",
                        [film_id, cast_id, target_id],
                        [RELATION_IDS["cast_member"], RELATION_IDS["award_received"]],
                    )

    return {
        template: list(candidates.values())
        for template, candidates in deduped.items()
    }


def collect_entity_metadata(
    alias_path: Path,
    text_path: Path,
    entity_ids: set[str],
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, str]]:
    labels: dict[str, str] = {}
    aliases: dict[str, list[str]] = {}
    descriptions: dict[str, str] = {}

    for row in iter_tsv_rows(alias_path):
        entity_id = row[0]
        if entity_id not in entity_ids:
            continue
        entity_aliases = [alias for alias in row[1:] if alias]
        if entity_aliases:
            labels[entity_id] = entity_aliases[0]
            aliases[entity_id] = entity_aliases[:10]

    for row in iter_tsv_rows(text_path):
        entity_id = row[0]
        if entity_id not in entity_ids:
            continue
        description = row[1] if len(row) > 1 else ""
        descriptions[entity_id] = description

    return labels, aliases, descriptions


def materialize_path_candidate(
    candidate: PathCandidate,
    labels: dict[str, str],
    relation_labels: dict[str, str],
) -> dict[str, object]:
    return {
        "template": candidate.template,
        "entity_ids": candidate.entity_ids,
        "entity_names": [labels.get(entity_id, entity_id) for entity_id in candidate.entity_ids],
        "relation_ids": candidate.relation_ids,
        "relation_names": [
            relation_labels.get(relation_id, relation_id)
            for relation_id in candidate.relation_ids
        ],
    }


def build_seed_rankings(
    turkish_films: set[str],
    film_to_directors: dict[str, set[str]],
    film_to_cast: dict[str, set[str]],
    person_edges: dict[str, list[tuple[str, str]]],
    labels: dict[str, str],
) -> dict[str, list[dict[str, object]]]:
    film_rankings = []
    for film_id in turkish_films:
        film_rankings.append(
            {
                "entity_id": film_id,
                "name": labels.get(film_id, film_id),
                "director_count": len(film_to_directors.get(film_id, set())),
                "cast_count": len(film_to_cast.get(film_id, set())),
                "supporting_edges": len(film_to_directors.get(film_id, set()))
                + len(film_to_cast.get(film_id, set())),
            }
        )
    film_rankings.sort(
        key=lambda item: (
            item["supporting_edges"],
            item["cast_count"],
            item["director_count"],
            item["name"],
        ),
        reverse=True,
    )

    people_rankings = []
    for person_id, edges in person_edges.items():
        people_rankings.append(
            {
                "entity_id": person_id,
                "name": labels.get(person_id, person_id),
                "relevant_edge_count": len(edges),
            }
        )
    people_rankings.sort(
        key=lambda item: (item["relevant_edge_count"], item["name"]),
        reverse=True,
    )
    return {
        "top_films": film_rankings[:25],
        "top_people": people_rankings[:25],
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def generate_markdown_report(summary: dict[str, object]) -> str:
    turkey_root = summary["turkey_root"]
    cinema_stats = summary["cinema_stats"]
    relation_frequency = summary["relation_frequency"]
    path_summary = summary["path_summary"]
    seed_rankings = summary["seed_rankings"]

    lines = [
        "# Phase 2 Exploration Report",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Turkey root entity: `{turkey_root['entity_id']}` ({turkey_root['name']})",
        f"- Candidate entities checked: `{turkey_root['candidate_count']}`",
        f"- Turkish origin subjects: `{cinema_stats['turkish_origin_subject_count']}`",
        f"- Turkish citizenship subjects: `{cinema_stats['turkish_citizenship_subject_count']}`",
        f"- Turkish cinema film candidates: `{cinema_stats['turkish_film_count']}`",
        f"- Cinema people of interest: `{cinema_stats['cinema_people_count']}`",
        "",
        "## Top Relation Frequency",
        "",
    ]
    for item in relation_frequency[:10]:
        lines.append(f"- `{item['relation_id']}` {item['relation_name']}: `{item['count']}`")

    lines.extend(
        [
            "",
            "## Verified Path Candidates",
            "",
        ]
    )
    for item in path_summary:
        lines.append(f"- `{item['template']}`: `{item['count']}`")

    lines.extend(
        [
            "",
            "## Top Film Seeds",
            "",
        ]
    )
    for item in seed_rankings["top_films"][:10]:
        lines.append(
            f"- `{item['entity_id']}` {item['name']}: directors=`{item['director_count']}`, cast=`{item['cast_count']}`"
        )

    lines.extend(
        [
            "",
            "## Top People Seeds",
            "",
        ]
    )
    for item in seed_rankings["top_people"][:10]:
        lines.append(
            f"- `{item['entity_id']}` {item['name']}: relevant edges=`{item['relevant_edge_count']}`"
        )

    return "\n".join(lines) + "\n"


def run_exploration(output_dir: Path) -> dict[str, object]:
    relation_labels = load_relation_labels(RELATION_ALIAS_PATH)
    turkey_candidates = find_turkey_candidates(ENTITY_ALIAS_PATH)
    turkey_id, turkey_candidate_stats = choose_turkey_root(TRIPLES_PATH, set(turkey_candidates))

    (
        turkey_origin_subjects,
        turkey_citizenship_subjects,
        turkey_relation_counts,
        turkey_neighbor_counts,
    ) = collect_turkey_context(TRIPLES_PATH, turkey_id)

    film_edges, film_to_directors, film_to_cast = collect_film_edges(
        TRIPLES_PATH,
        turkey_origin_subjects,
    )
    provisional_films = identify_turkish_films(film_edges, film_to_directors, film_to_cast)
    provisional_people = set()
    for director_ids in film_to_directors.values():
        provisional_people.update(director_ids)
    for cast_ids in film_to_cast.values():
        provisional_people.update(cast_ids)

    person_edges, second_hop_nodes = collect_person_edges(TRIPLES_PATH, provisional_people)
    film_instance_targets = collect_instance_targets(film_edges)
    person_instance_targets = collect_instance_targets(person_edges)

    metadata_ids = {turkey_id}
    metadata_ids.update(turkey_neighbor_counts.keys())
    metadata_ids.update(provisional_films)
    metadata_ids.update(provisional_people)
    metadata_ids.update(second_hop_nodes)
    for instance_ids in film_instance_targets.values():
        metadata_ids.update(instance_ids)
    for instance_ids in person_instance_targets.values():
        metadata_ids.update(instance_ids)

    labels, aliases, descriptions = collect_entity_metadata(
        ENTITY_ALIAS_PATH,
        TEXT_PATH,
        metadata_ids,
    )

    valid_turkish_films = {
        entity_id
        for entity_id in provisional_films
        if is_valid_film_entity(
            entity_id=entity_id,
            instance_targets=film_instance_targets,
            labels=labels,
            descriptions=descriptions,
        )
    }
    valid_people = {
        entity_id
        for entity_id in provisional_people
        if is_valid_person_entity(
            entity_id=entity_id,
            instance_targets=person_instance_targets,
            labels=labels,
            descriptions=descriptions,
        )
    }
    filtered_directors, filtered_cast = filter_film_relationships(
        turkish_films=valid_turkish_films,
        film_to_directors=film_to_directors,
        film_to_cast=film_to_cast,
        valid_people=valid_people,
    )
    filtered_people = set()
    for entity_ids in filtered_directors.values():
        filtered_people.update(entity_ids)
    for entity_ids in filtered_cast.values():
        filtered_people.update(entity_ids)

    filtered_person_edges = {
        entity_id: person_edges[entity_id]
        for entity_id in filtered_people
        if entity_id in person_edges
    }
    filtered_second_hop_nodes = set()
    for edges in filtered_person_edges.values():
        for relation_id, target_id in edges:
            if relation_id in {RELATION_IDS["place_of_birth"], RELATION_IDS["educated_at"]}:
                filtered_second_hop_nodes.add(target_id)

    location_edges = collect_location_edges(TRIPLES_PATH, filtered_second_hop_nodes)
    filtered_film_edges = {
        entity_id: film_edges[entity_id]
        for entity_id in valid_turkish_films
        if entity_id in film_edges
    }
    relation_frequency = count_relation_frequency(filtered_film_edges, filtered_person_edges)
    path_candidates = build_path_candidates(
        film_to_directors=filtered_directors,
        film_to_cast=filtered_cast,
        person_edges=filtered_person_edges,
        location_edges=location_edges,
    )

    entity_ids_for_output = set(metadata_ids)
    entity_ids_for_output.update(valid_turkish_films)
    entity_ids_for_output.update(filtered_people)
    entity_ids_for_output.update(filtered_second_hop_nodes)
    for edges in location_edges.values():
        for _, target_id in edges:
            entity_ids_for_output.add(target_id)
    for candidates in path_candidates.values():
        for candidate in candidates:
            entity_ids_for_output.update(candidate.entity_ids)

    labels, aliases, descriptions = collect_entity_metadata(
        ENTITY_ALIAS_PATH,
        TEXT_PATH,
        entity_ids_for_output,
    )

    seed_rankings = build_seed_rankings(
        turkish_films=valid_turkish_films,
        film_to_directors=filtered_directors,
        film_to_cast=filtered_cast,
        person_edges=filtered_person_edges,
        labels=labels,
    )
    serialized_path_candidates = {
        template: [
            materialize_path_candidate(candidate, labels, relation_labels)
            for candidate in candidates[:200]
        ]
        for template, candidates in path_candidates.items()
    }
    path_summary = [
        {"template": template, "count": len(path_candidates[template])}
        for template in PATH_TEMPLATE_ORDER
    ]
    relation_frequency_list = [
        {
            "relation_id": relation_id,
            "relation_name": relation_labels.get(relation_id, relation_id),
            "count": count,
        }
        for relation_id, count in relation_frequency.most_common(20)
    ]
    top_turkey_neighbors = [
        {
            "entity_id": entity_id,
            "name": labels.get(entity_id, entity_id),
            "touch_count": count,
        }
        for entity_id, count in turkey_neighbor_counts.most_common(20)
    ]

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "inputs": {
            "entity_alias_path": str(ENTITY_ALIAS_PATH),
            "relation_alias_path": str(RELATION_ALIAS_PATH),
            "triples_path": str(TRIPLES_PATH),
            "text_path": str(TEXT_PATH),
        },
        "turkey_root": {
            "entity_id": turkey_id,
            "name": labels.get(turkey_id, turkey_id),
            "aliases": aliases.get(turkey_id, turkey_candidates.get(turkey_id, [])[:10]),
            "description": descriptions.get(turkey_id, ""),
            "candidate_count": len(turkey_candidates),
            "candidate_stats": turkey_candidate_stats,
            "direct_relation_counts": dict(turkey_relation_counts),
            "top_neighbors": top_turkey_neighbors,
        },
        "cinema_stats": {
            "turkish_origin_subject_count": len(turkey_origin_subjects),
            "turkish_citizenship_subject_count": len(turkey_citizenship_subjects),
            "provisional_film_count": len(provisional_films),
            "turkish_film_count": len(valid_turkish_films),
            "provisional_people_count": len(provisional_people),
            "cinema_people_count": len(filtered_people),
            "second_hop_node_count": len(filtered_second_hop_nodes),
        },
        "relation_frequency": relation_frequency_list,
        "path_summary": path_summary,
        "path_candidates": serialized_path_candidates,
        "seed_rankings": seed_rankings,
    }

    write_json(output_dir / "turkiye_cinema_summary.json", summary)
    write_markdown(output_dir / "turkiye_cinema_summary.md", generate_markdown_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explore Turkiye + cinema signals in Wikidata5M and export reusable Phase 2 artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the Phase 2 outputs will be written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_exploration(args.output_dir)
    print(
        json.dumps(
            {
                "turkey_root": summary["turkey_root"]["entity_id"],
                "turkish_film_count": summary["cinema_stats"]["turkish_film_count"],
                "cinema_people_count": summary["cinema_stats"]["cinema_people_count"],
                "path_summary": summary["path_summary"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
