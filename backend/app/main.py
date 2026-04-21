from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chat import router as chat_router
from app.api.routes.baselines import router as baselines_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.evaluation import router as evaluation_router
from app.api.routes.groq_ops import router as groq_ops_router
from app.api.routes.health import router as health_router
from app.api.routes.kg_rag import router as kg_rag_router
from app.core.config import get_settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.app_debug)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        debug=settings.app_debug,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(baselines_router)
    app.include_router(chat_router)
    app.include_router(dashboard_router)
    app.include_router(evaluation_router)
    app.include_router(health_router)
    app.include_router(groq_ops_router)
    app.include_router(kg_rag_router)
    return app


app = create_app()
