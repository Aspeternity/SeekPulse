"""S1 upstream Telegram command behavior with fake Update/Context and temporary DB.

Commands are called as normal Python methods without a Telegram client, token,
network, or real user data. Simulated target permission checks use AsyncMock.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from app.bot import BotHandlers
from app.config import Settings
from app.db import Database


def update(text: str, user_id: int = 101):
    user = SimpleNamespace(
        id=user_id, username="test", first_name="Local",
        full_name="Local Test",
    )
    chat = SimpleNamespace(id=user_id + 1000, type="private", title=None)
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=user, effective_chat=chat,
        effective_message=message, callback_query=None,
    )


class CommandContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(prefix="seekpulse-commands-s1-")
        self.addAsyncCleanup(self._cleanup)
        path = Path(self.temp.name) / "commands.db"
        self.db = Database(path)
        await self.db.init()
        self.settings = Settings(
            bot_token="dummy-test-token",
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
            log_level="WARNING",
            allowed_user_ids=(),
        )
        self.handler = BotHandlers(settings=self.settings, db=self.db)
        self.context = SimpleNamespace(
            user_data={},
            bot=SimpleNamespace(
                get_chat=AsyncMock(),
                get_chat_member=AsyncMock(),
                get_me=AsyncMock(),
            ),
        )

    async def _cleanup(self):
        self.temp.cleanup()

    async def test_addkw_command_creates_independent_or_rules_without_duplicates(self):
        event = update("/addkw DMIT,oracle,dmit")
        await self.handler.addkw(event, self.context)
        rules = await self.db.list_keywords_by_tg_user(101)
        self.assertEqual([x.normalized_keyword for x in rules], ["dmit", "oracle"])
        event.effective_message.reply_text.assert_awaited_once()
        self.assertIn("已添加关键词", event.effective_message.reply_text.call_args.args[0])

    async def test_combo_command_creates_and_terms_not_plain_or(self):
        event = update("/combo DMIT,补货")
        await self.handler.combo(event, self.context)
        rows = await self.db.list_keywords_by_tg_user(101)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].required_keywords, "dmit,补货")
        self.assertEqual(rows[0].normalized_keyword, "dmit + 补货")
        self.assertIn("同时", event.effective_message.reply_text.call_args.args[0])

    async def test_combo_rejects_single_term(self):
        event = update("/combo DMIT")
        await self.handler.combo(event, self.context)
        self.assertEqual(await self.db.list_keywords_by_tg_user(101), [])
        self.assertIn("至少", event.effective_message.reply_text.call_args.args[0])

    async def test_block_command_deduplicates_terms(self):
        event = update("/block 求购,收,求购")
        await self.handler.block(event, self.context)
        rows = await self.db.list_block_keywords_by_tg_user(101)
        self.assertEqual([x.normalized_keyword for x in rows], ["求购", "收"])
        event.effective_message.reply_text.assert_awaited_once()
        self.assertIn("已添加屏蔽词", event.effective_message.reply_text.call_args.args[0])

    async def test_scope_command_applies_alias_and_rejects_unknown_category(self):
        valid = update("/scope tech,交易")
        await self.handler.scope(valid, self.context)
        state = await self.db.get_user_settings_by_tg_user(101)
        self.assertEqual(state.category_slugs, "tech,trade")
        bad = update("/scope 不是版块")
        await self.handler.scope(bad, self.context)
        state = await self.db.get_user_settings_by_tg_user(101)
        self.assertEqual(state.category_slugs, "tech,trade")
        reset = update("/scope all")
        await self.handler.scope(reset, self.context)
        self.assertEqual((await self.db.get_user_settings_by_tg_user(101)).category_slugs, "")

    async def test_pause_and_resume_command_toggle_only_current_user(self):
        first = update("/pause")
        await self.handler.pause(first, self.context)
        self.assertFalse((await self.db.get_user_settings_by_tg_user(101)).enabled)
        second = update("/resume")
        await self.handler.resume(second, self.context)
        self.assertTrue((await self.db.get_user_settings_by_tg_user(101)).enabled)

    async def test_whitelist_rejects_user_before_db_profile_creation(self):
        self.handler = BotHandlers(
            settings=replace(self.settings, allowed_user_ids=(202,)), db=self.db
        )
        event = update("/addkw DMIT", user_id=101)
        await self.handler.addkw(event, self.context)
        self.assertEqual(await self.db.list_keywords_by_tg_user(101), [])
        self.assertEqual(await self.db.list_targets_by_tg_user(101), [])
        self.assertIn("未开放", event.effective_message.reply_text.call_args.args[0])

    async def test_per_user_limit_does_not_affect_another_user(self):
        self.handler = BotHandlers(
            settings=replace(self.settings, max_keywords_per_user=1), db=self.db
        )
        await self.handler.addkw(update("/addkw DMIT,Oracle", user_id=101), self.context)
        await self.handler.addkw(update("/addkw Oracle", user_id=202), self.context)
        self.assertEqual(len(await self.db.list_keywords_by_tg_user(101)), 1)
        self.assertEqual(len(await self.db.list_keywords_by_tg_user(202)), 1)
        self.assertEqual((await self.db.list_keywords_by_tg_user(101))[0].normalized_keyword,
                         "dmit")
        self.assertEqual((await self.db.list_keywords_by_tg_user(202))[0].normalized_keyword,
                         "oracle")

    async def test_keyboard_keyword_entry_uses_same_add_path(self):
        start = update("新建关键词")
        await self.handler.handle_text_message(start, self.context)
        self.assertTrue(self.context.user_data["awaiting_keyword"])
        finish = update("Oracle,DMIT")
        await self.handler.handle_text_message(finish, self.context)
        self.assertFalse(self.context.user_data["awaiting_keyword"])
        self.assertEqual(len(await self.db.list_keywords_by_tg_user(101)), 2)

    async def test_addtarget_rejects_nonadmin_requester_without_bot_network(self):
        self.context.bot.get_chat.return_value = SimpleNamespace(
            type="channel", title="Fake Channel"
        )
        self.context.bot.get_chat_member.return_value = SimpleNamespace(status="member")
        event = update("/addtarget -1009001")
        await self.handler.addtarget(event, self.context)
        self.assertEqual(len(await self.db.list_targets_by_tg_user(101)), 1)
        self.assertIn("不是这个群组或频道的管理员",
                      event.effective_message.reply_text.call_args.args[0])
        self.context.bot.get_me.assert_not_awaited()

    async def test_addtarget_requires_both_requester_and_bot_admin_in_channel(self):
        self.context.bot.get_chat.return_value = SimpleNamespace(
            type="channel", title="Fake Channel"
        )
        self.context.bot.get_chat_member.side_effect = [
            SimpleNamespace(status="administrator"),
            SimpleNamespace(status="member"),
            SimpleNamespace(status="administrator"),
            SimpleNamespace(status="administrator"),
        ]
        self.context.bot.get_me.return_value = SimpleNamespace(id=999)
        denied = update("/addtarget -1009001")
        await self.handler.addtarget(denied, self.context)
        self.assertEqual(len(await self.db.list_targets_by_tg_user(101)), 1)
        allowed = update("/addtarget -1009001")
        await self.handler.addtarget(allowed, self.context)
        self.assertEqual(
            {t.chat_id for t in await self.db.list_targets_by_tg_user(101)},
            {1101, -1009001},
        )


if __name__ == "__main__":
    unittest.main()
