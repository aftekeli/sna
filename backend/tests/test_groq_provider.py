from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.providers.groq_provider import GroqProvider, GroqRateLimitedError
from app.providers.groq_quota import GroqQuotaManager, QuotaSnapshot


class _FakeClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, _: str, json: dict[str, Any]) -> httpx.Response:
        del json
        if not self._responses:
            raise AssertionError("No more fake responses available.")
        return self._responses.pop(0)


class GroqProviderRetryTests(unittest.TestCase):
    def build_settings(self) -> Settings:
        return Settings(
            _env_file=None,
            GROQ_API_KEY="test-key",
            GROQ_MODE="free",
            GROQ_CHECK_BEFORE_EACH_ACTION=True,
            GROQ_PAUSE_UNTIL_NEXT_DAY_ON_LIMIT=True,
            GROQ_REQUEST_PACING_RPM=100000,
            GROQ_DEFAULT_RETRY_AFTER_SECONDS=0,
            GROQ_CONSECUTIVE_429_BEFORE_COOLDOWN=3,
            GROQ_COOLDOWN_SECONDS=0,
            GROQ_DAILY_COOLDOWN_LIMIT=3,
            GROQ_DAILY_STOP_THRESHOLD_REQUESTS=50,
        )

    def _response(
        self,
        status_code: int,
        *,
        content: str = "ok",
        remaining_requests: str = "900",
        retry_after: str | None = None,
    ) -> httpx.Response:
        headers = {
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-remaining-requests": remaining_requests,
            "x-ratelimit-limit-tokens": "12000",
            "x-ratelimit-remaining-tokens": "11000",
        }
        if retry_after is not None:
            headers["retry-after"] = retry_after
        payload: dict[str, Any] = {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        return httpx.Response(
            status_code=status_code,
            headers=headers,
            json=payload,
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )

    def test_chat_completion_retries_after_temporary_429(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            provider = GroqProvider(self.build_settings())
            provider.quota = GroqQuotaManager(
                self.build_settings(),
                runtime_dir=Path(tmp_dir),
                sleep_fn=lambda _: None,
            )
            provider.quota.save_snapshot(
                QuotaSnapshot(
                    captured_at=provider.quota._utc_now().isoformat(),
                    model="openai/gpt-oss-120b",
                    source="test",
                    limit_requests=1000,
                    limit_tokens=12000,
                    remaining_requests=900,
                    remaining_tokens=11000,
                )
            )
            responses = [
                self._response(429, retry_after="0", remaining_requests="899"),
                self._response(200, content="Izmir", remaining_requests="898"),
            ]
            provider.build_http_client = lambda: _FakeClient(responses)  # type: ignore[method-assign]

            result = provider.chat_completion(
                action_name="phase5_retry",
                messages=[{"role": "user", "content": "Where was the director born?"}],
                max_output_tokens=32,
            )

            self.assertEqual(
                result["response"]["choices"][0]["message"]["content"],
                "Izmir",
            )
            self.assertIsNone(provider.quota.load_pause_state())
            runtime_state = provider.quota.load_runtime_state()
            self.assertEqual(runtime_state.consecutive_429_count, 0)
            self.assertEqual(runtime_state.daily_cooldown_count, 0)

    def test_chat_completion_raises_after_daily_cooldown_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            provider = GroqProvider(self.build_settings())
            provider.quota = GroqQuotaManager(
                self.build_settings(),
                runtime_dir=Path(tmp_dir),
                sleep_fn=lambda _: None,
            )
            provider.quota.save_snapshot(
                QuotaSnapshot(
                    captured_at=provider.quota._utc_now().isoformat(),
                    model="openai/gpt-oss-120b",
                    source="test",
                    limit_requests=1000,
                    limit_tokens=12000,
                    remaining_requests=900,
                    remaining_tokens=11000,
                )
            )
            responses = [self._response(429, retry_after="0", remaining_requests=str(899 - index)) for index in range(9)]
            provider.build_http_client = lambda: _FakeClient(responses)  # type: ignore[method-assign]

            with self.assertRaises(GroqRateLimitedError):
                provider.chat_completion(
                    action_name="phase5_retry_limit",
                    messages=[{"role": "user", "content": "Where was the director born?"}],
                    max_output_tokens=32,
                )

            pause_state = provider.quota.load_pause_state()
            self.assertIsNotNone(pause_state)
            self.assertEqual(pause_state.reason, "daily_cooldown_limit_reached")


if __name__ == "__main__":
    unittest.main()
