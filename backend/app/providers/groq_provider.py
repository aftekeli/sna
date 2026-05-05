from __future__ import annotations

from typing import Any

import httpx
from groq import Groq

from app.core.config import Settings
from app.providers.base import ProviderSnapshot
from app.providers.groq_quota import GroqQuotaManager, QuotaSnapshot


class GroqActionBlockedError(RuntimeError):
    """Raised when the Groq runtime blocks a new action before sending it."""


class GroqRateLimitedError(RuntimeError):
    """Raised when repeated 429s escalate into a day-level stop."""


class GroqProvider:
    """Groq chat-completion client with quota preflight and rate-limit history."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.quota = GroqQuotaManager(settings)

    @property
    def configured(self) -> bool:
        return bool(self.settings.groq_api_key)

    def build_client(self) -> Groq:
        if not self.configured:
            raise ValueError("Groq provider is not configured.")
        return Groq(api_key=self.settings.groq_api_key)

    def build_http_client(self) -> httpx.Client:
        if not self.configured:
            raise ValueError("Groq provider is not configured.")
        return httpx.Client(
            base_url="https://api.groq.com/openai/v1",
            headers={
                "Authorization": f"Bearer {self.settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    def _capture_snapshot(
        self,
        response: httpx.Response,
        *,
        source: str,
        service_tier: str | None = None,
    ) -> QuotaSnapshot:
        snapshot = QuotaSnapshot.from_headers(
            dict(response.headers),
            model=self.settings.groq_model,
            source=source,
            service_tier=service_tier,
        )
        self.quota.save_snapshot(snapshot)
        return snapshot

    def _probe_request(self) -> httpx.Response:
        payload = {
            "model": self.settings.groq_model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "temperature": 0,
        }
        with self.build_http_client() as client:
            return client.post("/chat/completions", json=payload)

    def get_quota_snapshot(self, *, force_probe: bool = False) -> QuotaSnapshot | None:
        snapshot = self.quota.load_snapshot()
        pause_state = self.quota.load_pause_state()
        if self.quota.is_pause_active(pause_state):
            return snapshot
        if not force_probe and not self.quota.is_snapshot_stale(snapshot):
            return snapshot

        if not self.configured:
            return snapshot

        self.quota.wait_for_request_slot(action_name="quota_probe")
        response = self._probe_request()
        service_tier = None
        try:
            service_tier = response.json().get("service_tier")
        except Exception:
            service_tier = None
        snapshot = self._capture_snapshot(response, source="probe", service_tier=service_tier)
        status = "probe_ok" if response.is_success else f"probe_http_{response.status_code}"
        details: dict[str, Any] = {"status_code": response.status_code}
        if response.status_code == 429:
            outcome = self.quota.mark_rate_limit_hit(
                action_name="quota_probe",
                snapshot=snapshot,
                retry_after=response.headers.get("retry-after"),
            )
            details["rate_limit_outcome"] = outcome.to_dict()
            if outcome.daily_pause:
                details["pause_state"] = outcome.pause_state.to_dict() if outcome.pause_state else None
            elif outcome.wait_seconds > 0:
                self.quota.sleep(outcome.wait_seconds)
        else:
            self.quota.mark_success()
        self.quota.record_history(
            action_name="quota_probe",
            status=status,
            projected_requests=1,
            projected_tokens=2,
            snapshot=snapshot,
            details=details,
        )
        if response.status_code == 429:
            return snapshot
        response.raise_for_status()
        return snapshot

    def preflight_action(
        self,
        *,
        action_name: str,
        projected_tokens: int,
        projected_requests: int = 1,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        if not self.settings.groq_check_before_each_action:
            snapshot = self.quota.load_snapshot()
            return {
                "allowed": True,
                "reason": "preflight_disabled",
                "projected_requests": projected_requests,
                "projected_tokens": projected_tokens,
                "request_reserve": None,
                "token_reserve": None,
                "snapshot": snapshot.to_dict() if snapshot else None,
                "pause_state": None,
            }

        pause_state = self.quota.load_pause_state()
        if self.quota.is_pause_active(pause_state):
            decision = {
                "allowed": False,
                "reason": "paused_until_next_day",
                "projected_requests": projected_requests,
                "projected_tokens": projected_tokens,
                "request_reserve": None,
                "token_reserve": None,
                "snapshot": self.quota.load_snapshot().to_dict() if self.quota.load_snapshot() else None,
                "pause_state": pause_state.to_dict() if pause_state else None,
            }
            self.quota.record_history(
                action_name=action_name,
                status="preflight_blocked",
                projected_requests=projected_requests,
                projected_tokens=projected_tokens,
                snapshot=self.quota.load_snapshot(),
                details={"reason": "paused_until_next_day"},
            )
            return decision

        snapshot = self.get_quota_snapshot(force_probe=force_refresh)
        decision = self.quota.evaluate_preflight(
            action_name=action_name,
            projected_requests=projected_requests,
            projected_tokens=projected_tokens,
            snapshot=snapshot,
        )
        if not decision.allowed:
            self.quota.record_history(
                action_name=action_name,
                status="preflight_blocked",
                projected_requests=projected_requests,
                projected_tokens=projected_tokens,
                snapshot=snapshot,
                details={"reason": decision.reason},
            )
        return decision.to_dict()

    def estimate_chat_tokens(
        self,
        messages: list[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> int:
        return self.quota.estimate_chat_tokens(messages, max_output_tokens)

    def chat_completion(
        self,
        *,
        action_name: str,
        messages: list[dict[str, Any]],
        max_output_tokens: int = 256,
        temperature: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        projected_tokens = self.estimate_chat_tokens(
            messages,
            max_output_tokens=max_output_tokens,
        )
        payload = {
            "model": self.settings.groq_model,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "temperature": temperature,
        }

        while True:
            decision = self.preflight_action(
                action_name=action_name,
                projected_tokens=projected_tokens,
                projected_requests=1,
            )
            if not decision["allowed"]:
                raise GroqActionBlockedError(f"Groq action blocked: {decision['reason']}")

            self.quota.wait_for_request_slot(action_name=action_name)
            with self.build_http_client() as client:
                response = client.post("/chat/completions", json=payload)

            service_tier = None
            body: dict[str, Any] | None = None
            try:
                body = response.json()
                service_tier = body.get("service_tier")
            except Exception:
                body = None
                service_tier = None

            snapshot = self._capture_snapshot(
                response,
                source="chat_completion",
                service_tier=service_tier,
            )

            if response.status_code == 429:
                outcome = self.quota.mark_rate_limit_hit(
                    action_name=action_name,
                    snapshot=snapshot,
                    retry_after=response.headers.get("retry-after"),
                )
                self.quota.record_history(
                    action_name=action_name,
                    status="rate_limited",
                    projected_requests=1,
                    projected_tokens=projected_tokens,
                    snapshot=snapshot,
                    details={
                        "metadata": metadata or {},
                        "rate_limit_outcome": outcome.to_dict(),
                    },
                )
                if outcome.daily_pause:
                    raise GroqRateLimitedError(
                        "Groq returned repeated 429 responses and the runtime paused for the day."
                    )
                if outcome.wait_seconds > 0:
                    self.quota.sleep(outcome.wait_seconds)
                continue

            response.raise_for_status()
            self.quota.mark_success()
            usage = body.get("usage") if body else None
            self.quota.record_history(
                action_name=action_name,
                status="success",
                projected_requests=1,
                projected_tokens=projected_tokens,
                snapshot=snapshot,
                details={
                    "metadata": metadata or {},
                    "usage": usage,
                },
            )
            return {
                "response": body,
                "quota_snapshot": snapshot.to_dict(),
            }

    def snapshot(self) -> ProviderSnapshot:
        quota_snapshot = self.quota.load_snapshot()
        pause_state = self.quota.load_pause_state()
        details: dict[str, Any] = {
            "model": self.settings.groq_model,
            "plan_mode": self.settings.groq_mode,
            "check_before_each_action": self.settings.groq_check_before_each_action,
            "allow_ollama_fallback": self.settings.groq_allow_ollama_fallback,
            "pause_until_next_day_on_limit": self.settings.groq_pause_until_next_day_on_limit,
            "quota_snapshot": quota_snapshot.to_dict() if quota_snapshot else None,
            "pause_state": pause_state.to_dict() if pause_state else None,
            "runtime_status": self.quota.runtime_status(),
        }
        return ProviderSnapshot(
            name="groq",
            configured=self.configured,
            mode="primary",
            details=details,
        )
