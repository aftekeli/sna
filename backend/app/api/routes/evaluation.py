from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.evaluation import EVALUATION_METHODS, Phase7EvaluationRunner

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


class RunEvaluationRequest(BaseModel):
    methods: list[str] | None = None
    question_ids: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
    top_k: int = Field(default=6, ge=1, le=12)
    max_rounds: int | None = Field(default=None, ge=1, le=6)
    skip_existing: bool = True


class ComputeMetricsRequest(BaseModel):
    methods: list[str] | None = None
    question_ids: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=50)


class ExportCaseStudiesRequest(BaseModel):
    methods: list[str] | None = None
    question_ids: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
    success_limit: int = Field(default=5, ge=1, le=20)
    failure_limit: int = Field(default=5, ge=1, le=20)


def get_runner(settings: Settings = Depends(get_settings)) -> Phase7EvaluationRunner:
    return Phase7EvaluationRunner(settings)


@router.get("/questions")
def list_evaluation_questions(
    limit: int | None = None,
    runner: Phase7EvaluationRunner = Depends(get_runner),
) -> dict[str, Any]:
    return {
        "methods": list(EVALUATION_METHODS),
        "questions": runner.list_questions(limit=limit),
    }


@router.get("/coverage")
def get_evaluation_coverage(
    methods: list[str] | None = None,
    question_ids: list[str] | None = None,
    limit: int | None = None,
    runner: Phase7EvaluationRunner = Depends(get_runner),
) -> dict[str, Any]:
    return runner.coverage(methods=methods, question_ids=question_ids, limit=limit)


@router.post("/run")
def run_evaluation(
    request: RunEvaluationRequest,
    runner: Phase7EvaluationRunner = Depends(get_runner),
) -> dict[str, Any]:
    return runner.run_experiments(
        methods=request.methods,
        question_ids=request.question_ids,
        limit=request.limit,
        top_k=request.top_k,
        max_rounds=request.max_rounds,
        skip_existing=request.skip_existing,
    )


@router.post("/metrics")
def compute_evaluation_metrics(
    request: ComputeMetricsRequest,
    runner: Phase7EvaluationRunner = Depends(get_runner),
) -> dict[str, Any]:
    return runner.compute_metrics(
        methods=request.methods,
        question_ids=request.question_ids,
        limit=request.limit,
    )


@router.post("/case-studies")
def export_case_studies(
    request: ExportCaseStudiesRequest,
    runner: Phase7EvaluationRunner = Depends(get_runner),
) -> dict[str, Any]:
    return runner.export_case_studies(
        methods=request.methods,
        question_ids=request.question_ids,
        limit=request.limit,
        success_limit=request.success_limit,
        failure_limit=request.failure_limit,
    )


@router.get("/latest")
def get_latest_evaluation_results(
    runner: Phase7EvaluationRunner = Depends(get_runner),
) -> dict[str, Any]:
    return runner.latest_results()
