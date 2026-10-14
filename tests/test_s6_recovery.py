"""S6 offline long-outage, Telegram Session, 429 and SQLite lock regressions.

Exercises approved S2-S5 production contracts with virtual clocks and fakes.
No test-only hooks are added to the application.
"""

from __future__ import annotations

import asyncio
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.db import Database
from app.delivery import CoreStore, TaskStatus
from app.domain import Source, SourceObservation
from app.maintenance import MaintenanceError, inspect_database
from app.route_store import RouteStore
from app.rss import FeedFetchResult
from app.source_adapters import RSSSource, TelegramSource
from app.source_state import SourceStore
from app.web_auth import AdminWebConfig, WebAuth, password_hash


INITIAL = datetime(2026, 10, 14, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = INITIAL

    def __call__(self):
        return self.value

    def advance(self, seconds: int):
        self.value += timedelta(seconds=seconds)

    def seconds(self) -> int:
        return int(self.value.timestamp())


class FakeTelegram:
    def __init__(self):
        self.authorized = True
        self.messages = [
            SimpleNamespace(
                id=100, raw_text="DMIT\nhttps://www.nodeseek.com/post-100-1",
                entities=[],
            )
        ]
        self.calls = 0

    async def is_user_authorized(self):
        return self.authorized

    async def get_messages(self, _channel, *, limit):
        return self.messages[-limit:]

    async def iter_messages(self, _channel, *, min_id, reverse, limit):
        self.calls += 1
        assert reverse
        for msg in self.messages:
            if msg.id > min_id:
                yield msg
            if self.calls > 20:
                raise AssertionError("unbounded backfill")

    def append(self, msg_id: int):
        self.messages.append(SimpleNamespace(
            id=msg_id,
            raw_text=f"DMIT\nhttps://www.nodeseek.com/post-{msg_id}-1",
            entities=[],
        ))


class Http429(Exception):
    status = 429
    headers = {"Retry-After": "120"}


class FakeFeed:
    max_entries_per_feed = 30

    def __init__(self):
        self.calls = 0

    async def fetch(self, _url):
        self.calls += 1
        if self.calls == 1:
            raise Http429()
        return FeedFetchResult(feed_title="Official NodeSeek", entries=[])


class RecoveryContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory(prefix="seekpulse-s6-recovery-")
        self.addAsyncCleanup(self._cleanup)
        self.path = Path(self.directory.name) / "test.db"
        self.db = Database(self.path)
        await self.db.init()
        self.core = CoreStore(self.path)
        await self.core.init()
        self.sources = SourceStore(self.path)
        await self.sources.init()
        self.routes = RouteStore(self.path)
        await self.routes.init()
        self.user = await self.db.ensure_user_profile(
            101, 1101, None, "U", None, "private",
        )
        self.target = (await self.db.list_targets_by_tg_user(101))[0]
        self.clock = Clock()
        await self.core.observe(SourceObservation(
            Source.RSS, "rss-123", 123, INITIAL,
            title="DMIT offer",
        ))

    async def _cleanup(self):
        self.directory.cleanup()

    async def test_long_offline_expiration_is_auditable_and_fresh_work_proceeds(self):
        now = self.clock.seconds()
        await self.core.enqueue(
            self.user.id, 123, [self.target.id], now=now, ttl_seconds=1800
        )
        leased = (await self.core.claim(now=now, lease_seconds=30))[0]
        self.clock.advance(3600 * 12)  # VPS unreachable for 12 hours
        recovery = await CoreStore(self.path).recover(now=self.clock.seconds())
        self.assertEqual(recovery.expired, 1)
        self.assertFalse(await self.core.mark_sent(
            leased.id, leased.lease_token, now=self.clock.seconds()
        ))
        self.assertEqual((await self.core.list_tasks(self.user.id))[0].status,
                         TaskStatus.EXPIRED)
        await self.core.observe(SourceObservation(
            Source.RSS, "rss-124", 124, self.clock(),
            title="fresh post",
        ))
        self.assertEqual(await self.core.enqueue(
            self.user.id, 124, [self.target.id],
            now=self.clock.seconds(),
        ), 1)
        tasks = await self.core.claim(now=self.clock.seconds())
        self.assertEqual([t.post_id for t in tasks], [124])
        self.assertEqual(len(await self.core.list_tasks(self.user.id)), 2)

    async def test_interrupted_lease_recovers_without_reusing_old_token(self):
        now = self.clock.seconds()
        await self.core.enqueue(self.user.id, 123, [self.target.id], now=now)
        first = (await self.core.claim(now=now, lease_seconds=10))[0]
        self.clock.advance(11)
        got = await CoreStore(self.path).recover(now=self.clock.seconds())
        self.assertEqual(got.leases_requeued, 1)
        next_claim = (await self.core.claim(now=self.clock.seconds()))[0]
        self.assertNotEqual(next_claim.lease_token, first.lease_token)
        self.assertFalse(await self.core.mark_sent(
            first.id, first.lease_token, now=self.clock.seconds()
        ))
        self.assertTrue(await self.core.mark_sent(
            next_claim.id, next_claim.lease_token,
            now=self.clock.seconds() + 1,
        ))
        self.assertEqual((await self.core.list_tasks(self.user.id))[0].status,
                         TaskStatus.SENT)

    async def test_session_revoked_does_not_advance_cursor_and_recovery_catches_up(self):
        await self.sources.set_enabled(Source.TELEGRAM, True)
        fake = FakeTelegram()
        tg = TelegramSource(
            fake, self.core, self.sources, clock=self.clock, backfill_limit=100
        )
        self.assertEqual((await tg.sync_once()).outcome, "baseline")
        self.assertEqual((await self.sources.status(Source.TELEGRAM)).cursor, 100)
        self.assertIsNone(await self.core.get_post(100))  # don't replay pre-baseline

        fake.authorized = False
        fake.append(101)
        self.clock.advance(1)
        self.assertEqual((await tg.sync_once()).outcome, "auth_required")
        self.assertEqual((await self.sources.status(Source.TELEGRAM)).cursor, 100)
        self.assertIsNone(await self.core.get_post(101))
        self.assertEqual((await tg.sync_once()).outcome, "backoff")
        self.assertIsNone((await self.sources.status(Source.RSS)).last_error_code)
        fake.authorized = True
        self.clock.advance(3600)
        self.assertEqual((await tg.sync_once()).outcome, "ok")
        self.assertEqual((await SourceStore(self.path).status(Source.TELEGRAM)).cursor, 101)
        self.assertIsNotNone(await self.core.get_post(101))
        self.assertIsNone(await self.core.get_post(100))
        self.assertEqual((await tg.sync_once()).outcome, "ok")
        self.assertEqual(len((await self.core.get_post(101)).observations), 1)

    async def test_rss_platform_429_and_telegram_backoff_are_independent(self):
        feed = FakeFeed()
        rss = RSSSource(feed, self.core, self.sources, clock=self.clock)
        self.assertEqual((await rss.poll_once()).outcome, "error")
        self.assertEqual(feed.calls, 1)
        self.assertEqual(
            (await self.sources.status(Source.RSS)).retry_at,
            self.clock.seconds() + 120,
        )
        self.assertEqual((await rss.poll_once()).outcome, "backoff")
        self.assertEqual(feed.calls, 1)
        self.assertEqual((await self.sources.status(Source.TELEGRAM)).retry_at, 0)
        self.clock.advance(120)
        self.assertEqual((await rss.poll_once()).outcome, "baseline")
        self.assertEqual(feed.calls, 2)
        self.assertEqual((await self.sources.status(Source.RSS)).failures, 0)

    async def test_source_gap_survives_outage_and_is_never_auto_cleared(self):
        await self.sources.mark_gap(Source.RSS, "rss_window_no_overlap")
        await self.sources.mark_failure(Source.RSS, "timeout", now=self.clock.seconds())
        self.clock.advance(3600 * 24)
        await SourceStore(self.path).mark_success(
            Source.RSS, now=self.clock.seconds()
        )
        restored = await SourceStore(self.path).status(Source.RSS)
        self.assertEqual(restored.gap_code, "rss_window_no_overlap")
        self.assertEqual(restored.failures, 0)

    async def test_target_rate_limit_is_independent_and_expired_after_outage(self):
        await self.db.add_target(
            self.user.id, 2202, chat_title="Extra", chat_type="private"
        )
        own = [t.id for t in await self.db.list_targets_by_tg_user(101)]
        await self.routes.extend_cooldown(own[0], until=400)
        await self.routes.extend_cooldown(own[1], until=10000)
        self.assertEqual(await self.routes.blocked_targets(now=100),
                         set(own))
        self.assertEqual(await RouteStore(self.path).blocked_targets(now=500),
                         {own[1]})
        self.assertEqual(await RouteStore(self.path).blocked_targets(now=10000),
                         set())

    async def test_sqlite_busy_fail_closed_then_recovers_without_task_loss(self):
        await self.core.enqueue(
            self.user.id, 123, [self.target.id], now=self.clock.seconds()
        )
        # With no application connections held, temporary DELETE-journal
        # EXCLUSIVE transaction blocks read-only integrity inspection.
        with sqlite3.connect(self.path, timeout=0.1) as other:
            mode = other.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            self.assertEqual(mode.lower(), "delete")
            other.execute("BEGIN EXCLUSIVE")
            other.execute("SELECT 1 FROM users")
            with self.assertRaises(MaintenanceError) as exc:
                inspect_database(self.path)
            self.assertEqual(exc.exception.code, "database_busy")
            other.rollback()
        self.assertEqual(inspect_database(self.path)["tasks"], {"pending": 1})
        self.assertEqual(len(await self.core.claim(now=self.clock.seconds())), 1)

    async def test_web_session_does_not_survive_new_process_and_no_token_in_db(self):
        config = AdminWebConfig(
            101, password_hash("test password for S6!", salt=b"1234567890abcdef")
        )
        running = WebAuth(config)
        token, session = running.new_session(authenticated=True)
        self.assertIsNotNone(running.get(token, authenticated=True))
        restarted = WebAuth(config)
        self.assertIsNone(restarted.get(token))
        self.assertNotIn(token.encode(), self.path.read_bytes())
        self.assertNotIn(session.csrf.encode(), self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
