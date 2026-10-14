"""S3 local source state contracts. All SQLite files are temporary."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db import Database
from app.delivery import CoreStore
from app.domain import Source
from app.source_state import SourceStore


class SourceStateContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory(prefix="seekpulse-s3-")
        self.addAsyncCleanup(self._cleanup)
        self.path = Path(self.directory.name) / "test.sqlite3"
        self.db = Database(self.path)
        await self.db.init()
        self.core = CoreStore(self.path)
        await self.core.init()
        self.state = SourceStore(self.path)
        await self.state.init()

    async def _cleanup(self):
        self.directory.cleanup()

    async def test_defaults_independent_and_idempotent(self):
        rss = await self.state.status(Source.RSS)
        tg = await self.state.status(Source.TELEGRAM)
        self.assertTrue(rss.enabled)
        self.assertFalse(tg.enabled)  # No Session or implicit live TG login
        self.assertFalse(rss.initialized)
        self.assertEqual(tg.cursor, 0)
        await SourceStore(self.path).init()
        self.assertTrue((await self.state.status(Source.RSS)).enabled)
        self.assertFalse((await self.state.status(Source.TELEGRAM)).enabled)

    async def test_rss_initial_baseline_is_atomic_and_survives_restart(self):
        self.assertTrue(await self.state.bootstrap_rss([1, 2, 2], now=100))
        self.assertTrue(await self.state.rss_seen(1))
        self.assertTrue(await self.state.rss_seen(2))
        self.assertFalse(await self.state.rss_seen(3))
        self.assertFalse(await self.state.bootstrap_rss([3], now=101))
        self.assertFalse(await self.state.rss_seen(3))
        self.assertTrue((await SourceStore(self.path).status(Source.RSS)).initialized)
        self.assertIsNone(await self.core.get_post(1))
        self.assertEqual(await self.state.remember_rss(3, now=102), True)
        self.assertEqual(await self.state.remember_rss(3, now=103), False)

    async def test_invalid_baseline_does_not_mark_initialized(self):
        with self.assertRaises(ValueError):
            await self.state.bootstrap_rss([5, 0], now=100)
        self.assertFalse((await self.state.status(Source.RSS)).initialized)
        self.assertFalse(await self.state.rss_seen(5))

    async def test_telegram_cursor_monotonic_and_survives_new_instance(self):
        await self.state.set_enabled(Source.TELEGRAM, True)
        self.assertTrue(await self.state.bootstrap_telegram(100))
        self.assertFalse(await self.state.bootstrap_telegram(999))
        await self.state.advance_telegram(103)
        await self.state.advance_telegram(101)
        reopened = SourceStore(self.path)
        self.assertEqual((await reopened.status(Source.TELEGRAM)).cursor, 103)
        self.assertFalse((await reopened.status(Source.RSS)).initialized)

    async def test_pause_and_resume_preserve_cursors(self):
        await self.state.bootstrap_rss([10], now=100)
        await self.state.bootstrap_telegram(50)
        await self.state.set_enabled(Source.RSS, False)
        await self.state.set_enabled(Source.TELEGRAM, True)
        self.assertEqual((await self.state.status(Source.RSS)).enabled, False)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).enabled, True)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 50)
        self.assertTrue(await self.state.rss_seen(10))

    async def test_rate_limits_and_health_are_per_source(self):
        first = await self.state.mark_failure(Source.RSS, "http_429", now=100, retry_after_seconds=120)
        self.assertEqual(first, 220)
        second = await self.state.mark_failure(Source.RSS, "timeout", now=101)
        self.assertEqual(second, 121)
        rss = await self.state.status(Source.RSS)
        self.assertEqual(rss.failures, 2)
        self.assertEqual(rss.last_error_code, "timeout")
        self.assertIsNone((await self.state.status(Source.TELEGRAM)).last_error_code)
        await self.state.mark_success(Source.RSS, now=130)
        self.assertEqual((await self.state.status(Source.RSS)).retry_at, 0)
        self.assertEqual((await self.state.status(Source.RSS)).last_success_at, 130)

    async def test_backfill_and_auth_fail_closed(self):
        self.assertGreaterEqual(
            await self.state.mark_failure(Source.TELEGRAM, "auth_required", now=100),
            3700,
        )
        self.assertGreaterEqual(
            await self.state.mark_failure(Source.RSS, "http_403", now=100),
            3700,
        )

    async def test_gap_sticky_until_explicit_acknowledgement(self):
        await self.state.mark_gap(Source.RSS, "rss_window_no_overlap")
        await self.state.mark_success(Source.RSS, now=100)
        self.assertEqual(
            (await self.state.status(Source.RSS)).gap_code, "rss_window_no_overlap"
        )
        self.assertIsNone((await self.state.status(Source.TELEGRAM)).gap_code)
        await self.state.acknowledge_gap(Source.RSS)
        self.assertIsNone((await self.state.status(Source.RSS)).gap_code)

    async def test_bad_inputs_are_rejected_not_logged(self):
        with self.assertRaises(ValueError):
            await self.state.set_enabled(Source.RSS, 1)
        with self.assertRaises(ValueError):
            await self.state.mark_failure(Source.RSS, "token=secret", now=100)
        with self.assertRaises(ValueError):
            await self.state.mark_gap(Source.TELEGRAM, "bad\ntrace")
        with self.assertRaises(ValueError):
            await self.state.bootstrap_telegram(-1)
        with self.assertRaises(ValueError):
            await self.state.mark_failure(Source.RSS, "timeout", now=100, retry_after_seconds=100000)
        with self.assertRaises(ValueError):
            await self.state.rss_seen(2**65)

    async def test_legacy_history_preserved_no_automatic_replay(self):
        user = await self.db.ensure_user_profile(9, 9, None, "U", None, "private")
        await self.db.mark_delivered(
            user.id, "legacy", title="old", link="old",
            category_slug=None, matched_keywords=["dmit"],
        )
        await self.state.init()
        self.assertEqual(len(await self.db.list_history_by_tg_user(9, 20)), 1)
        self.assertEqual(await self.core.list_tasks(user.id), [])


if __name__ == "__main__":
    unittest.main()
