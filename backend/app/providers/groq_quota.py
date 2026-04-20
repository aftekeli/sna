from __future__ import annotations

import math
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.artifacts import ArtifactStore, utc_now_iso
from app.core.config import Settings


def _parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _parse_seconds(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    text = value.strip().lower()
    if text.endswith("ms"):
        return float(text[:-2]) / 1000.0
    compound_match = re.fullmatch(
        r"(?:(?P<hours>\d+(?:\.\d+)?)h)?(?:(?P<minutes>\d+(?:\.\d+)?)m)?(?:(?P<seconds>\d+(?:\.\d+)?)s?)?",
        text,
    )
    if compound_match and any(compound_match.groupdict().values()):
        hours = float(compound_match.group("hours") or "0")
        minutes = float(compound_match.group("minutes") or "0")
        seconds = float(compound_match.group("seconds") or "0")
        return (hours * 3600) + (minutes * 60) + seconds
    if text.endswith("s") and "m" not in text[:-1]:
        return float(text[:-1])
    if "m" in text and text.endswith("s"):
        minutes_text, seconds_text = text[:-1].split("m", 1)
        minutes = float(minutes_text or "0")
        seconds = float(seconds_text or "0")
        return (minutes * 60) + seconds
    try:
        return float(text)
    except ValueError:
        return None


@dataclass(slots=True)
class QuotaSnapshot:
    captured_at: str
    model: str
    source: str
    limit_requests: int | None = None
    limit_tokens: int | None = None
    remaining_requests: int | None = None
    remaining_tokens: int | None = None
    reset_requests_seconds: float | None = None
    reset_tokens_seconds: float | None = None
    retry_after_seconds: float | None = None
    service_tier: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_headers(
        cls,
        headers: dict[str, str],
        *,
        model: str,
        source: str,
        service_tier: str | None = None,
    ) -> "QuotaSnapshot":
        normalized_headers = {key.lower(): value for key, value in headers.items()}
        return cls(
            captured_at=utc_now_iso(),
            model=model,
            source=source,
            limit_requests=_parse_int(normalized_headers.get("x-ratelimit-limit-requests")),
            limit_tokens=_parse_int(normalized_headers.get("x-ratelimit-limit-tokens")),
            remaining_requests=_parse_int(normalized_headers.get("x-ratelimit-remaining-requests")),
            remaining_tokens=_parse_int(normalized_headers.get("x-ratelimit-remaining-tokens")),
            reset_requests_seconds=_parse_seconds(normalized_headers.get("x-ratelimit-reset-requests")),
            reset_tokens_seconds=_parse_seconds(normalized_headers.get("x-ratelimit-reset-tokens")),
            retry_after_seconds=_parse_seconds(normalized_headers.get("retry-after")),
            service_tier=service_tier,
            headers=normalized_headers,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QuotaSnapshot":
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def age_seconds(self) -> float:
        captured_at = datetime.fromisoformat(self.captured_at)
        return max((datetime.now(UTC) - captured_at).total_seconds(), 0.0)


@dataclass(slots=True)
class PauseState:
    active: bool
    reason: str
    triggered_at: str
    action_name: str
    resume_on_date: str
    last_seen_headers: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PauseState":
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RateLimitRuntimeState:
    local_date: str
    consecutive_429_count: int = 0
    daily_cooldown_count: int = 0
    cooldown_until: str | None = None
    last_request_at: str | None = None
    last_success_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RateLimitRuntimeState":
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RateLimitOutcome:
    daily_pause: bool
    wait_seconds: float
    retry_after_seconds: float
    consecutive_429_count: int
    daily_cooldown_count: int
    cooldown_until: str | None
    pause_state: PauseState | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_pause": self.daily_pause,
            "wait_seconds": self.wait_seconds,
            "retry_after_seconds": self.retry_after_seconds,
            "consecutive_429_count": self.consecutive_429_count,
            "daily_cooldown_count": self.daily_cooldown_count,
            "cooldown_until": self.cooldown_until,
            "pause_state": self.pause_state.to_dict() if self.pause_state else None,
        }


@dataclass(slots=True)
class PreflightDecision:
    allowed: bool
    reason: str
    projected_requests: int
    projected_tokens: int
    request_reserve: int | None
    token_reserve: int | None
    snapshot: QuotaSnapshot | None
    pause_state: PauseState | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "projected_requests": self.projected_requests,
            "projected_tokens": self.projected_tokens,
            "request_reserve": self.request_reserve,
            "token_reserve": self.token_reserve,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "pause_state": self.pause_state.to_dict() if self.pause_state else None,
        }


class GroqQuotaManager:
    def __init__(
        self,
        settings: Settings,
        runtime_dir: Path | None = None,
        *,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.settings = settings
        self.timezone = self._resolve_timezone(settings.groq_usage_timezone)
        self.store = ArtifactStore(runtime_dir or settings.groq_runtime_dir)
        self._sleep_fn = sleep_fn or time.sleep

    def _resolve_timezone(self, timezone_name: str):
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            if timezone_name == "Europe/Istanbul":
                return timezone(timedelta(hours=3), name=timezone_name)
            return datetime.now().astimezone().tzinfo or timezone.utc

    def _utc_now(self) -> datetime:
        return datetime.now(UTC)

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if value in (None, ""):
            return None
        return datetime.fromisoformat(value)

    def local_now(self) -> datetime:
        return datetime.now(self.timezone)

    def today_str(self) -> str:
        return self.local_now().date().isoformat()

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self._sleep_fn(seconds)

    def min_request_interval_seconds(self) -> float:
        if self.settings.groq_request_pacing_rpm <= 0:
            return 0.0
        return 60.0 / float(self.settings.groq_request_pacing_rpm)

    def load_snapshot(self) -> QuotaSnapshot | None:
        payload = self.store.read_json("quota_snapshot.json")
        if not payload:
            return None
        return QuotaSnapshot.from_dict(payload)

    def save_snapshot(self, snapshot: QuotaSnapshot) -> QuotaSnapshot:
        self.store.write_json("quota_snapshot.json", snapshot.to_dict())
        return snapshot

    def default_runtime_state(self) -> RateLimitRuntimeState:
        return RateLimitRuntimeState(local_date=self.today_str())

    def load_runtime_state(self) -> RateLimitRuntimeState:
        payload = self.store.read_json("rate_limit_state.json")
        if not payload:
            return self.default_runtime_state()
        state = RateLimitRuntimeState.from_dict(payload)
        if state.local_date != self.today_str():
            state = self.default_runtime_state()
            self.save_runtime_state(state)
            return state
        if state.cooldown_until and not self.is_cooldown_active(state):
            state.cooldown_until = None
            self.save_runtime_state(state)
        return state

    def save_runtime_state(self, state: RateLimitRuntimeState) -> RateLimitRuntimeState:
        self.store.write_json("rate_limit_state.json", state.to_dict())
        return state

    def load_pause_state(self) -> PauseState | None:
        payload = self.store.read_json("pause_state.json")
        if not payload:
            return None
        pause_state = PauseState.from_dict(payload)
        if pause_state.reason == "rate_limited_429":
            self.clear_pause_state()
            return None
        if not self.is_pause_active(pause_state):
            self.clear_pause_state()
            return None
        return pause_state

    def clear_pause_state(self) -> None:
        pause_state_path = self.store.resolve("pause_state.json")
        if pause_state_path.exists():
            pause_state_path.unlink()

    def save_pause_state(self, pause_state: PauseState) -> PauseState:
        self.store.write_json("pause_state.json", pause_state.to_dict())
        return pause_state

    def is_snapshot_stale(self, snapshot: QuotaSnapshot | None) -> bool:
        if snapshot is None:
            return True
        return snapshot.age_seconds() > self.settings.groq_quota_cache_ttl_seconds

    def is_pause_active(self, pause_state: PauseState | None) -> bool:
        if pause_state is None or not pause_state.active:
            return False
        return self.local_now().date() < date.fromisoformat(pause_state.resume_on_date)

    def is_cooldown_active(self, state: RateLimitRuntimeState | None) -> bool:
        if state is None:
            return False
        cooldown_until = self._parse_datetime(state.cooldown_until)
        if cooldown_until is None:
            return False
        return self._utc_now() < cooldown_until

    def cooldown_remaining_seconds(self, state: RateLimitRuntimeState | None) -> float:
        if state is None:
            return 0.0
        cooldown_until = self._parse_datetime(state.cooldown_until)
        if cooldown_until is None:
            return 0.0
        return max((cooldown_until - self._utc_now()).total_seconds(), 0.0)

    def request_reserve(self, limit_requests: int | None) -> int | None:
        if self.settings.groq_request_reserve is not None:
            return self.settings.groq_request_reserve
        if limit_requests is None:
            return self.settings.groq_daily_stop_threshold_requests
        return self.settings.groq_daily_stop_threshold_requests

    def token_reserve(self, limit_tokens: int | None) -> int | None:
        if self.settings.groq_token_reserve is not None:
            return self.settings.groq_token_reserve
        if limit_tokens is None:
            return None
        return max(
            self.settings.groq_token_reserve_floor,
            math.ceil(limit_tokens * self.settings.groq_token_reserve_percent),
        )

    def estimate_chat_tokens(
        self,
        messages: list[dict[str, Any]],
        max_output_tokens: int,
    ) -> int:
        prompt_chars = 0
        for message in messages:
            content = message.get("content", "")
            prompt_chars += len(content) if isinstance(content, str) else len(str(content))
        prompt_estimate = math.ceil(prompt_chars / 4) + (len(messages) * 12)
        return prompt_estimate + max_output_tokens

    def pause_for_day(
        self,
        *,
        reason: str,
        action_name: str,
        snapshot: QuotaSnapshot | None,
        details: dict[str, Any] | None = None,
    ) -> PauseState:
        tomorrow = self.local_now().date() + timedelta(days=1)
        pause_state = PauseState(
            active=True,
            reason=reason,
            triggered_at=utc_now_iso(),
            action_name=action_name,
            resume_on_date=tomorrow.isoformat(),
            last_seen_headers=snapshot.headers if snapshot else {},
            details=details or {},
        )
        return self.save_pause_state(pause_state)

    def record_history(
        self,
        *,
        action_name: str,
        status: str,
        projected_requests: int,
        projected_tokens: int,
        snapshot: QuotaSnapshot | None,
        details: dict[str, Any] | None = None,
    ) -> Path:
        payload = {
            "timestamp": utc_now_iso(),
            "action_name": action_name,
            "status": status,
            "projected_requests": projected_requests,
            "projected_tokens": projected_tokens,
            "snapshot": snapshot.to_dict() if snapshot else None,
            "details": details or {},
        }
        return self.store.append_jsonl(Path("history") / f"{self.today_str()}.jsonl", payload)

    def wait_for_request_slot(self, *, action_name: str) -> float:
        state = self.load_runtime_state()
        wait_seconds = 0.0
        if self.is_cooldown_active(state):
            wait_seconds = max(wait_seconds, self.cooldown_remaining_seconds(state))

        last_request_at = self._parse_datetime(state.last_request_at)
        if last_request_at is not None:
            elapsed = (self._utc_now() - last_request_at).total_seconds()
            wait_seconds = max(wait_seconds, self.min_request_interval_seconds() - elapsed)

        if wait_seconds > 0:
            self.record_history(
                action_name=action_name,
                status="waiting_for_slot",
                projected_requests=0,
                projected_tokens=0,
                snapshot=self.load_snapshot(),
                details={"wait_seconds": wait_seconds},
            )
            self.sleep(wait_seconds)

        state = self.load_runtime_state()
        if state.cooldown_until and not self.is_cooldown_active(state):
            state.cooldown_until = None
        state.last_request_at = utc_now_iso()
        self.save_runtime_state(state)
        return max(wait_seconds, 0.0)

    def mark_success(self) -> RateLimitRuntimeState:
        state = self.load_runtime_state()
        state.consecutive_429_count = 0
        if not self.is_cooldown_active(state):
            state.cooldown_until = None
        state.last_success_at = utc_now_iso()
        return self.save_runtime_state(state)

    def runtime_status(self) -> dict[str, Any]:
        state = self.load_runtime_state()
        return {
            "state": state.to_dict(),
            "cooldown_active": self.is_cooldown_active(state),
            "cooldown_until": state.cooldown_until,
            "cooldown_remaining_seconds": self.cooldown_remaining_seconds(state),
            "consecutive_429_count": state.consecutive_429_count,
            "daily_cooldown_count": state.daily_cooldown_count,
            "request_pacing_rpm": self.settings.groq_request_pacing_rpm,
            "daily_stop_threshold_requests": self.settings.groq_daily_stop_threshold_requests,
        }

    def evaluate_preflight(
        self,
        *,
        action_name: str,
        projected_requests: int,
        projected_tokens: int,
        snapshot: QuotaSnapshot | None,
    ) -> PreflightDecision:
        pause_state = self.load_pause_state()
        if self.is_pause_active(pause_state):
            return PreflightDecision(
                allowed=False,
                reason="paused_until_next_day",
                projected_requests=projected_requests,
                projected_tokens=projected_tokens,
                request_reserve=None,
                token_reserve=None,
                snapshot=snapshot,
                pause_state=pause_state,
            )

        if snapshot is None:
            return PreflightDecision(
                allowed=False,
                reason="missing_quota_snapshot",
                projected_requests=projected_requests,
                projected_tokens=projected_tokens,
                request_reserve=None,
                token_reserve=None,
                snapshot=None,
            )

        request_reserve = self.request_reserve(snapshot.limit_requests)
        token_reserve = self.token_reserve(snapshot.limit_tokens)

        if (
            snapshot.remaining_requests is not None
            and request_reserve is not None
            and snapshot.remaining_requests - projected_requests < request_reserve
        ):
            pause_state = None
            if self.settings.groq_pause_until_next_day_on_limit:
                pause_state = self.pause_for_day(
                    reason="daily_request_reserve_reached",
                    action_name=action_name,
                    snapshot=snapshot,
                    details={
                        "remaining_requests": snapshot.remaining_requests,
                        "projected_requests": projected_requests,
                        "request_reserve": request_reserve,
                    },
                )
            return PreflightDecision(
                allowed=False,
                reason="daily_request_reserve_reached",
                projected_requests=projected_requests,
                projected_tokens=projected_tokens,
                request_reserve=request_reserve,
                token_reserve=token_reserve,
                snapshot=snapshot,
                pause_state=pause_state,
            )

        if (
            snapshot.remaining_tokens is not None
            and token_reserve is not None
            and snapshot.remaining_tokens - projected_tokens < token_reserve
        ):
            pause_state = None
            if self.settings.groq_pause_until_next_day_on_limit:
                pause_state = self.pause_for_day(
                    reason="low_remaining_tokens",
                    action_name=action_name,
                    snapshot=snapshot,
                    details={
                        "remaining_tokens": snapshot.remaining_tokens,
                        "projected_tokens": projected_tokens,
                        "token_reserve": token_reserve,
                    },
                )
            return PreflightDecision(
                allowed=False,
                reason="low_remaining_tokens",
                projected_requests=projected_requests,
                projected_tokens=projected_tokens,
                request_reserve=request_reserve,
                token_reserve=token_reserve,
                snapshot=snapshot,
                pause_state=pause_state,
            )

        return PreflightDecision(
            allowed=True,
            reason="allowed",
            projected_requests=projected_requests,
            projected_tokens=projected_tokens,
            request_reserve=request_reserve,
            token_reserve=token_reserve,
            snapshot=snapshot,
            pause_state=None,
        )

    def mark_rate_limit_hit(
        self,
        *,
        action_name: str,
        snapshot: QuotaSnapshot | None,
        retry_after: str | None,
    ) -> RateLimitOutcome:
        retry_after_seconds = (
            _parse_seconds(retry_after)
            or (snapshot.retry_after_seconds if snapshot else None)
            or float(self.settings.groq_default_retry_after_seconds)
        )
        state = self.load_runtime_state()
        state.consecutive_429_count += 1

        pause_state: PauseState | None = None
        wait_seconds = float(retry_after_seconds)
        cooldown_until: str | None = state.cooldown_until

        if state.consecutive_429_count >= self.settings.groq_consecutive_429_before_cooldown:
            state.daily_cooldown_count += 1
            state.consecutive_429_count = 0
            if state.daily_cooldown_count >= self.settings.groq_daily_cooldown_limit:
                state.cooldown_until = None
                self.save_runtime_state(state)
                pause_state = self.pause_for_day(
                    reason="daily_cooldown_limit_reached",
                    action_name=action_name,
                    snapshot=snapshot,
                    details={
                        "retry_after_seconds": retry_after_seconds,
                        "daily_cooldown_count": state.daily_cooldown_count,
                    },
                )
                return RateLimitOutcome(
                    daily_pause=True,
                    wait_seconds=0.0,
                    retry_after_seconds=float(retry_after_seconds),
                    consecutive_429_count=state.consecutive_429_count,
                    daily_cooldown_count=state.daily_cooldown_count,
                    cooldown_until=None,
                    pause_state=pause_state,
                )

            cooldown_until_dt = self._utc_now() + timedelta(seconds=self.settings.groq_cooldown_seconds)
            state.cooldown_until = cooldown_until_dt.isoformat()
            cooldown_until = state.cooldown_until
            wait_seconds = float(self.settings.groq_cooldown_seconds)
        elif state.cooldown_until and not self.is_cooldown_active(state):
            state.cooldown_until = None
            cooldown_until = None

        self.save_runtime_state(state)
        return RateLimitOutcome(
            daily_pause=False,
            wait_seconds=float(wait_seconds),
            retry_after_seconds=float(retry_after_seconds),
            consecutive_429_count=state.consecutive_429_count,
            daily_cooldown_count=state.daily_cooldown_count,
            cooldown_until=cooldown_until,
            pause_state=None,
        )
