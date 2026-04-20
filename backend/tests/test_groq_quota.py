from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from app.core.config import Settings
from app.providers.groq_quota import PauseState, QuotaSnapshot, GroqQuotaManager


class GroqQuotaManagerTests(unittest.TestCase):
    def build_settings(self) -> Settings:
        return Settings(
            _env_file=None,
            GROQ_MODE="free",
            GROQ_CHECK_BEFORE_EACH_ACTION=True,
            GROQ_PAUSE_UNTIL_NEXT_DAY_ON_LIMIT=True,
            GROQ_USAGE_TIMEZONE="Europe/Istanbul",
            GROQ_REQUEST_PACING_RPM=12,
            GROQ_DEFAULT_RETRY_AFTER_SECONDS=60,
            GROQ_CONSECUTIVE_429_BEFORE_COOLDOWN=3,
            GROQ_COOLDOWN_SECONDS=300,
            GROQ_DAILY_COOLDOWN_LIMIT=3,
            GROQ_DAILY_STOP_THRESHOLD_REQUESTS=50,
        )

    def test_low_remaining_requests_creates_daily_pause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manager = GroqQuotaManager(self.build_settings(), runtime_dir=Path(tmp_dir))
            snapshot = QuotaSnapshot(
                captured_at="2026-04-18T00:00:00+00:00",
                model="openai/gpt-oss-120b",
                source="test",
                limit_requests=1000,
                remaining_requests=50,
            )
            decision = manager.evaluate_preflight(
                action_name="phase7_batch",
                projected_requests=1,
                projected_tokens=50,
                snapshot=snapshot,
            )
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.reason, "daily_request_reserve_reached")
            pause_state = manager.load_pause_state()
            self.assertIsNotNone(pause_state)
            self.assertTrue(manager.is_pause_active(pause_state))

    def test_low_token_preflight_creates_pause_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manager = GroqQuotaManager(self.build_settings(), runtime_dir=Path(tmp_dir))
            snapshot = QuotaSnapshot(
                captured_at="2026-04-18T00:00:00+00:00",
                model="openai/gpt-oss-120b",
                source="test",
                limit_requests=1000,
                limit_tokens=12000,
                remaining_requests=999,
                remaining_tokens=900,
            )
            decision = manager.evaluate_preflight(
                action_name="phase4_wording_batch",
                projected_requests=1,
                projected_tokens=50,
                snapshot=snapshot,
            )
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.reason, "low_remaining_tokens")
            pause_state = manager.load_pause_state()
            self.assertIsNotNone(pause_state)
            self.assertTrue(manager.is_pause_active(pause_state))

    def test_legacy_rate_limit_pause_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manager = GroqQuotaManager(self.build_settings(), runtime_dir=Path(tmp_dir))
            legacy_pause = PauseState(
                active=True,
                reason="rate_limited_429",
                triggered_at="2026-04-18T00:00:00+00:00",
                action_name="legacy_action",
                resume_on_date=(manager.local_now().date() + timedelta(days=1)).isoformat(),
            )
            manager.save_pause_state(legacy_pause)
            loaded = manager.load_pause_state()
            self.assertIsNone(loaded)

    def test_expired_pause_state_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manager = GroqQuotaManager(self.build_settings(), runtime_dir=Path(tmp_dir))
            expired_pause = PauseState(
                active=True,
                reason="daily_request_reserve_reached",
                triggered_at="2026-04-18T00:00:00+00:00",
                action_name="quota_probe",
                resume_on_date=manager.local_now().date().isoformat(),
            )
            manager.save_pause_state(expired_pause)
            loaded = manager.load_pause_state()
            self.assertIsNone(loaded)

    def test_first_429_only_sets_consecutive_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manager = GroqQuotaManager(self.build_settings(), runtime_dir=Path(tmp_dir))
            outcome = manager.mark_rate_limit_hit(
                action_name="phase5_retry",
                snapshot=None,
                retry_after="2",
            )
            state = manager.load_runtime_state()
            self.assertFalse(outcome.daily_pause)
            self.assertEqual(outcome.wait_seconds, 2.0)
            self.assertEqual(state.consecutive_429_count, 1)
            self.assertEqual(state.daily_cooldown_count, 0)
            self.assertIsNone(state.cooldown_until)

    def test_third_429_starts_five_minute_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manager = GroqQuotaManager(self.build_settings(), runtime_dir=Path(tmp_dir))
            manager.mark_rate_limit_hit(action_name="phase5_retry", snapshot=None, retry_after="2")
            manager.mark_rate_limit_hit(action_name="phase5_retry", snapshot=None, retry_after="2")
            outcome = manager.mark_rate_limit_hit(action_name="phase5_retry", snapshot=None, retry_after="2")
            state = manager.load_runtime_state()
            self.assertFalse(outcome.daily_pause)
            self.assertEqual(outcome.wait_seconds, 300.0)
            self.assertEqual(state.consecutive_429_count, 0)
            self.assertEqual(state.daily_cooldown_count, 1)
            self.assertIsNotNone(state.cooldown_until)

    def test_success_resets_consecutive_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manager = GroqQuotaManager(self.build_settings(), runtime_dir=Path(tmp_dir))
            manager.mark_rate_limit_hit(action_name="phase5_retry", snapshot=None, retry_after="2")
            manager.mark_rate_limit_hit(action_name="phase5_retry", snapshot=None, retry_after="2")
            manager.mark_success()
            state = manager.load_runtime_state()
            self.assertEqual(state.consecutive_429_count, 0)
            self.assertIsNotNone(state.last_success_at)

    def test_third_cooldown_stops_for_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manager = GroqQuotaManager(self.build_settings(), runtime_dir=Path(tmp_dir))
            final_outcome = None
            for index in range(9):
                final_outcome = manager.mark_rate_limit_hit(
                    action_name=f"phase5_retry_{index}",
                    snapshot=None,
                    retry_after="2",
                )
                if (index + 1) % 3 == 0 and index < 8:
                    state = manager.load_runtime_state()
                    state.cooldown_until = None
                    manager.save_runtime_state(state)
            self.assertIsNotNone(final_outcome)
            self.assertTrue(final_outcome.daily_pause)
            pause_state = manager.load_pause_state()
            self.assertIsNotNone(pause_state)
            self.assertEqual(pause_state.reason, "daily_cooldown_limit_reached")

    def test_wait_for_request_slot_applies_pacing(self) -> None:
        sleep_calls: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with tempfile.TemporaryDirectory() as tmp_dir:
            manager = GroqQuotaManager(
                self.build_settings(),
                runtime_dir=Path(tmp_dir),
                sleep_fn=fake_sleep,
            )
            state = manager.load_runtime_state()
            state.last_request_at = manager._utc_now().isoformat()
            manager.save_runtime_state(state)
            manager.wait_for_request_slot(action_name="phase5_pacing")
            self.assertTrue(sleep_calls)
            self.assertGreaterEqual(sleep_calls[0], 4.0)

    def test_istanbul_timezone_falls_back_without_zoneinfo_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = self.build_settings()
            manager = GroqQuotaManager(settings, runtime_dir=Path(tmp_dir))
            self.assertIsNotNone(manager.local_now().tzinfo)
            self.assertEqual(manager.today_str(), manager.local_now().date().isoformat())

    def test_quota_snapshot_parses_hour_minute_second_reset_headers(self) -> None:
        snapshot = QuotaSnapshot.from_headers(
            {
                "x-ratelimit-reset-requests": "1h10m4.5s",
                "x-ratelimit-reset-tokens": "2m3s",
            },
            model="openai/gpt-oss-120b",
            source="test",
        )
        self.assertEqual(snapshot.reset_requests_seconds, 4204.5)
        self.assertEqual(snapshot.reset_tokens_seconds, 123.0)


if __name__ == "__main__":
    unittest.main()
