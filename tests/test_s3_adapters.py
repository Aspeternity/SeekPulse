"""S3 RSS/TG adapter recovery and cross-source contracts (no real network)."""

from __future__ import annotations

import asyncio
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.db import Database
from app.delivery import CoreStore
from app.domain import RuleOutcome, RuleSet, Source, evaluate_rules
from app.rss import FeedEntry, FeedFetchResult
from app.source_adapters import (
    RSSSource, SourceSupervisor, TelegramSource,
    telegram_observation,
)
from app.source_state import SourceStore


NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


def rss_item(post_id, *, title="DMIT", summary="补货", category="trade",
             summary_known=True, link=None):
    return FeedEntry(
        item_key=str(post_id), title=title,
        link=link if link is not None
        else f"https://www.nodeseek.com/post-{post_id}-1",
        summary=summary, published_at="", source_text=title,
        category_slug=category, category_name="",
        summary_known=summary_known,
    )


def batch(*entries):
    return FeedFetchResult(feed_title="NodeSeek", entries=list(entries))


class FakeFeed:
    def __init__(self, *responses, limit=30):
        self.responses = list(responses)
        self.calls = 0
        self.max_entries_per_feed = limit
        self.called = asyncio.Event()

    async def fetch(self, url):
        self.calls += 1
        self.called.set()
        self.url = url
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def message(message_id, post_id, *, title="DMIT", entity_url=None, raw=None):
    text = raw if raw is not None else (
        f"{title}\nhttps://www.nodeseek.com/post-{post_id}-1"
    )
    entities = ([SimpleNamespace(url=entity_url)] if entity_url else [])
    return SimpleNamespace(id=message_id, raw_text=text, entities=entities)


class FakeTelegram:
    def __init__(self, messages=(), authorized=True):
        self.messages = list(messages)
        self.authorized = authorized
        self.history_calls = 0
        self.baseline_calls = 0
        self.called = asyncio.Event()
        self.auth_called = asyncio.Event()
        self.error = None

    async def is_user_authorized(self):
        self.auth_called.set()
        return self.authorized

    async def get_messages(self, channel, limit):
        self.baseline_calls += 1
        self.called.set()
        assert channel == "nodeseekc" and limit == 1
        return sorted(self.messages, key=lambda item: item.id, reverse=True)[:1]

    async def iter_messages(self, channel, min_id, reverse, limit):
        self.history_calls += 1
        self.called.set()
        assert channel == "nodeseekc" and reverse is True
        if self.error is not None:
            raise self.error
        items = sorted(
            (m for m in self.messages if m.id > min_id),
            key=lambda m: m.id,
        )
        for item in items[:limit]:
            yield item


class HttpError(Exception):
    def __init__(self, status, retry_after=None):
        self.status = status
        self.headers = ({"Retry-After": str(retry_after)}
                        if retry_after is not None else {})


class SourceAdapterContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory(prefix="seekpulse-s3-adapters-")
        self.addAsyncCleanup(self._cleanup)
        self.path = Path(self.directory.name) / "test.db"
        self.db = Database(self.path)
        await self.db.init()
        self.core = CoreStore(self.path)
        await self.core.init()
        self.state = SourceStore(self.path)
        await self.state.init()
        self.clock = Clock()

    async def _cleanup(self):
        self.directory.cleanup()

    def reader(self, *responses, limit=30):
        return RSSSource(
            FakeFeed(*responses, limit=limit),
            self.core, self.state, clock=self.clock,
        )

    async def tg(self, messages=(), limit=500, authorized=True):
        await self.state.set_enabled(Source.TELEGRAM, True)
        client = FakeTelegram(messages, authorized)
        return TelegramSource(
            client, self.core, self.state,
            clock=self.clock, backfill_limit=limit,
        )

    async def test_rss_first_poll_never_backfills_and_restart_is_stable(self):
        rss = self.reader(batch(rss_item(1), rss_item(2)), batch(rss_item(1), rss_item(2)))
        first = await rss.poll_once()
        self.assertEqual(first.outcome, "baseline")
        self.assertIsNone(await self.core.get_post(1))
        self.assertTrue(await self.state.rss_seen(2))
        self.assertEqual((await rss.poll_once()).observed, 0)
        self.assertTrue((await SourceStore(self.path).status(Source.RSS)).initialized)

    async def test_rss_new_post_dedup_and_missing_summary(self):
        feed = FakeFeed(
            batch(rss_item(1)),
            batch(rss_item(1), rss_item(2, summary="", summary_known=False)),
            batch(rss_item(2, summary="late edit")),
        )
        rss = RSSSource(feed, self.core, self.state, clock=self.clock)
        self.assertEqual((await rss.poll_once()).outcome, "baseline")
        self.assertEqual((await rss.poll_once()).observed, 1)
        self.assertIsNone((await self.core.get_post(2)).summary)
        self.assertEqual((await rss.poll_once()).observed, 0)
        self.assertEqual(len((await self.core.get_post(2)).observations), 1)
        self.assertEqual(await self.core.get_post(1), None)

    async def test_rss_feed_403_and_429_are_bounded(self):
        rss = self.reader(HttpError(429, retry_after=300), batch())
        self.assertEqual((await rss.poll_once()).outcome, "error")
        self.assertEqual((await self.state.status(Source.RSS)).retry_at,
                         int(NOW.timestamp()) + 300)
        self.assertEqual((await rss.poll_once()).outcome, "backoff")
        self.assertEqual(rss.feed.calls, 1)
        self.clock.advance(300)
        self.assertEqual((await rss.poll_once()).outcome, "baseline")
        self.assertEqual((await self.state.status(Source.RSS)).failures, 0)

        other = self.reader(HttpError(403))
        self.assertEqual((await other.poll_once()).outcome, "error")
        self.assertEqual((await self.state.status(Source.RSS)).last_error_code,
                         "http_403")
        self.assertGreaterEqual((await self.state.status(Source.RSS)).retry_at,
                                int(self.clock().timestamp()) + 3600)

    async def test_rss_timeout_keeps_baseline_and_source_independent(self):
        rss = self.reader(asyncio.TimeoutError(), batch(rss_item(10)))
        self.assertEqual((await rss.poll_once()).outcome, "error")
        self.assertFalse((await self.state.status(Source.RSS)).initialized)
        self.assertFalse((await self.state.status(Source.TELEGRAM)).initialized)
        self.clock.advance(10)
        self.assertEqual((await rss.poll_once()).outcome, "baseline")
        self.assertIsNone(await self.core.get_post(10))

    async def test_rss_gap_persists_without_claiming_recovered_posts(self):
        rss = self.reader(
            batch(rss_item(1), rss_item(2), rss_item(3)),
            batch(rss_item(4), rss_item(5), rss_item(6)),
            limit=3,
        )
        await rss.poll_once()
        self.assertEqual((await rss.poll_once()).observed, 3)
        self.assertEqual((await self.state.status(Source.RSS)).gap_code,
                         "rss_window_no_overlap")
        self.assertIsNotNone(await self.core.get_post(6))
        self.assertIsNone(await self.core.get_post(1))

    async def test_rss_invalid_entries_skipped_and_canonical_guid_fallback(self):
        valid = rss_item(3, link="", summary="补货")
        valid.item_key = "https://nodeseek.com/post-3-1"
        invalid = rss_item(4, link="https://evil.invalid/post-4-1")
        # If a feed entry has an untrusted URL, do not invent an identity.
        rss = self.reader(batch(), batch(invalid, valid))
        await rss.poll_once()
        result = await rss.poll_once()
        self.assertEqual(result.observed, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(
            (await self.state.status(Source.RSS)).gap_code,
            "rss_unrecognized_entry",
        )
        self.assertIsNone(await self.core.get_post(4))
        self.assertEqual((await self.core.get_post(3)).url,
                         "https://www.nodeseek.com/post-3-1")

    async def test_rss_only_official_https_allowed(self):
        for url in (
            "http://rss.nodeseek.com/",
            "https://rss.nodeseek.com.evil.invalid/",
            "https://rss.nodeseek.com/private",
            "https://u:p@rss.nodeseek.com/",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                RSSSource(FakeFeed(batch()), self.core, self.state, url=url)
        self.assertEqual(self.reader(batch()).url, "https://rss.nodeseek.com/")

    async def test_rss_disabled_does_not_fetch(self):
        rss = self.reader(batch())
        await self.state.set_enabled(Source.RSS, False)
        self.assertEqual((await rss.poll_once()).outcome, "disabled")
        self.assertEqual(rss.feed.calls, 0)

    async def test_rss_ingest_failure_does_not_checkpoint_new_id(self):
        feed = FakeFeed(batch(), batch(rss_item(9)), batch(rss_item(9)))
        rss = RSSSource(feed, self.core, self.state, clock=self.clock)
        await rss.poll_once()
        original_observe = self.core.observe
        attempts = 0

        async def fail_once(item):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("simulated storage failure")
            return await original_observe(item)

        self.core.observe = fail_once
        self.assertEqual((await rss.poll_once()).outcome, "error")
        self.assertFalse(await self.state.rss_seen(9))
        self.clock.advance(10)
        self.assertEqual((await rss.poll_once()).observed, 1)
        self.assertTrue(await self.state.rss_seen(9))

    async def test_telegram_first_login_skips_old_messages(self):
        tg = await self.tg([message(10, 100), message(11, 101)])
        self.assertEqual((await tg.sync_once()).outcome, "baseline")
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 11)
        self.assertIsNone(await self.core.get_post(100))
        tg.client.messages.append(message(12, 102))
        self.assertEqual((await tg.sync_once()).observed, 1)
        self.assertIsNotNone(await self.core.get_post(102))
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 12)

    async def test_live_callback_never_skips_gap_before_reconcile(self):
        tg = await self.tg([message(100, 200)])
        await tg.sync_once()
        self.assertTrue(await tg.on_new_message(message(105, 205)))
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 100)
        tg.client.messages.extend([message(x, x + 100) for x in range(101, 106)])
        result = await tg.sync_once()
        self.assertEqual(result.fetched, 5)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 105)
        for post_id in range(201, 206):
            self.assertIsNotNone(await self.core.get_post(post_id))
        self.assertEqual(len((await self.core.get_post(205)).observations), 1)

    async def test_telegram_session_restart_replays_idempotently(self):
        tg = await self.tg([message(10, 100)])
        await tg.sync_once()
        tg.client.messages.append(message(11, 101))
        await tg.sync_once()
        reopened = TelegramSource(
            FakeTelegram([message(10, 100), message(11, 101), message(12, 102)]),
            CoreStore(self.path), SourceStore(self.path), clock=self.clock,
        )
        self.assertEqual((await reopened.sync_once()).observed, 1)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 12)
        self.assertEqual(len((await self.core.get_post(101)).observations), 1)

    async def test_telegram_backfill_overflow_does_not_advance(self):
        tg = await self.tg([message(10, 100)], limit=2)
        await tg.sync_once()
        tg.client.messages.extend([message(11, 101), message(12, 102), message(13, 103)])
        result = await tg.sync_once()
        self.assertEqual(result.outcome, "gap")
        self.assertEqual(result.fetched, 3)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 10)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).gap_code,
                         "backfill_limit")
        self.clock.advance(3600)
        wider = TelegramSource(tg.client, self.core, self.state, clock=self.clock,
                               backfill_limit=5)
        self.assertEqual((await wider.sync_once()).observed, 3)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 13)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).gap_code,
                         "backfill_limit")

    async def test_telegram_history_error_keeps_cursor_unchanged(self):
        tg = await self.tg([message(50, 500)])
        await tg.sync_once()
        tg.client.messages.append(message(51, 501))
        tg.client.error = TimeoutError("network down")
        self.assertEqual((await tg.sync_once()).outcome, "error")
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 50)
        self.clock.advance(10)
        tg.client.error = None
        self.assertEqual((await tg.sync_once()).observed, 1)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 51)

    async def test_no_session_never_runs_network_history(self):
        tg = await self.tg([message(10, 100)], authorized=False)
        self.assertEqual((await tg.sync_once()).outcome, "auth_required")
        self.assertEqual(tg.client.baseline_calls, 0)
        self.assertEqual(tg.client.history_calls, 0)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).last_error_code,
                         "auth_required")

    async def test_telegram_pause_blocks_live_and_resume_catches_up(self):
        tg = await self.tg([message(10, 100)])
        await tg.sync_once()
        await self.state.set_enabled(Source.TELEGRAM, False)
        self.assertFalse(await tg.on_new_message(message(11, 101)))
        tg.client.messages.append(message(11, 101))
        self.assertEqual((await tg.sync_once()).outcome, "disabled")
        await self.state.set_enabled(Source.TELEGRAM, True)
        self.assertEqual((await tg.sync_once()).observed, 1)
        self.assertIsNotNone(await self.core.get_post(101))

    async def test_unknown_telegram_format_leaves_a_durable_gap_flag(self):
        tg = await self.tg([message(10, 100)])
        await tg.sync_once()
        tg.client.messages.append(
            message(11, 0, raw="https://nodeseek.com.evil.invalid/post-5-1")
        )
        result = await tg.sync_once()
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.observed, 0)
        self.assertEqual((await self.state.status(Source.TELEGRAM)).cursor, 11)
        self.assertEqual(
            (await SourceStore(self.path).status(Source.TELEGRAM)).gap_code,
            "tg_unrecognized_message",
        )
        tg.client.messages.append(message(12, 102))
        self.assertEqual((await tg.sync_once()).observed, 1)
        self.assertEqual(
            (await self.state.status(Source.TELEGRAM)).gap_code,
            "tg_unrecognized_message",
        )

    async def test_telegram_hidden_link_and_untrusted_links(self):
        hidden = message(1, 0, raw="DMIT sale", entity_url="https://nodeseek.com/post-42-1")
        found = telegram_observation(hidden, NOW)
        self.assertEqual(found.post_id, 42)
        self.assertEqual(found.title, "DMIT sale")
        for m in (
            message(2, 0, raw="D", entity_url="https://nodeseek.com.evil.invalid/post-42-1"),
            message(3, 0, raw="foo"),
            message(4, 0, raw="https://nodeseek.com/post-1-1\nhttps://nodeseek.com/post-2-1"),
            message(5, 0, raw="https://nodeseek.com/post-" + "9" * 5000 + "-1"),
        ):
            self.assertIsNone(telegram_observation(m, NOW))
        self.assertIsNone(telegram_observation(message(0, 42), NOW))

    async def test_missing_category_waits_for_rss_enrichment(self):
        tg = await self.tg([message(10, 777)])
        await tg.sync_once()  # baseline only
        await tg.on_new_message(message(11, 501, title="DMIT"))
        initial = await self.core.get_post(501)
        rules = RuleSet(
            clauses=(("dmit", "补货"),),
            allowed_categories=frozenset({"trade"}),
        )
        self.assertEqual(evaluate_rules(initial, rules).outcome,
                         RuleOutcome.INSUFFICIENT_DATA)
        rss = self.reader(batch(), batch(rss_item(501, title="later", summary="补货")))
        await rss.poll_once()
        await rss.poll_once()
        final = await self.core.get_post(501)
        self.assertEqual(final.title, "DMIT")
        self.assertEqual(final.category_slug, "trade")
        self.assertEqual(final.summary, "补货")
        self.assertEqual(evaluate_rules(final, rules).outcome, RuleOutcome.MATCHED)
        self.assertEqual(final.first_seen_by_source()[Source.RSS], NOW)

    async def test_double_source_does_not_create_any_delivery_task(self):
        tg = await self.tg([])
        await tg.sync_once()
        await tg.on_new_message(message(1, 10))
        rss = self.reader(batch(), batch(rss_item(10)))
        await rss.poll_once()
        await rss.poll_once()
        self.assertEqual(len((await self.core.get_post(10)).observations), 2)
        user = await self.db.ensure_user_profile(123, 456, None, "U", None, "private")
        self.assertEqual(await self.core.list_tasks(user.id), [])

    async def test_rss_http_date_retry_after_respected(self):
        future = format_datetime(NOW + timedelta(seconds=450), usegmt=True)
        rss = self.reader(HttpError(429, future), batch())
        self.assertEqual((await rss.poll_once()).outcome, "error")
        self.assertEqual(
            (await self.state.status(Source.RSS)).retry_at,
            int(NOW.timestamp()) + 450,
        )
        self.clock.advance(449)
        self.assertEqual((await rss.poll_once()).outcome, "backoff")
        self.clock.advance(1)
        self.assertEqual((await rss.poll_once()).outcome, "baseline")

    async def test_supervisor_never_attaches_expired_session(self):
        tg = await self.tg([message(1, 10)])
        await tg.sync_once()
        tg.client.auth_called.clear()
        tg.client.authorized = False
        callbacks = []
        tg.client.add_event_handler = lambda *args: callbacks.append(args)
        rss = self.reader(batch())
        stop = asyncio.Event()
        task = asyncio.create_task(SourceSupervisor(rss, tg).run_forever(stop))
        try:
            await asyncio.wait_for(tg.client.auth_called.wait(), timeout=3)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3)
        self.assertEqual(callbacks, [])
        self.assertEqual(
            (await self.state.status(Source.TELEGRAM)).last_error_code,
            "auth_required",
        )

    async def test_sibling_source_runs_when_rss_throws(self):
        tg = await self.tg([message(1, 10)])
        rss = self.reader(TimeoutError("simulated"))
        results = await asyncio.gather(rss.poll_once(), tg.sync_once())
        self.assertEqual(results[0].outcome, "error")
        self.assertEqual(results[1].outcome, "baseline")
        self.assertIsNotNone((await self.state.status(Source.RSS)).last_error_code)
        self.assertIsNone((await self.state.status(Source.TELEGRAM)).last_error_code)

    async def test_supervisor_stops_both_without_cascading_failure(self):
        tg = await self.tg([message(1, 10)])
        rss = self.reader(TimeoutError("simulated"))
        stop = asyncio.Event()
        task = asyncio.create_task(
            SourceSupervisor(rss, tg, rss_interval=10, telegram_interval=10)
            .run_forever(stop)
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(rss.feed.called.wait(), tg.client.called.wait()),
                timeout=3,
            )
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3)
        self.assertEqual(rss.feed.calls, 1)
        self.assertEqual(tg.client.baseline_calls, 1)


if __name__ == "__main__":
    unittest.main()
