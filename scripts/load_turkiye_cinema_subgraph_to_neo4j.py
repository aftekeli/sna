from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from neo4j import GraphDatabase

from explore_turkiye_cinema import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import get_settings

DEFAULT_IMPORT_DIR = REPO_ROOT / "artifacts" / "phase-3" / "neo4j_import"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "artifacts" / "phase-3" / "neo4j_verification.json"


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if path.name == "entities.csv":
        for row in rows:
            row["aliases"] = json.loads(row.pop("aliases_json"))
            row["domains"] = json.loads(row.pop("domains_json"))
            row["roles"] = json.loads(row.pop("roles_json"))
    return rows


def batched(rows: list[dict[str, str]], batch_size: int) -> list[list[dict[str, str]]]:
    return [rows[index : index + batch_size] for index in range(0, len(rows), batch_size)]


def create_indexes(session) -> None:
    statements = [
        "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE",
        "CREATE INDEX entity_domain_idx IF NOT EXISTS FOR (e:Entity) ON (e.is_turkiye_related)",
        "CREATE FULLTEXT INDEX entity_text_search IF NOT EXISTS FOR (e:Entity) ON EACH [e.canonical_name, e.aliases_text, e.description]",
    ]
    for statement in statements:
        session.run(statement).consume()


def load_nodes(session, rows: list[dict[str, str]], batch_size: int) -> None:
    query = """
    UNWIND $rows AS row
    MERGE (e:Entity {entity_id: row.entity_id})
    SET e.canonical_name = row.canonical_name,
        e.description = row.description,
        e.aliases = row.aliases,
        e.aliases_text = row.aliases_text,
        e.domains = row.domains,
        e.roles = row.roles,
        e.is_turkiye_related = row.is_turkiye_related = 'true'
    """
    for batch in batched(rows, batch_size):
        session.run(query, rows=batch).consume()


def load_relationships(session, rows: list[dict[str, str]], batch_size: int) -> None:
    query = """
    UNWIND $rows AS row
    MATCH (source:Entity {entity_id: row.source_id})
    MATCH (target:Entity {entity_id: row.target_id})
    MERGE (source)-[r:REL {pid: row.pid, source_id: row.source_id, target_id: row.target_id}]->(target)
    SET r.label = row.relation_label,
        r.domain = 'turkiye_cinema'
    """
    for batch in batched(rows, batch_size):
        session.run(query, rows=batch).consume()


def verify_queries(session) -> dict[str, object]:
    queries = {
        "one_hop_films": """
            MATCH (film:Entity)-[:REL {pid: 'P495'}]->(country:Entity {entity_id: 'Q43'})
            RETURN film.canonical_name AS film, country.canonical_name AS country
            LIMIT 5
        """,
        "two_hop_director_birth_place": """
            MATCH (film:Entity)-[:REL {pid: 'P57'}]->(director:Entity)-[:REL {pid: 'P19'}]->(birth_place:Entity)
            RETURN film.canonical_name AS film, director.canonical_name AS director, birth_place.canonical_name AS birth_place
            LIMIT 5
        """,
        "three_hop_director_birth_place_country": """
            MATCH (film:Entity)-[:REL {pid: 'P57'}]->(director:Entity)-[:REL {pid: 'P19'}]->(birth_place:Entity)-[:REL {pid: 'P17'}]->(country:Entity)
            RETURN film.canonical_name AS film, director.canonical_name AS director, birth_place.canonical_name AS birth_place, country.canonical_name AS country
            LIMIT 5
        """,
    }

    results: dict[str, object] = {}
    for name, query in queries.items():
        rows = session.run(query).data()
        results[name] = {
            "row_count": len(rows),
            "sample_rows": rows,
        }
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load the extracted Turkiye cinema subgraph into Neo4j Aura and verify sample queries.",
    )
    parser.add_argument(
        "--import-dir",
        type=Path,
        default=DEFAULT_IMPORT_DIR,
        help="Directory containing entities.csv and relationships.csv.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size used for Neo4j writes.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Where to write the verification summary JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    if not settings.neo4j_uri or not settings.neo4j_username or not settings.neo4j_password:
        raise RuntimeError("Neo4j credentials are missing from the environment.")

    entities = load_csv_rows(args.import_dir / "entities.csv")
    relationships = load_csv_rows(args.import_dir / "relationships.csv")

    with GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    ) as driver:
        driver.verify_connectivity()
        with driver.session(database=settings.neo4j_database) as session:
            create_indexes(session)
            load_nodes(session, entities, args.batch_size)
            load_relationships(session, relationships, args.batch_size)
            verification = verify_queries(session)

    payload = {
        "entity_count": len(entities),
        "relationship_count": len(relationships),
        "verification": verification,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
