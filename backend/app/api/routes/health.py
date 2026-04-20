from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.config import Settings, get_settings
from app.providers import get_provider_registry

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    registry = get_provider_registry(settings)
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "domain": settings.project_domain,
        "providers": registry.snapshot(),
    }


@router.get("/health/readiness")
def readiness(
    probe_neo4j: bool = Query(default=False),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    registry = get_provider_registry(settings)
    providers = registry.snapshot(probe_neo4j=probe_neo4j)
    ready = providers["groq"]["configured"] and providers["neo4j"]["configured"]
    return {
        "status": "ready" if ready else "not_ready",
        "checks": providers,
    }
