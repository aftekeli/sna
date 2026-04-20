from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import Settings, get_settings
from app.providers.groq_provider import GroqProvider
from app.providers.neo4j_provider import Neo4jProvider

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

DEFAULT_SAMPLE_QUESTION_ID = "qa_104db2fbbec9"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Missing artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_text(path: Path) -> str:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Missing artifact: {path}")
    return path.read_text(encoding="utf-8")


def _phase2_summary_path(settings: Settings) -> Path:
    return settings.artifacts_dir / "phase-2" / "turkiye_cinema_summary.json"


def _phase3_summary_path(settings: Settings) -> Path:
    return settings.phase3_dir / "phase3_subgraph_summary.json"


def _phase3_cypher_path(settings: Settings) -> Path:
    return settings.phase3_dir / "cypher_library.cypher"


def _phase3_verification_path(settings: Settings) -> Path:
    return settings.phase3_dir / "neo4j_verification.json"


def _phase4_summary_path(settings: Settings) -> Path:
    return settings.phase4_dir / "dataset_summary.json"


def _phase7_coverage_path(settings: Settings) -> Path:
    return settings.phase7_dir / "latest" / "coverage.json"


def _phase7_metrics_path(settings: Settings) -> Path:
    return settings.phase7_dir / "latest" / "metrics.json"


def _phase7_case_studies_path(settings: Settings) -> Path:
    return settings.phase7_dir / "latest" / "case_studies.json"


def _phase5_result_path(settings: Settings, method: str, question_id: str) -> Path:
    return settings.phase5_dir / "latest" / method / f"{question_id}.json"


def _phase6_result_path(settings: Settings, question_id: str) -> Path:
    return settings.phase6_dir / "latest" / f"{question_id}.json"


def _safe_method_summary(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    by_method = metrics.get("by_method", {})
    summaries: list[dict[str, Any]] = []
    for method_name, payload in by_method.items():
        summary = payload.get("summary", {})
        summaries.append(
            {
                "method": method_name,
                "coverage": summary.get("coverage"),
                "accuracy": summary.get("accuracy"),
                "exact_match": summary.get("exact_match"),
                "f1": summary.get("f1"),
                "retrieval_recall": summary.get("retrieval_recall"),
            }
        )
    return summaries


def _enrich_templates(
    templates: list[dict[str, Any]], verification: dict[str, Any]
) -> list[dict[str, Any]]:
    def _vkey(title: str) -> str | None:
        t = title.lower()
        if "1-hop" in t or "root" in t or "türkiye root" in t:
            return "one_hop_films"
        if ("director" in t or "birth" in t) and ("3-hop" in t or "three" in t or "country" in t):
            return "three_hop_director_birth_place_country"
        if "director" in t and ("birth" in t or "2-hop" in t or "two" in t):
            return "two_hop_director_birth_place"
        return None

    enriched = []
    for tmpl in templates:
        key = _vkey(tmpl.get("title", ""))
        block = verification.get(key, {}) if key else {}
        enriched.append(
            {
                **tmpl,
                "row_count": block.get("row_count", 0),
                "sample_rows": block.get("sample_rows", []),
            }
        )
    return enriched


def _parse_cypher_library(raw_text: str) -> list[dict[str, Any]]:
    blocks = [block.strip() for block in raw_text.split(";") if block.strip()]
    templates: list[dict[str, Any]] = []
    current_title = "Cypher Query"
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        description = ""
        start = 0
        if lines and lines[0].startswith("//"):
            current_title = lines[0].replace("//", "", 1).strip()
            start = 1
            if len(lines) > 1 and lines[1].startswith("//"):
                description = lines[1].replace("//", "", 1).strip()
                start = 2
        statement = "\n".join(lines[start:]).strip()
        templates.append({"title": current_title, "description": description, "statement": statement})
    return templates


@router.get("/overview")
def get_dashboard_overview(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    phase2 = _load_json(_phase2_summary_path(settings))
    phase3 = _load_json(_phase3_summary_path(settings))
    phase4 = _load_json(_phase4_summary_path(settings))
    phase7_coverage = _load_json(_phase7_coverage_path(settings))
    phase7_metrics = _load_json(_phase7_metrics_path(settings))
    case_studies = _load_json(_phase7_case_studies_path(settings))
    groq_snapshot = GroqProvider(settings).snapshot()

    return {
        "generated_at": phase7_metrics.get("created_at"),
        "domain": settings.project_domain,
        "graph": {
            "turkey_root": phase2.get("turkey_root"),
            "cinema_stats": phase2.get("cinema_stats"),
            "relation_frequency": phase2.get("relation_frequency", []),
            "path_summary": phase2.get("path_summary", []),
            "seed_rankings": phase2.get("seed_rankings", {}),
            "node_count": phase3.get("node_count"),
            "edge_count": phase3.get("edge_count"),
            "top_roles": phase3.get("top_roles", []),
            "sample_nodes": phase3.get("sample_nodes", [])[:12],
        },
        "dataset": {
            "question_count": phase4.get("question_count"),
            "distribution": phase4.get("distribution", {}),
            "validation": phase4.get("validation", {}),
        },
        "evaluation": {
            "coverage": phase7_coverage,
            "method_summaries": _safe_method_summary(phase7_metrics),
            "case_study_counts": {
                "success_cases": len(case_studies.get("success_cases", [])),
                "failure_cases": len(case_studies.get("failure_cases", [])),
            },
        },
        "groq": groq_snapshot,
    }


@router.get("/cypher-library")
def get_cypher_library(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    verification = _load_json(_phase3_verification_path(settings))
    raw_library = _load_text(_phase3_cypher_path(settings))
    templates = _parse_cypher_library(raw_library)
    verification_dict = verification.get("verification", {})
    enriched = _enrich_templates(templates, verification_dict)

    return {
        "generated_at": verification.get("generated_at"),
        "library_text": raw_library,
        "templates": enriched,
        "verification": verification_dict,
        "entity_count": verification.get("entity_count"),
        "relationship_count": verification.get("relationship_count"),
    }


class RunCypherBody(dict):
    pass


@router.post("/run-cypher")
def run_cypher(body: dict[str, Any], settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    import time

    query_index: int = int(body.get("query_index", 0))
    neo4j = Neo4jProvider(settings)
    if not neo4j.configured:
        return {"rows": [], "row_count": 0, "elapsed_ms": 0, "error": "Neo4j not configured"}

    try:
        raw_library = _load_text(_phase3_cypher_path(settings))
        templates = _parse_cypher_library(raw_library)
        if query_index < 0 or query_index >= len(templates):
            return {"rows": [], "row_count": 0, "elapsed_ms": 0, "error": f"Invalid query index {query_index}"}
        statement = templates[query_index]["statement"]
        import re as _re
        has_limit = bool(_re.search(r"\bLIMIT\b", statement, _re.IGNORECASE))
        query = statement if has_limit else statement + " LIMIT 20"
        t0 = time.monotonic()
        rows = neo4j.run_query(query)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {"rows": rows, "row_count": len(rows), "elapsed_ms": elapsed_ms, "error": None}
    except Exception as exc:
        return {"rows": [], "row_count": 0, "elapsed_ms": 0, "error": str(exc)}


@router.get("/graph-data")
def get_graph_data(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    import csv as _csv
    import json as _json

    neo4j = Neo4jProvider(settings)
    if neo4j.configured:
        try:
            node_rows = neo4j.run_query(
                "MATCH (n:Entity) RETURN n.entity_id AS id, n.canonical_name AS label, n.roles AS roles"
            )
            edge_rows = neo4j.run_query(
                "MATCH (a:Entity)-[r:REL]->(b:Entity) RETURN a.entity_id AS source, b.entity_id AS target, r.label AS relation"
            )
            return {
                "nodes": [{"id": r["id"], "label": r["label"], "roles": list(r["roles"] or [])} for r in node_rows],
                "edges": [{"source": r["source"], "target": r["target"], "relation": r["relation"]} for r in edge_rows],
                "source": "neo4j",
            }
        except Exception:
            pass

    entities_path = settings.phase3_entities_path
    rels_path = settings.phase3_relationships_path
    if entities_path.exists() and rels_path.exists():
        nodes: list[dict[str, Any]] = []
        with open(entities_path, encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                roles = _json.loads(row.get("roles_json", "[]"))
                nodes.append({"id": row["entity_id"], "label": row["canonical_name"], "roles": roles})
        edges: list[dict[str, Any]] = []
        with open(rels_path, encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                edges.append({"source": row["source_id"], "target": row["target_id"], "relation": row["relation_label"]})
        return {"nodes": nodes, "edges": edges, "source": "csv"}

    return {"nodes": [], "edges": [], "source": "unavailable"}


@router.get("/entity-distribution")
def get_entity_distribution(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    phase3 = _load_json_optional(_phase3_summary_path(settings))
    hardcoded = [
        {"role": "film", "label": "Film", "count": 207, "tone": "cyan"},
        {"role": "cast_member", "label": "Cast Member", "count": 193, "tone": "amber"},
        {"role": "birth_place", "label": "Birth Place", "count": 109, "tone": "green"},
        {"role": "director", "label": "Director", "count": 47, "tone": "pink"},
        {"role": "country", "label": "Country", "count": 25, "tone": "rose"},
        {"role": "award", "label": "Award", "count": 13, "tone": "blue"},
    ]
    if not phase3:
        return {"entity_types": hardcoded}

    role_map = {"film": "Film", "cast_member": "Cast Member", "birth_place": "Birth Place",
                "director": "Director", "country": "Country", "award": "Award"}
    tone_map = {"film": "cyan", "cast_member": "amber", "birth_place": "green",
                "director": "pink", "country": "rose", "award": "blue"}
    keep = set(role_map.keys())
    entity_types = [
        {"role": r["role"], "label": role_map[r["role"]], "count": r["count"], "tone": tone_map[r["role"]]}
        for r in phase3.get("top_roles", []) if r["role"] in keep
    ]
    return {"entity_types": entity_types or hardcoded}


@router.get("/question-metrics")
def get_question_metrics(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    metrics = _load_json_optional(_phase7_metrics_path(settings))
    if not metrics:
        return {"questions": []}

    bm = metrics.get("by_method", {})
    qids = metrics.get("question_ids", [])
    lookups: dict[str, dict[str, int]] = {}
    for method_key, method_label in [
        ("no_retrieval", "no_retrieval"),
        ("vanilla_rag", "vanilla_rag"),
        ("vanilla_qe", "vanilla_qe"),
        ("kg_infused_rag", "kg_rag"),
    ]:
        payload = bm.get(method_key, {})
        lookups[method_label] = {
            q["question_id"]: (1 if q["metrics"].get("accuracy") else 0)
            for q in payload.get("questions", [])
        }

    return {
        "questions": [
            {
                "id": qid,
                "no_retrieval": lookups["no_retrieval"].get(qid, 0),
                "vanilla_rag": lookups["vanilla_rag"].get(qid, 0),
                "vanilla_qe": lookups["vanilla_qe"].get(qid, 0),
                "kg_rag": lookups["kg_rag"].get(qid, 0),
            }
            for qid in qids
        ]
    }


@router.get("/question-trace")
def get_question_trace(
    question_id: str = Query(default=DEFAULT_SAMPLE_QUESTION_ID),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    kg_trace = _load_json(_phase6_result_path(settings, question_id))
    no_retrieval = _load_json_optional(_phase5_result_path(settings, "no_retrieval", question_id))
    vanilla_rag = _load_json_optional(_phase5_result_path(settings, "vanilla_rag", question_id))
    vanilla_qe = _load_json_optional(_phase5_result_path(settings, "vanilla_qe", question_id))
    case_studies = _load_json(_phase7_case_studies_path(settings))

    return {
        "question_id": question_id,
        "question": kg_trace.get("question"),
        "gold_answer": kg_trace.get("gold_answer"),
        "kg_rag": kg_trace,
        "baselines": {
            "no_retrieval": no_retrieval,
            "vanilla_rag": vanilla_rag,
            "vanilla_qe": vanilla_qe,
        },
        "case_studies": {
            "success_cases": [
                case for case in case_studies.get("success_cases", []) if case.get("question_id") == question_id
            ],
            "failure_cases": [
                case for case in case_studies.get("failure_cases", []) if case.get("question_id") == question_id
            ],
        },
    }
