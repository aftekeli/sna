# Multi-Hop Question Answering with KG-Infused RAG over a Turkiye Cinema Knowledge Graph

## Course Information

| Field | Value |
| --- | --- |
| Course | CSE474 Social Network Analysis |
| Instructor | Assoc. Prof. Alper Ozcan |
| Students | 20210808067 - Munevver Nur Topluyurek<br>20220808617 - Ahmet Faruk Tekeli |

## Overview

This project presents a Knowledge Graph-Infused Retrieval-Augmented Generation (KG-Infused RAG) system for multi-hop question answering in the Turkiye cinema domain.

The system combines a curated cinema-focused subgraph, baseline retrieval pipelines, and a graph-guided reasoning workflow to answer multi-hop questions with traceable evidence. In addition to the backend QA pipeline, the repository includes an interactive dashboard and a live chat interface for exploring graph structure, Cypher queries, evaluation outputs, and explainable evidence trails.

## Key Features

- Knowledge graph construction over the Turkiye cinema domain
- Multi-hop question answering with KG-guided retrieval and reasoning
- Baseline comparison pipelines for retrieval and answer generation
- FastAPI backend exposing chat, dashboard, evaluation, and graph endpoints
- Next.js frontend with dashboard, knowledge graph, Cypher, GNN, XAI, and live chat views
- Generated experiment artifacts used directly by the application

## System Components

### Backend

The backend is implemented with FastAPI and organizes the QA pipeline into modular components for providers, KG-RAG execution, baseline methods, evaluation, and chat orchestration.

Main responsibilities:
- provider integration for Groq, Neo4j, and local fallback services
- KG-RAG execution and answer tracing
- baseline retrieval and generation workflows
- evaluation metric loading and comparison endpoints
- session-based live chat support

### Frontend

The frontend is implemented with Next.js and provides an application-style interface for inspecting the project outputs and interacting with the QA system.

Main views:
- Dashboard
- Knowledge Graph
- Cypher Queries
- GNN
- XAI Evidence
- Live Chat

### Artifacts

The `artifacts/` directory stores generated outputs used by the interface and backend views, including graph summaries, dataset metadata, baseline retrieval outputs, KG-RAG traces, and evaluation results.

## Data Foundation

This project was developed using a locally downloaded copy of **Wikidata5M-KG** provided by **Alphonse7** on Hugging Face. The dataset package supplies the triplets, entity aliases, relation aliases, and text descriptions used throughout the pipeline to:

- extracting a Turkiye-centered cinema subgraph
- building Neo4j-ready entity and relationship exports
- generating the verified multi-hop QA benchmark used for evaluation

During development, this was the only external dataset package used from the project root for graph construction and dataset generation. The downstream outputs produced from that source are stored under `artifacts/`.

Primary data package:
- [Alphonse7/Wikidata5M-KG (Hugging Face)](https://huggingface.co/datasets/Alphonse7/Wikidata5M-KG)

## Technology Stack

| Layer | Technologies |
| --- | --- |
| Backend | FastAPI, Uvicorn, Pydantic, HTTPX |
| Graph / Data | Neo4j Aura, CSV/JSON/SQLite artifacts |
| LLM Provider | Groq |
| Frontend | Next.js, React, TypeScript |
| Visualization | React-based custom UI and graph rendering components |

## Repository Structure

```text
.
|-- artifacts/
|   |-- phase-2/
|   |-- phase-3/
|   |-- phase-4/
|   |-- phase-5/
|   |-- phase-6/
|   `-- phase-7/
|-- backend/
|   |-- app/
|   |   |-- api/
|   |   |   `-- routes/
|   |   |-- baselines/
|   |   |-- chat/
|   |   |-- core/
|   |   |-- evaluation/
|   |   |-- kg_rag/
|   |   `-- providers/
|   |-- requirements.txt
|   `-- requirements-dev.txt
|-- docs/
|   `-- .gitkeep
|-- frontend/
|   |-- app/
|   |-- components/
|   |-- lib/
|   |-- package.json
|   `-- tsconfig.json
|-- scripts/
|   |-- explore_turkiye_cinema.py
|   |-- extract_turkiye_cinema_subgraph.py
|   |-- generate_verified_multihop_qa_dataset.py
|   `-- load_turkiye_cinema_subgraph_to_neo4j.py
|-- .env.example
|-- start_backend.bat
|-- start_frontend.bat
`-- dev_frontend.bat
```

## Setup

### 1. Environment Variables

Copy `.env.example` to `.env` and provide the required credentials.

Expected variables:
- `GROQ_API_KEY`
- `GROQ_MODEL` (optional override)
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE`

### 2. Backend Installation

Install backend dependencies from the project root:

```bash
python -m pip install -r backend/requirements.txt
```

Start the backend:

```bash
start_backend.bat
```

Backend default address:

```text
http://127.0.0.1:8000
```

### 3. Frontend Installation

Install frontend dependencies from the `frontend/` directory:

```bash
npm install
```

Build the frontend:

```bash
npm run build
```

Start the production frontend:

```bash
start_frontend.bat
```

For development mode:

```bash
dev_frontend.bat
```

Frontend default address:

```text
http://127.0.0.1:3000
```

## Documentation

Project documentation files can be placed under the `docs/` directory.

## Project Scope

This repository focuses on:
- graph-centered multi-hop QA in a domain-specific knowledge graph
- comparison between retrieval strategies and graph-guided reasoning
- explainability through structured traces, Cypher inspection, and evidence visualization
- an interactive interface for presenting the full project workflow
