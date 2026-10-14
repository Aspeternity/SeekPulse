"""S1 real upstream FeedPoller characterization with mocked RSS and Bot.

The original business code executes against fresh temporary SQLite databases.
No HTTP, Telegram token, session, persistent user database, or real push occurs.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from telegram.error import Forbidden

from app.config import Settings
from app.db import Database
from app.poller import FeedPoller
from app.rss import FeedEntry, FeedFetchResult


def entry(item: str, title: str, category: str | None = "trade") -> FeedEntry:
    labels = {"trade": "交易", "tech": "技术"}
    return FeedEntry(
        item_key=item,
        title=title,
        link="https://example.invalid/" + item,
        summary="",
        published_at="2024-10-02 10:00",
        source_text=title.lower(),
        category_slug=category,
        category_name=labels.get(category, "未分类"),
    )


class UpstreamPollerContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = TemporaryDirectory(prefix="seekpulse-poller-s1-")
        self.addAsyncCleanup(self._cleanup)
        path = Path(self.temp_dir.name) / "fresh.db"
        self.db = Database(path)
        await self.db.init()
        self.settings = Settings(
            bot_token="dummy-token-never-used",
            database_path=path,
            rss_url="https://example.invalid/rss",
            max_keywords_per_user=50,
            max_targets_per_user=10,
            history_limit=10,
            poll_interval_seconds=10,
            http_timeout_seconds=2,
            max_entries_per_feed=20,
            mark_as_read_on_first_poll=True,
            disable_web_page_preview=True,
            log_level="ERROR",
            allowed_user_ids=(),
        )
        self.poller = FeedPoller(self.settings, self.db)
        self.bot = SimpleNamespace(send_message=AsyncMock())

    async def _cleanup(self):
        self.temp_dir.cleanup()

    async def user(self, tg_user_id: int, chat_id: int, *, initialized: bool = True):
        user = await self.db.ensure_user_profile(
            tg_user_id=tg_user_id,
            chat_id=chat_id,
            username=None,
            first_name="S1",
            chat_title=None,
            chat_type="private",
        )
        if initialized:
            await self.db.set_user_initialized(user.id)
        return user

    async def keyword(self, tg_id: int, word: str, terms=None):
        _added, record = await self.db.add_keyword(tg_id, word, required_terms=terms)
        return record

    async def poll(self, entries):
        self.poller.feed_client.fetch = AsyncMock(
            return_value=FeedFetchResult(feed_title="Isolated RSS", entries=entries)
        )
        await self.poller.run_once(self.bot)

    async def test_initialization_marks_existing_items_read_without_backfill(self):
        user = await self.user(101, 1001, initialized=False)
        await self.keyword(101, "dmit")
        await self.poll([entry("old", "DMIT old")])
        self.bot.send_message.assert_not_called()
        self.assertTrue(await self.db.is_delivered(user.id, "old"))
        self.assertEqual(await self.db.list_history_by_tg_user(101, 5), [])
        state = await self.db.get_user_settings_by_tg_user(101)
        self.assertTrue(state.initialized)
        await self.poll([entry("new", "DMIT new")])
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertTrue(await self.db.is_delivered(user.id, "new"))

    async def test_or_keywords_and_and_combo_generate_one_user_post_notification(self):
        user = await self.user(101, 1001)
        await self.keyword(101, "DMIT")
        await self.keyword(101, "oracle")
        await self.keyword(101, "DMIT + 补货", terms=["DMIT", "补货"])
        await self.poll([entry("match", "DMIT Oracle 补货")])
        self.assertEqual(self.bot.send_message.await_count, 1)
        sent_text = self.bot.send_message.call_args.kwargs["text"]
        self.assertIn("DMIT", sent_text)
        self.assertIn("oracle", sent_text)
        self.assertIn("补货", sent_text)
        self.assertTrue(await self.db.is_delivered(user.id, "match"))
        counts = {k.normalized_keyword: k.hit_count
                  for k in await self.db.list_keywords_by_tg_user(101)}
        self.assertEqual(counts, {"dmit": 1, "oracle": 1, "dmit + 补货": 1})

    async def test_block_keywords_take_precedence_over_matching_rules(self):
        user = await self.user(101, 1001)
        await self.keyword(101, "DMIT")
        created, _ = await self.db.add_block_keyword(101, "求购")
        self.assertTrue(created)
        await self.poll([entry("blocked", "DMIT 求购")])
        self.bot.send_message.assert_not_called()
        self.assertTrue(await self.db.is_delivered(user.id, "blocked"))
        self.assertEqual(await self.db.list_history_by_tg_user(101, 10), [])
        self.assertEqual((await self.db.list_block_keywords_by_tg_user(101))[0].hit_count, 1)
        self.assertEqual((await self.db.list_keywords_by_tg_user(101))[0].hit_count, 0)

    async def test_category_filter_prevents_wrong_or_unknown_category_delivery(self):
        user = await self.user(101, 1001)
        await self.keyword(101, "DMIT")
        await self.db.set_user_categories(101, ["tech"])
        await self.poll([
            entry("trade", "DMIT sale", "trade"),
            entry("unknown", "DMIT unclassified", None),
            entry("tech", "DMIT code", "tech"),
        ])
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertTrue(await self.db.is_delivered(user.id, "tech"))
        self.assertFalse(await self.db.is_delivered(user.id, "trade"))
        self.assertFalse(await self.db.is_delivered(user.id, "unknown"))

    async def test_unrestricted_category_allows_unknown_category_as_legacy_behavior(self):
        user = await self.user(101, 1001)
        await self.keyword(101, "dmit")
        await self.poll([entry("unknown", "DMIT only", None)])
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertTrue(await self.db.is_delivered(user.id, "unknown"))

    async def test_two_users_and_multiple_targets_are_independently_delivered(self):
        a = await self.user(101, 1001)
        b = await self.user(202, 2002)
        await self.keyword(101, "DMIT")
        await self.keyword(202, "dmit")
        await self.db.add_target_by_tg_user(
            101, -1005000, chat_title="Channel", chat_type="channel"
        )
        await self.poll([entry("same", "New DMIT")])
        self.assertEqual(self.bot.send_message.await_count, 3)
        ids = [call.kwargs["chat_id"] for call in self.bot.send_message.await_args_list]
        self.assertCountEqual(ids, [1001, -1005000, 2002])
        self.assertTrue(await self.db.is_delivered(a.id, "same"))
        self.assertTrue(await self.db.is_delivered(b.id, "same"))
        await self.poll([entry("same", "New DMIT")])
        self.assertEqual(self.bot.send_message.await_count, 3)
        self.assertEqual((await self.db.list_keywords_by_tg_user(101))[0].hit_count, 1)
        self.assertEqual((await self.db.list_keywords_by_tg_user(202))[0].hit_count, 1)

    async def test_paused_user_does_not_receive_feed_notifications(self):
        a = await self.user(101, 1001)
        b = await self.user(202, 2002)
        await self.keyword(101, "DMIT")
        await self.keyword(202, "DMIT")
        await self.db.set_user_enabled(101, False)
        await self.poll([entry("sale", "DMIT sale")])
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertEqual(self.bot.send_message.call_args.kwargs["chat_id"], 2002)
        self.assertFalse(await self.db.is_delivered(a.id, "sale"))
        self.assertTrue(await self.db.is_delivered(b.id, "sale"))

    async def test_forbidden_disables_only_the_failed_target(self):
        user = await self.user(101, 1001)
        await self.keyword(101, "DMIT")
        await self.db.add_target_by_tg_user(
            101, -1005000, chat_title="Channel", chat_type="channel"
        )
        self.bot.send_message.side_effect = [Forbidden("no access"), None, None]
        await self.poll([entry("first", "DMIT new")])
        self.assertTrue(await self.db.is_delivered(user.id, "first"))
        targets = await self.db.list_targets_by_tg_user(101)
        self.assertFalse(next(t.enabled for t in targets if t.chat_id == 1001))
        self.assertTrue(next(t.enabled for t in targets if t.chat_id == -1005000))
        await self.poll([entry("second", "DMIT next")])
        self.assertEqual(self.bot.send_message.await_count, 3)
        self.assertEqual(self.bot.send_message.await_args_list[-1].kwargs["chat_id"],
                         -1005000)

    async def test_all_failed_targets_keep_item_eligible_for_next_poll(self):
        user = await self.user(101, 1001)
        await self.keyword(101, "dmit")
        self.bot.send_message.side_effect = RuntimeError("simulated network error")
        with self.assertLogs("app.poller", level="ERROR") as failures:
            await self.poll([entry("retry", "DMIT available")])
            self.assertFalse(await self.db.is_delivered(user.id, "retry"))
            await self.poll([entry("retry", "DMIT available")])
        self.assertEqual(len(failures.output), 2)
        self.assertEqual(self.bot.send_message.await_count, 2)

    async def test_partial_target_failure_is_documented_legacy_limitation(self):
        # S1 records legacy behavior only; S2/S4 must replace this post-wide
        # sent flag with independently durable (user, post, target) tasks.
        user = await self.user(101, 1001)
        await self.keyword(101, "dmit")
        await self.db.add_target_by_tg_user(
            101, -1005000, chat_title="Channel", chat_type="channel"
        )
        self.bot.send_message.side_effect = [None, RuntimeError("target 2 failed")]
        with self.assertLogs("app.poller", level="ERROR") as failures:
            await self.poll([entry("partial", "DMIT partial")])
        self.assertEqual(len(failures.output), 1)
        self.assertTrue(await self.db.is_delivered(user.id, "partial"))
        await self.poll([entry("partial", "DMIT partial")])
        self.assertEqual(self.bot.send_message.await_count, 2)

    async def test_feed_failure_does_not_mark_item_or_send(self):
        user = await self.user(101, 1001)
        await self.keyword(101, "dmit")
        self.poller.feed_client.fetch = AsyncMock(side_effect=TimeoutError("offline"))
        with self.assertLogs("app.poller", level="ERROR"):
            await self.poller.run_once(self.bot)
        self.bot.send_message.assert_not_called()
        self.assertEqual(await self.db.list_history_by_tg_user(101, 10), [])
        self.assertFalse(await self.db.is_delivered(user.id, "new"))

    async def test_no_eligible_polling_users_skips_rss_fetch(self):
        self.poller.feed_client.fetch = AsyncMock()
        await self.poller.run_once(self.bot)
        self.poller.feed_client.fetch.assert_not_called()
        self.bot.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
