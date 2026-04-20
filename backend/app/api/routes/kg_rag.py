from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.kg_rag import KGInfusedRAGRunner

router = APIRouter(prefix="/kg-rag", tags=["kg-rag"])


class RunKGQuestionRequest(BaseModel):
    question_id: str
    top_k: int = Field(default=6, ge=1, le=12)
    max_rounds: int | None = Field(default=None, ge=1, le=6)
    skip_existing: bool = True


class RunKGDatasetRequest(BaseModel):
    question_ids: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
    top_k: int = Field(default=6, ge=1, le=12)
    max_rounds: int | None = Field(default=None, ge=1, le=6)
    skip_existing: bool = True


def get_runner(settings: Settings = Depends(get_settings)) -> KGInfusedRAGRunner:
    return KGInfusedRAGRunner(settings)


@router.get("/questions")
def list_kg_questions(
    limit: int | None = None,
    runner: KGInfusedRAGRunner = Depends(get_runner),
) -> dict[str, Any]:
    return {"questions": runner.list_questions(limit=limit)}


@router.post("/run-question")
def run_kg_question(
    request: RunKGQuestionRequest,
    runner: KGInfusedRAGRunner = Depends(get_runner),
) -> dict[str, Any]:
    return runner.run_question(
        question_id=request.question_id,
        top_k=request.top_k,
        max_rounds=request.max_rounds,
        skip_existing=request.skip_existing,
    )


@router.post("/run-dataset")
def run_kg_dataset(
    request: RunKGDatasetRequest,
    runner: KGInfusedRAGRunner = Depends(get_runner),
) -> dict[str, Any]:
    return runner.run_dataset(
        question_ids=request.question_ids,
        limit=request.limit,
        top_k=request.top_k,
        max_rounds=request.max_rounds,
        skip_existing=request.skip_existing,
    )


@router.get("/results")
def get_kg_results(
    question_id: str | None = None,
    runner: KGInfusedRAGRunner = Depends(get_runner),
) -> dict[str, Any]:
    return {"results": runner.get_results(question_id=question_id)}
