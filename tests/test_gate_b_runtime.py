"""Gate B one-process lifecycle, lock, opt-in and stale-source contracts.

All external components are fake; no real Bot, Telethon, API, Web listener,
VPS, Session or protected environment data.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.db import Database
from app.gate_b_targets import GateBTargetStore
from app.main import _serve_locked
from app.route_store import RouteStore
from app.delivery import CoreStore
from app.domain import Source
from app.instance_lock import database_owner_lock
from app.rss import FeedEntry, FeedFetchResult
from app.source_adapters import RSSSource, TelegramSource
from app.source_state import SourceStore

try:
    from app.v11_main import GateBComponents, _run_live, main, push_secret, supervise
except ModuleNotFoundError:
    GateBComponents = None


class FakeUpdater:
    def __init__(self, trace):
        self.trace = trace
        self.active = asyncio.Event()

    async def start_polling(self):
        self.trace.append("polling.start")
        self.active.set()

    async def stop(self):
        self.trace.append("polling.stop")


class FakeBot:
    def __init__(self, trace):
        self.trace = trace
        self.updater = FakeUpdater(trace)

    async def initialize(self):
        self.trace.append("bot.initialize")

    async def start(self):
        self.trace.append("bot.start")

    async def stop(self):
        self.trace.append("bot.stop")

    async def shutdown(self):
        self.trace.append("bot.shutdown")


class FakeLoop:
    def __init__(self, name, trace, *, exit_immediately=False):
        self.name = name
        self.trace = trace
        self.exit_immediately = exit_immediately

    async def run_forever(self, stop):
        self.trace.append(self.name + ".start")
        if not self.exit_immediately:
            await stop.wait()
        self.trace.append(self.name + ".stop")


class FakeServer:
    def __init__(self, trace, *, exit_immediately=False):
        self.trace = trace
        self.should_exit = False
        self.exit_immediately = exit_immediately

    async def serve(self):
        self.trace.append("web.start")
        if not self.exit_immediately:
            while not self.should_exit:
                await asyncio.sleep(0.01)
        self.trace.append("web.stop")


@unittest.skipUnless(GateBComponents is not None, "optional FastAPI/Uvicorn needed")
class RuntimeLifecycleContracts(unittest.IsolatedAsyncioTestCase):
    def fake_components(self, trace, *, failed=None):
        return GateBComponents(
            FakeBot(trace),
            FakeLoop("source", trace, exit_immediately=failed == "source"),
            FakeLoop("dispatcher", trace, exit_immediately=failed == "dispatcher"),
            FakeLoop("worker", trace, exit_immediately=failed == "worker"),
            FakeServer(trace, exit_immediately=failed == "web"),
        )

    async def test_clean_stop_drains_all_and_stops_bot_once(self):
        trace = []
        stop = asyncio.Event()
        c = self.fake_components(trace)
        task = asyncio.create_task(supervise(c, stop))
        await asyncio.wait_for(c.application.updater.active.wait(), 2)
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, 3)
        self.assertTrue(all(x in trace for x in (
            "bot.initialize", "bot.start", "polling.start",
            "source.start", "dispatcher.start", "worker.start", "web.start",
            "source.stop", "dispatcher.stop", "worker.stop", "web.stop",
            "polling.stop", "bot.stop", "bot.shutdown",
        )))
        self.assertLess(trace.index("polling.stop"), trace.index("bot.shutdown"))

    async def test_any_component_early_exit_aborts_other_sends(self):
        trace = []
        c = self.fake_components(trace, failed="worker")
        stop = asyncio.Event()
        with self.assertRaisesRegex(RuntimeError, "component_stopped"):
            await asyncio.wait_for(supervise(c, stop), 3)
        self.assertTrue(stop.is_set())
        self.assertTrue(c.web_server.should_exit)
        self.assertIn("bot.shutdown", trace)

    async def test_legacy_runner_refuses_cutover_database_before_bot_start(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "legacy.db"
            db = Database(path)
            await db.init()
            await CoreStore(path).init()
            await RouteStore(path).init()
            await GateBTargetStore(path).init()
            with patch(
                "app.main.build_application",
                side_effect=AssertionError("must not start Bot or send"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "legacy_runner_denied_on_v11_database"
                ):
                    await _serve_locked(SimpleNamespace(database_path=path))

    async def test_enabled_runner_requires_explicit_operator_optin(self):
        with patch.dict(os.environ, {"SEEKPULSE_V11_ENABLE": ""}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "not_explicitly_enabled"):
                main(["--run"])

    async def test_telegram_session_has_its_own_lock_across_db_paths(self):
        with TemporaryDirectory() as td:
            session = Path(td) / "user.session"
            session.write_bytes(b"offline-mock-session")
            database = Path(td) / "secondary.sqlite"
            settings = SimpleNamespace(database_path=database)
            with (database_owner_lock(session),
                  patch.dict(os.environ, {"SEEKPULSE_TG_SESSION": str(session)}),
                  patch("app.v11_main.build_components",
                        side_effect=AssertionError("must not build or send"))):
                with self.assertRaisesRegex(RuntimeError, "instance_already_running"):
                    await _run_live(settings)
            with database_owner_lock(database):
                pass

    async def test_noncanonical_or_missing_session_file_is_denied(self):
        with TemporaryDirectory() as td:
            raw = Path(td) / "tg"
            raw.write_bytes(b"offline-session")
            settings = SimpleNamespace(database_path=Path(td) / "bot.sqlite")
            with patch.dict(os.environ, {"SEEKPULSE_TG_SESSION": str(raw)}):
                with self.assertRaisesRegex(RuntimeError, "session_file_invalid"):
                    await _run_live(settings)
            with patch.dict(os.environ, {"SEEKPULSE_TG_SESSION": str(raw) + ".session"}):
                with self.assertRaisesRegex(RuntimeError, "session_file_invalid"):
                    await _run_live(settings)

    async def test_push_resolver_never_reads_bot_token(self):
        with patch.dict(os.environ, {
            "BOT_TOKEN": "not_for_push",
            "SEEKPULSE_PUSH_BARK_PHONE": "barks://api.day.app/demo",
        }, clear=True):
            self.assertIsNone(push_secret("BOT_TOKEN"))
            self.assertEqual(
                push_secret("BARK_PHONE"), "barks://api.day.app/demo"
            )
            self.assertIsNone(push_secret("../.env"))


class LockContracts(unittest.TestCase):
    def test_identical_database_cannot_have_two_owners(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "bot.db"
            with database_owner_lock(p):
                with self.assertRaisesRegex(
                    RuntimeError, "instance_already_running"
                ):
                    with database_owner_lock(p):
                        pass
            with database_owner_lock(p):
                pass


class FakeTG:
    def __init__(self, now):
        self.posts = [self.post(100, now)]
        self.now = now

    @staticmethod
    def post(message_id, dt, raw=None):
        return SimpleNamespace(
            id=message_id,
            date=dt,
            raw_text=raw or f"DMIT\nhttps://www.nodeseek.com/post-{message_id}-1",
            entities=[],
        )

    async def is_user_authorized(self):
        return True

    async def get_messages(self, _channel, *, limit):
        return self.posts[-limit:]

    async def iter_messages(self, _channel, *, min_id, reverse, limit):
        for item in self.posts:
            if item.id > min_id:
                yield item


class FakeRSS:
    def __init__(self, now):
        self.now = now
        self.calls = 0
        self.max_entries_per_feed = 30

    def entry(self, post_id, published_epoch):
        return FeedEntry(
            item_key=f"https://www.nodeseek.com/post-{post_id}-1",
            title="DMIT",
            link=f"https://www.nodeseek.com/post-{post_id}-1",
            summary="restock",
            published_at="unknown",
            source_text="DMIT restock",
            category_slug=None,
            category_name="",
            published_epoch=published_epoch,
        )

    async def fetch(self, _url):
        self.calls += 1
        if self.calls == 1:
            entries = [self.entry(100, self.now)]
        else:
            entries = [
                self.entry(101, self.now - 86400),
                self.entry(102, None),
                self.entry(103, self.now),
            ]
        return FeedFetchResult("NodeSeek", entries)


class StaleSourceContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        self.path = Path(self.folder.name) / "bot.db"
        await Database(self.path).init()
        self.core = CoreStore(self.path)
        await self.core.init()
        self.state = SourceStore(self.path)
        await self.state.init()
        self.now = datetime.now(timezone.utc)
        self.now_sec = int(self.now.timestamp())

    async def _cleanup(self):
        self.folder.cleanup()

    async def test_old_and_unknown_telegram_posts_not_replayed(self):
        await self.state.set_enabled(Source.TELEGRAM, True)
        api = FakeTG(self.now)
        tg = TelegramSource(
            api, self.core, self.state, clock=lambda: self.now,
            max_message_age_seconds=1800,
        )
        self.assertEqual((await tg.sync_once()).outcome, "baseline")
        api.posts.extend([
            api.post(101, self.now - timedelta(hours=24)),
            api.post(102, self.now, "DMIT\nhttps://www.nodeseek.com/post-102-1"),
            SimpleNamespace(
                id=103, raw_text="https://www.nodeseek.com/post-103-1",
                entities=[], date=None,
            ),
        ])
        result = await tg.sync_once()
        self.assertEqual(result.outcome, "ok")
        self.assertIsNone(await self.core.get_post(101))
        self.assertIsNotNone(await self.core.get_post(102))
        self.assertIsNone(await self.core.get_post(103))
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 103)
        self.assertEqual(
            (await self.state.status(Source.TELEGRAM)).gap_code,
            "tg_unrecognized_message",
        )

    async def test_rss_requires_trustworthy_published_date_in_v11(self):
        rss = RSSSource(
            FakeRSS(self.now_sec), self.core, self.state,
            clock=lambda: self.now, max_entry_age_seconds=1800,
        )
        self.assertEqual((await rss.poll_once()).outcome, "baseline")
        report = await rss.poll_once()
        self.assertEqual(report.outcome, "ok")
        self.assertEqual(report.observed, 1)
        self.assertIsNone(await self.core.get_post(101))
        self.assertIsNone(await self.core.get_post(102))
        self.assertIsNotNone(await self.core.get_post(103))
        self.assertIsNotNone((await self.state.status(Source.RSS)).gap_code)


if __name__ == "__main__":
    unittest.main()
