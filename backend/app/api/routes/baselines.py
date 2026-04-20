from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.baselines import Phase5BaselineRunner, SUPPORTED_BASELINES
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/baselines", tags=["baselines"])


class BuildIndexRequest(BaseModel):
    force_rebuild: bool = False


class RunQuestionRequest(BaseModel):
    method: str = Field(pattern="^(no_retrieval|vanilla_rag|vanilla_qe)$")
    question_id: str
    top_k: int = Field(default=6, ge=1, le=12)
    skip_existing: bool = True


class RunDatasetRequest(BaseModel):
    methods: list[str] | None = None
    question_ids: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
    top_k: int = Field(default=6, ge=1, le=12)
    skip_existing: bool = True


def get_runner(settings: Settings = Depends(get_settings)) -> Phase5BaselineRunner:
    return Phase5BaselineRunner(settings)


@router.get("/questions")
def list_baseline_questions(
    limit: int | None = None,
    runner: Phase5BaselineRunner = Depends(get_runner),
) -> dict[str, Any]:
    return {
        "supported_methods": list(SUPPORTED_BASELINES),
        "questions": runner.list_questions(limit=limit),
    }


@router.get("/index/status")
def get_index_status(runner: Phase5BaselineRunner = Depends(get_runner)) -> dict[str, Any]:
    return runner.corpus_status()


@router.post("/index/build")
def build_index(
    request: BuildIndexRequest,
    runner: Phase5BaselineRunner = Depends(get_runner),
) -> dict[str, Any]:
    return runner.build_corpus_index(force_rebuild=request.force_rebuild)


@router.post("/run-question")
def run_baseline_question(
    request: RunQuestionRequest,
    runner: Phase5BaselineRunner = Depends(get_runner),
) -> dict[str, Any]:
    return runner.run_question(
        method=request.method,
        question_id=request.question_id,
        top_k=request.top_k,
        skip_existing=request.skip_existing,
    )


@router.post("/run-dataset")
def run_baseline_dataset(
    request: RunDatasetRequest,
    runner: Phase5BaselineRunner = Depends(get_runner),
) -> dict[str, Any]:
    return runner.run_dataset(
        methods=request.methods,
        question_ids=request.question_ids,
        limit=request.limit,
        top_k=request.top_k,
        skip_existing=request.skip_existing,
    )


@router.get("/results")
def get_baseline_results(
    method: str | None = None,
    question_id: str | None = None,
    runner: Phase5BaselineRunner = Depends(get_runner),
) -> dict[str, Any]:
    return {
        "results": runner.get_results(method=method, question_id=question_id),
    }
