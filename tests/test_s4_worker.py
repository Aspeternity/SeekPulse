"""S4 native TG/Bark/ntfy simulated sends and worker fairness. Zero network."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from telegram.error import Forbidden, RetryAfter, TimedOut

from app.db import Database
from app.delivery import CoreStore, TaskStatus
from app.domain import Source, SourceObservation
from app.notifiers import (
    AppriseNotifier, Notification, SendResult, TelegramNotifier,
)
from app.route_store import Channel, ChannelTarget, RouteStore
from app.routing import Priority
from app.worker import DeliveryWorker

EPOCH = 1000
OBS = datetime(2026, 10, 14, tzinfo=timezone.utc)


def event(post_id, title="DMIT service"):
    return SourceObservation(
        source=Source.RSS, event_id=f"rss-{post_id}",
        post_id=post_id, observed_at=OBS, title=title, summary="",
    )


class Clock:
    def __init__(self, now=EPOCH):
        self.value = now

    def __call__(self):
        return self.value

    def advance(self, delta):
        self.value += delta


class FakeBot:
    def __init__(self):
        self.calls = []
        self.error = None

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(message_id=len(self.calls))


class FakeService:
    def __init__(self, ok=True, status_code=None):
        self.ok, self.status_code = ok, status_code

    def __bool__(self):
        return self.ok


class FakeResult:
    def __init__(self, ok=True, code=None):
        self.ok = ok
        self.service = FakeService(ok, code)

    def __bool__(self):
        return self.ok

    def __iter__(self):
        return iter((self.service,))


class FakeApprise:
    def __init__(self):
        self.urls = []
        self.requests = []
        self.next_result = FakeResult()

    def add(self, url):
        self.urls.append(url)
        return True

    async def async_notify(self, **kwargs):
        self.requests.append(kwargs)
        return self.next_result


class NotifierContracts(unittest.IsolatedAsyncioTestCase):
    async def test_native_telegram_html_is_escaped_and_success_is_api_only(self):
        bot = FakeBot()
        adapter = TelegramNotifier(bot)
        target = ChannelTarget(1, 1, Channel.TELEGRAM, 123456, None)
        message = Notification("<A&B>", "body", "https://www.nodeseek.com/post-42-1")
        result = await adapter.send(target, message)
        self.assertTrue(result.accepted)
        self.assertEqual(bot.calls[0]["parse_mode"], "HTML")
        self.assertIn("&lt;A&amp;B&gt;", bot.calls[0]["text"])
        self.assertEqual(bot.calls[0]["chat_id"], 123456)

    async def test_native_telegram_error_categories(self):
        bot = FakeBot()
        adapter = TelegramNotifier(bot)
        target = ChannelTarget(1, 1, Channel.TELEGRAM, 123, None)
        note = Notification("DMIT", "text", "https://www.nodeseek.com/post-1-1")
        bot.error = RetryAfter(7)
        throttled = await adapter.send(target, note)
        self.assertFalse(throttled.accepted)
        self.assertTrue(throttled.retryable)
        self.assertEqual(throttled.error_code, "http_429")
        self.assertGreaterEqual(throttled.retry_after_seconds, 7)

        bot.error = Forbidden("request rejected")
        denied = await adapter.send(target, note)
        self.assertFalse(denied.retryable)
        self.assertEqual(denied.error_code, "telegram_rejected")
        bot.error = TimedOut()
        self.assertTrue((await adapter.send(target, note)).retryable)

    async def test_apprise_rejects_redirects_private_hosts_and_injected_urls(self):
        allowed = (
            (Channel.BARK, "barks://api.day.app/device-key"),
            (Channel.NTFY, "ntfys://ntfy.sh/topic"),
        )
        for channel, url in allowed:
            with self.subTest(channel=channel):
                safe = AppriseNotifier.validated_url(channel, url)
                self.assertIn("retry=0", safe)
                self.assertIn("redirect=no", safe)

        rejected = (
            (Channel.BARK, "bark://127.0.0.1/secret"),
            (Channel.NTFY, "ntfy://localhost/topic"),
            (Channel.NTFY, "ntfy://ntfy.sh.evil.invalid/topic"),
            (Channel.BARK, "bark://api.day.app:8080/key"),
            (Channel.NTFY, "ntfys://ntfy.sh/topic?redirect=yes"),
            (Channel.NTFY, "ntfy://u:p@ntfy.sh/topic"),
            (Channel.BARK, "http://api.day.app/device-key"),
            (Channel.BARK, "bark://api.day.app/device-key"),  # insecure
            (Channel.NTFY, "ntfy://ntfy.sh/topic"),  # insecure
            (Channel.BARK, "barks://api.day.app/key1/key2"),  # multi-device
            (Channel.NTFY, "ntfys://ntfy.sh/topic1/topic2"),  # multi-topic
            (Channel.NTFY, "ntfys://ntfy.sh/topic%2Fhidden"),  # encoded slash
            (Channel.NTFY, "ntfys://ntfy.sh/../../private"),
        )
        for channel, url in rejected:
            with self.subTest(url=url), self.assertRaises(ValueError):
                AppriseNotifier.validated_url(channel, url)

    async def test_apprise_result_object_and_service_status(self):
        fake = FakeApprise()
        adapter = AppriseNotifier(
            lambda name: "barks://api.day.app/fake-key",
            factory=lambda: fake,
        )
        target = ChannelTarget(1, 1, Channel.BARK, None, "MY_BARK_REF")
        message = Notification("N", "body", "https://www.nodeseek.com/post-1-1")
        self.assertTrue((await adapter.send(target, message)).accepted)
        self.assertEqual(len(fake.requests), 1)
        fake.next_result = FakeResult(False, 403)
        rejected = await adapter.send(target, message)
        self.assertFalse(rejected.retryable)
        fake.next_result = FakeResult(False, 429)
        result = await adapter.send(target, message)
        self.assertTrue(result.retryable)
        self.assertEqual(result.error_code, "http_429")
        fake.next_result = FakeResult(False)
        self.assertTrue((await adapter.send(target, message)).retryable)

    async def test_apprise_denied_destination_never_builds_http_client(self):
        factory_calls = []
        adapter = AppriseNotifier(
            lambda name: "ntfy://127.0.0.1/topic",
            factory=lambda: factory_calls.append(1),
        )
        target = ChannelTarget(1, 1, Channel.NTFY, None, "TOPIC_REF")
        result = await adapter.send(target, Notification("N", "x", "link"))
        self.assertEqual(result.error_code, "push_config_rejected")
        self.assertFalse(result.retryable)
        self.assertEqual(factory_calls, [])

    async def test_sendresult_rejects_credential_in_error_message(self):
        with self.assertRaises(ValueError):
            SendResult.failure("token=abc", retryable=True)


class WorkerContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory(prefix="seekpulse-s4-worker-")
        self.addAsyncCleanup(self._clean)
        self.path = Path(self.folder.name) / "worker.db"
        self.db = Database(self.path)
        await self.db.init()
        self.core = CoreStore(self.path)
        await self.core.init()
        self.routes = RouteStore(self.path)
        await self.routes.init()
        self.user = await self.db.ensure_user_profile(
            101, 1101, None, "A", None, "private"
        )
        await self.db.add_target(self.user.id, 2202, chat_title="B", chat_type="private")
        await self.db.add_target(self.user.id, 3303, chat_title="C", chat_type="private")
        self.ids = [t.id for t in await self.db.list_targets_by_tg_user(101)]
        _, self.dmit = await self.db.add_keyword(101, "dmit")
        self.clock = Clock()
        self.bot = FakeBot()
        self.push = FakeApprise()
        await self.routes.bind_channel(
            self.user.id, self.ids[1], Channel.BARK, "BARK_SECRET"
        )
        await self.routes.bind_channel(
            self.user.id, self.ids[2], Channel.NTFY, "NTFY_SECRET"
        )
        self.apprise = AppriseNotifier(
            lambda ref: {
                "BARK_SECRET": "barks://api.day.app/fake-key",
                "NTFY_SECRET": "ntfys://ntfy.sh/fake-topic",
            }.get(ref),
            factory=lambda: self.push,
        )
        self.worker = DeliveryWorker(
            self.core, self.routes,
            TelegramNotifier(self.bot), self.apprise,
            now=self.clock, parallel=3,
        )
        await self.core.observe(event(100))

    async def _clean(self):
        self.folder.cleanup()

    async def test_same_post_three_channels_are_independent_and_deduplicated(self):
        self.assertEqual(await self.worker.route_post(self.user.id, 100), 3)
        self.assertEqual(await self.worker.route_post(self.user.id, 100), 0)
        report = await self.worker.run_once()
        self.assertEqual(report.claimed, 3)
        self.assertEqual(report.sent, 3)
        self.assertEqual(len(self.bot.calls), 1)
        self.assertEqual(len(self.push.requests), 2)
        self.assertEqual({
            t.status for t in await self.core.list_tasks(self.user.id, 100)
        }, {TaskStatus.SENT})

    async def test_single_channel_failure_does_not_block_other_targets(self):
        self.bot.error = TimedOut()
        await self.worker.route_post(self.user.id, 100)
        r = await self.worker.run_once()
        self.assertEqual(r.claimed, 3)
        self.assertEqual(r.sent, 2)
        self.assertEqual(r.retry_wait, 1)
        tasks = await self.core.list_tasks(self.user.id)
        tg = next(x for x in tasks if x.target_id == self.ids[0])
        self.assertEqual(tg.status, TaskStatus.RETRY_WAIT)
        self.bot.error = None
        self.clock.advance(10)
        r2 = await self.worker.run_once()
        self.assertEqual(r2.sent, 1)
        self.assertEqual(len(self.bot.calls), 2)
        self.assertEqual(len(self.push.requests), 2)

    async def test_telegram_rate_limit_cools_only_its_target(self):
        self.bot.error = RetryAfter(30)
        await self.worker.route_post(self.user.id, 100)
        r = await self.worker.run_once()
        self.assertEqual(r.retry_wait, 1)
        self.assertEqual(r.sent, 2)
        self.assertIn(self.ids[0],
                      await RouteStore(self.path).blocked_targets(now=EPOCH + 10))
        self.bot.error = None
        self.clock.advance(10)
        self.assertEqual((await self.worker.run_once()).claimed, 0)
        self.clock.advance(20)
        self.assertEqual((await self.worker.run_once()).sent, 1)
        self.assertEqual(len(self.push.requests), 2)

    async def test_rule_disabled_after_enqueue_suppresses_leased_task(self):
        await self.worker.route_post(self.user.id, 100)
        await self.db.set_keyword_enabled(101, self.dmit.id, False)
        result = await self.worker.run_once()
        self.assertEqual(result.suppressed, 3)
        self.assertEqual(len(self.bot.calls), 0)
        self.assertEqual(len(self.push.requests), 0)
        statuses = {t.status for t in await self.core.list_tasks(self.user.id)}
        self.assertEqual(statuses, {TaskStatus.SUPPRESSED})

    async def test_explicit_rule_override_removes_old_target_before_send(self):
        await self.worker.route_post(self.user.id, 100)
        await self.routes.set_rule(
            self.user.id, self.dmit.id,
            override_targets=[self.ids[0]],
        )
        result = await self.worker.run_once()
        self.assertEqual(result.sent, 1)
        self.assertEqual(result.suppressed, 2)
        self.assertEqual(len(self.push.requests), 0)

    async def test_repeated_channel_rate_spacing_persists_restart(self):
        await self.worker.route_post(self.user.id, 100)
        await self.worker.run_once()
        await self.core.observe(event(101))
        await self.worker.route_post(self.user.id, 101)
        self.assertEqual((await self.worker.run_once()).claimed, 0)
        self.clock.advance(1)
        r = await self.worker.run_once()
        self.assertEqual(r.sent, 1)  # Telegram; both pushes hold for 2 seconds
        self.clock.advance(1)
        restarted = DeliveryWorker(
            self.core, RouteStore(self.path), TelegramNotifier(self.bot),
            self.apprise, now=self.clock, parallel=3,
        )
        self.assertEqual((await restarted.run_once()).sent, 2)

    async def test_fair_scheduler_normal_progresses_during_urgent_flood(self):
        # Override default for urgent "dmit", normal for "normal", one target.
        _, normal = await self.db.add_keyword(101, "normal")
        await self.routes.set_defaults(self.user.id, [self.ids[0]])
        await self.routes.set_rule(
            self.user.id, self.dmit.id, priority=Priority.URGENT
        )
        scheduler = DeliveryWorker(
            self.core, self.routes, TelegramNotifier(self.bot),
            self.apprise, now=self.clock, parallel=1, normal_every=3,
        )
        for n in range(8):
            await self.core.observe(event(200 + n, title="DMIT offer"))
            await scheduler.route_post(self.user.id, 200 + n)
        for n in range(2):
            await self.core.observe(event(300 + n, title="normal update"))
            await scheduler.route_post(self.user.id, 300 + n)
        sent_ids = []
        for _ in range(6):
            self.assertEqual((await scheduler.run_once()).sent, 1)
            self.clock.advance(2)
            for task in await self.core.list_tasks(self.user.id):
                if task.status is TaskStatus.SENT:
                    sent_ids.append(task.post_id)
        self.assertTrue(any(300 <= x < 302 for x in sent_ids))
        self.assertEqual(len(self.bot.calls), 6)

    async def test_max_one_target_per_batch_even_with_concurrent_tasks(self):
        await self.routes.set_defaults(self.user.id, [self.ids[0]])
        for pid in (101, 102, 103):
            await self.core.observe(event(pid))
            await self.worker.route_post(self.user.id, pid)
        first = await self.worker.run_once()
        self.assertEqual(first.claimed, 1)
        self.assertEqual(first.sent, 1)
        self.clock.advance(1)
        second = await self.worker.run_once()
        self.assertEqual(second.claimed, 1)
        self.assertEqual(len(self.bot.calls), 2)

    async def test_retry_is_bounded_and_expires(self):
        self.bot.error = TimedOut()
        await self.routes.set_defaults(self.user.id, [self.ids[0]])
        await self.worker.route_post(self.user.id, 100, ttl_seconds=12)
        self.assertEqual((await self.worker.run_once()).retry_wait, 1)
        self.clock.advance(10)
        result = await self.worker.run_once()
        self.assertEqual(result.expired, 1)
        tasks = await self.core.list_tasks(self.user.id)
        self.assertEqual(tasks[0].status, TaskStatus.EXPIRED)

    async def test_send_cancellation_keeps_lease_for_recovery(self):
        class HangingBot:
            def __init__(self):
                self.started = asyncio.Event()

            async def send_message(self, **kwargs):
                self.started.set()
                await asyncio.Event().wait()

        hang = HangingBot()
        worker = DeliveryWorker(
            self.core, self.routes, TelegramNotifier(hang),
            self.apprise, now=self.clock, parallel=1,
        )
        await self.routes.set_defaults(self.user.id, [self.ids[0]])
        await worker.route_post(self.user.id, 100)
        task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(hang.started.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((await self.core.list_tasks(self.user.id))[0].status,
                         TaskStatus.LEASED)
        self.clock.advance(31)
        await self.core.recover(now=self.clock())
        self.assertEqual((await self.core.list_tasks(self.user.id))[0].status,
                         TaskStatus.RETRY_WAIT)


if __name__ == "__main__":
    unittest.main()
