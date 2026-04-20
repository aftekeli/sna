from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.config import Settings, get_settings
from app.providers import get_provider_registry

router = APIRouter(prefix="/ops/groq", tags=["groq-ops"])


@router.get("/quota")
def get_groq_quota(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    groq = get_provider_registry(settings).groq
    snapshot = groq.quota.load_snapshot()
    pause_state = groq.quota.load_pause_state()
    runtime_status = groq.quota.runtime_status()
    return {
        "configured": groq.configured,
        "mode": settings.groq_mode,
        "snapshot": snapshot.to_dict() if snapshot else None,
        "snapshot_stale": groq.quota.is_snapshot_stale(snapshot),
        "pause_state": pause_state.to_dict() if pause_state else None,
        "paused_for_rest_of_day": groq.quota.is_pause_active(pause_state),
        "cooldown_active": runtime_status["cooldown_active"],
        "cooldown_until": runtime_status["cooldown_until"],
        "consecutive_429_count": runtime_status["consecutive_429_count"],
        "daily_cooldown_count": runtime_status["daily_cooldown_count"],
        "request_pacing_rpm": runtime_status["request_pacing_rpm"],
        "daily_stop_threshold_requests": runtime_status["daily_stop_threshold_requests"],
        "runtime_state": runtime_status["state"],
        "runtime_dir": str(settings.groq_runtime_dir),
    }


@router.post("/quota/probe")
def probe_groq_quota(
    force: bool = Query(default=False),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    groq = get_provider_registry(settings).groq
    snapshot = groq.get_quota_snapshot(force_probe=force)
    pause_state = groq.quota.load_pause_state()
    runtime_status = groq.quota.runtime_status()
    return {
        "configured": groq.configured,
        "snapshot": snapshot.to_dict() if snapshot else None,
        "pause_state": pause_state.to_dict() if pause_state else None,
        "paused_for_rest_of_day": groq.quota.is_pause_active(pause_state),
        "cooldown_active": runtime_status["cooldown_active"],
        "cooldown_until": runtime_status["cooldown_until"],
        "consecutive_429_count": runtime_status["consecutive_429_count"],
        "daily_cooldown_count": runtime_status["daily_cooldown_count"],
        "request_pacing_rpm": runtime_status["request_pacing_rpm"],
        "daily_stop_threshold_requests": runtime_status["daily_stop_threshold_requests"],
        "runtime_state": runtime_status["state"],
    }


@router.get("/pause-state")
def get_groq_pause_state(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    groq = get_provider_registry(settings).groq
    pause_state = groq.quota.load_pause_state()
    runtime_status = groq.quota.runtime_status()
    return {
        "configured": groq.configured,
        "paused_for_rest_of_day": groq.quota.is_pause_active(pause_state),
        "pause_state": pause_state.to_dict() if pause_state else None,
        "cooldown_active": runtime_status["cooldown_active"],
        "cooldown_until": runtime_status["cooldown_until"],
        "consecutive_429_count": runtime_status["consecutive_429_count"],
        "daily_cooldown_count": runtime_status["daily_cooldown_count"],
        "request_pacing_rpm": runtime_status["request_pacing_rpm"],
        "daily_stop_threshold_requests": runtime_status["daily_stop_threshold_requests"],
        "runtime_state": runtime_status["state"],
        "resume_timezone": settings.groq_usage_timezone,
    }
