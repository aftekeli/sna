from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from explore_turkiye_cinema import (
    ENTITY_ALIAS_PATH,
    RELATION_ALIAS_PATH,
    RELATION_IDS,
    TEXT_PATH,
    TRIPLES_PATH,
    collect_entity_metadata,
    iter_tsv_rows,
    load_relation_labels,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE2_SUMMARY_PATH = REPO_ROOT / "artifacts" / "phase-2" / "turkiye_cinema_summary.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "phase-3"
SUBGRAPH_RELATION_IDS = {
    RELATION_IDS["director"],
    RELATION_IDS["cast_member"],
    RELATION_IDS["award_received"],
    RELATION_IDS["country_of_origin"],
    RELATION_IDS["place_of_birth"],
    RELATION_IDS["educated_at"],
    RELATION_IDS["country"],
    RELATION_IDS["country_of_citizenship"],
    RELATION_IDS["instance_of"],
}


def load_phase2_summary(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_entity_ids(summary: dict[str, object]) -> tuple[set[str], dict[str, set[str]]]:
    entity_ids: set[str] = set()
    entity_roles: dict[str, set[str]] = defaultdict(set)

    turkey_root = summary["turkey_root"]
    entity_ids.add(turkey_root["entity_id"])
    entity_roles[turkey_root["entity_id"]].add("country_root")

    for item in turkey_root["top_neighbors"]:
        entity_ids.add(item["entity_id"])
        entity_roles[item["entity_id"]].add("turkey_neighbor")

    for item in summary["seed_rankings"]["top_films"]:
        entity_ids.add(item["entity_id"])
        entity_roles[item["entity_id"]].add("film_seed")

    for item in summary["seed_rankings"]["top_people"]:
        entity_ids.add(item["entity_id"])
        entity_roles[item["entity_id"]].add("person_seed")

    for template, candidates in summary["path_candidates"].items():
        for candidate in candidates:
            ids = candidate["entity_ids"]
            for entity_id in ids:
                entity_ids.add(entity_id)
            if template.startswith("film_director"):
                if len(ids) >= 1:
                    entity_roles[ids[0]].add("film")
                if len(ids) >= 2:
                    entity_roles[ids[1]].add("director")
            elif template.startswith("film_cast"):
                if len(ids) >= 1:
                    entity_roles[ids[0]].add("film")
                if len(ids) >= 2:
                    entity_roles[ids[1]].add("cast_member")

            if "birth_place" in template:
                if len(ids) >= 3:
                    entity_roles[ids[2]].add("birth_place")
            elif "education" in template:
                if len(ids) >= 3:
                    entity_roles[ids[2]].add("education_entity")
            elif "award" in template:
                if len(ids) >= 3:
                    entity_roles[ids[2]].add("award")

            if template.endswith("_country") and len(ids) >= 4:
                entity_roles[ids[3]].add("country")

    return entity_ids, entity_roles


def derive_domain_tags(role_map: set[str]) -> list[str]:
    tags = {"cinema", "turkiye"}
    if "country_root" in role_map or "country" in role_map:
        tags.add("geography")
    if "director" in role_map or "cast_member" in role_map or "person_seed" in role_map:
        tags.add("people")
    if "film" in role_map or "film_seed" in role_map:
        tags.add("film")
    if "award" in role_map:
        tags.add("award")
    if "education_entity" in role_map:
        tags.add("education")
    return sorted(tags)


def collect_subgraph_edges(
    entity_ids: set[str],
    relation_labels: dict[str, str],
) -> list[dict[str, object]]:
    edges: list[dict[str, object]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    for row in iter_tsv_rows(TRIPLES_PATH):
        source_id, relation_id, target_id = row[:3]
        if relation_id not in SUBGRAPH_RELATION_IDS:
            continue
        if source_id not in entity_ids or target_id not in entity_ids:
            continue
        edge_key = (source_id, relation_id, target_id)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        edges.append(
            {
                "source_id": source_id,
                "pid": relation_id,
                "relation_label": relation_labels.get(relation_id, relation_id),
                "target_id": target_id,
            }
        )

    return edges


def write_nodes_csv(
    path: Path,
    entity_ids: set[str],
    role_map: dict[str, set[str]],
    labels: dict[str, str],
    aliases: dict[str, list[str]],
    descriptions: dict[str, str],
) -> list[dict[str, object]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
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
        for entity_id in sorted(entity_ids):
            roles = sorted(role_map.get(entity_id, {"context"}))
            alias_values = aliases.get(entity_id, [labels.get(entity_id, entity_id)])
            row = {
                "entity_id": entity_id,
                "canonical_name": labels.get(entity_id, entity_id),
                "description": descriptions.get(entity_id, ""),
                "aliases_json": json.dumps(alias_values, ensure_ascii=False),
                "aliases_text": " | ".join(alias_values),
                "domains_json": json.dumps(derive_domain_tags(set(roles)), ensure_ascii=False),
                "roles_json": json.dumps(roles, ensure_ascii=False),
                "is_turkiye_related": "true",
            }
            writer.writerow(row)
            rows.append(row)
    return rows


def write_edges_csv(path: Path, edges: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["source_id", "pid", "relation_label", "target_id"],
        )
        writer.writeheader()
        writer.writerows(edges)


def build_cypher_library(summary: dict[str, object]) -> str:
    sample_birth_place = summary["path_candidates"]["film_director_birth_place"][0]
    sample_birth_place_country = summary["path_candidates"]["film_director_birth_place_country"][0]

    lines = [
        "// Phase 3 Cypher starter library",
        "",
        "// 1-hop: films tied to Turkiye by country of origin",
        "MATCH (film:Entity)-[r:REL {pid: 'P495'}]->(country:Entity {entity_id: 'Q43'})",
        "RETURN film.entity_id AS film_id, film.canonical_name AS film_name, country.canonical_name AS country_name",
        "LIMIT 25;",
        "",
        "// 2-hop: film -> director -> birth place",
        "MATCH (film:Entity)-[:REL {pid: 'P57'}]->(director:Entity)-[:REL {pid: 'P19'}]->(birth_place:Entity)",
        "RETURN film.canonical_name AS film, director.canonical_name AS director, birth_place.canonical_name AS birth_place",
        "LIMIT 25;",
        "",
        "// 3-hop: film -> director -> birth place -> country",
        "MATCH (film:Entity)-[:REL {pid: 'P57'}]->(director:Entity)-[:REL {pid: 'P19'}]->(birth_place:Entity)-[:REL {pid: 'P17'}]->(country:Entity)",
        "RETURN film.canonical_name AS film, director.canonical_name AS director, birth_place.canonical_name AS birth_place, country.canonical_name AS country",
        "LIMIT 25;",
        "",
        "// Example-specific 2-hop verification",
        f"MATCH (film:Entity {{entity_id: '{sample_birth_place['entity_ids'][0]}'}})-[:REL {{pid: 'P57'}}]->(director:Entity)-[:REL {{pid: 'P19'}}]->(birth_place:Entity)",
        "RETURN film.canonical_name AS film, director.canonical_name AS director, birth_place.canonical_name AS birth_place;",
        "",
        "// Example-specific 3-hop verification",
        f"MATCH (film:Entity {{entity_id: '{sample_birth_place_country['entity_ids'][0]}'}})-[:REL {{pid: 'P57'}}]->(director:Entity)-[:REL {{pid: 'P19'}}]->(birth_place:Entity)-[:REL {{pid: 'P17'}}]->(country:Entity)",
        "RETURN film.canonical_name AS film, director.canonical_name AS director, birth_place.canonical_name AS birth_place, country.canonical_name AS country;",
        "",
    ]
    return "\n".join(lines)


def build_phase3_summary(
    node_rows: list[dict[str, object]],
    edges: list[dict[str, object]],
) -> dict[str, object]:
    role_counter: dict[str, int] = defaultdict(int)
    for row in node_rows:
        roles = json.loads(row["roles_json"])
        for role in roles:
            role_counter[role] += 1

    top_roles = sorted(role_counter.items(), key=lambda item: (-item[1], item[0]))
    sample_nodes = [
        {
            "entity_id": row["entity_id"],
            "canonical_name": row["canonical_name"],
            "roles": json.loads(row["roles_json"]),
        }
        for row in node_rows[:20]
    ]
    sample_edges = edges[:20]

    return {
        "node_count": len(node_rows),
        "edge_count": len(edges),
        "top_roles": [
            {"role": role, "count": count}
            for role, count in top_roles[:20]
        ],
        "sample_nodes": sample_nodes,
        "sample_edges": sample_edges,
    }


def generate_markdown_summary(summary: dict[str, object]) -> str:
    lines = [
        "# Phase 3 Subgraph Extraction",
        "",
        f"- Node count: `{summary['node_count']}`",
        f"- Edge count: `{summary['edge_count']}`",
        "",
        "## Top Roles",
        "",
    ]
    for item in summary["top_roles"]:
        lines.append(f"- `{item['role']}`: `{item['count']}`")

    lines.extend(["", "## Sample Nodes", ""])
    for item in summary["sample_nodes"][:10]:
        lines.append(
            f"- `{item['entity_id']}` {item['canonical_name']} roles={','.join(item['roles'])}"
        )

    lines.extend(["", "## Sample Edges", ""])
    for item in summary["sample_edges"][:10]:
        lines.append(
            f"- `{item['source_id']}` -[{item['pid']}:{item['relation_label']}]-> `{item['target_id']}`"
        )

    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract a Neo4j-ready Turkiye cinema subgraph from Phase 2 artifacts.",
    )
    parser.add_argument(
        "--phase2-summary",
        type=Path,
        default=PHASE2_SUMMARY_PATH,
        help="Path to the Phase 2 summary JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where Neo4j-ready Phase 3 files will be written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    phase2_summary = load_phase2_summary(args.phase2_summary)
    entity_ids, role_map = collect_entity_ids(phase2_summary)
    relation_labels = load_relation_labels(RELATION_ALIAS_PATH)
    labels, aliases, descriptions = collect_entity_metadata(
        ENTITY_ALIAS_PATH,
        TEXT_PATH,
        entity_ids,
    )
    edges = collect_subgraph_edges(entity_ids, relation_labels)

    import_dir = args.output_dir / "neo4j_import"
    node_rows = write_nodes_csv(
        import_dir / "entities.csv",
        entity_ids=entity_ids,
        role_map=role_map,
        labels=labels,
        aliases=aliases,
        descriptions=descriptions,
    )
    write_edges_csv(import_dir / "relationships.csv", edges)

    phase3_summary = build_phase3_summary(node_rows=node_rows, edges=edges)
    write_json(args.output_dir / "phase3_subgraph_summary.json", phase3_summary)
    write_text(args.output_dir / "phase3_subgraph_summary.md", generate_markdown_summary(phase3_summary))
    write_text(args.output_dir / "cypher_library.cypher", build_cypher_library(phase2_summary))

    print(
        json.dumps(
            {
                "node_count": phase3_summary["node_count"],
                "edge_count": phase3_summary["edge_count"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
