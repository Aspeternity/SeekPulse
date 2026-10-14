"""S1 original SQLite user/rule/target persistence regression.

Every test creates a separate private temporary SQLite database. No real bot,
Telegram session, external URL, or user's application database is accessed.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db import Database


class UpstreamDatabaseContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = TemporaryDirectory(prefix="seekpulse-s1-")
        self.addAsyncCleanup(self._cleanup)
        self.path = Path(self.temp_dir.name) / "isolated.db"
        self.db = Database(self.path)
        await self.db.init()

    async def _cleanup(self):
        self.temp_dir.cleanup()

    async def _user(self, tg_id: int, chat_id: int):
        return await self.db.ensure_user_profile(
            tg_user_id=tg_id,
            chat_id=chat_id,
            username=None,
            first_name="Test",
            chat_title=None,
            chat_type="private",
        )

    async def test_new_user_has_one_default_target_but_no_polling_until_keyword(self):
        user = await self._user(101, 1001)
        self.assertEqual(await self.db.get_polling_users(), [])
        targets = await self.db.list_targets_by_tg_user(101)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].user_id, user.id)
        self.assertEqual(targets[0].chat_id, 1001)
        created, _rule = await self.db.add_keyword(101, "dmit")
        self.assertTrue(created)
        self.assertEqual(len(await self.db.get_polling_users()), 1)

    async def test_combinations_are_normalized_deduplicated_per_user(self):
        await self._user(101, 1001)
        first, saved = await self.db.add_keyword(
            101, "DMIT + 补货", required_terms=["DMIT", "补货", "dmit"]
        )
        self.assertTrue(first)
        self.assertEqual(saved.normalized_keyword, "dmit + 补货")
        self.assertEqual(saved.required_keywords, "dmit,补货")
        second, previous = await self.db.add_keyword(
            101, "补货 + DMIT", required_terms=["补货", "dmit"]
        )
        self.assertFalse(second)
        self.assertEqual(previous.id, saved.id)
        self.assertEqual(await self.db.count_keywords_by_tg_user(101), 1)

    async def test_cross_user_keyword_and_target_mutations_are_rejected(self):
        user_a = await self._user(101, 1001)
        await self._user(202, 2002)
        _inserted, a_keyword = await self.db.add_keyword(101, "dmit")
        _inserted, b_keyword = await self.db.add_keyword(202, "dmit")
        a_target = (await self.db.list_targets_by_tg_user(101))[0]
        self.assertNotEqual(a_keyword.id, b_keyword.id)
        self.assertNotEqual(a_keyword.user_id, b_keyword.user_id)
        self.assertFalse(await self.db.set_keyword_enabled(202, a_keyword.id, False))
        self.assertFalse(await self.db.delete_keyword(202, a_keyword.id))
        self.assertFalse(await self.db.delete_target(202, a_target.id))
        self.assertEqual(len(await self.db.list_targets_by_tg_user(101)), 1)
        self.assertEqual(len(await self.db.list_keywords_by_tg_user(101)), 1)
        self.assertEqual(user_a.id, a_target.user_id)

    async def test_multiple_targets_and_duplicate_target_are_isolated_by_user(self):
        await self._user(101, 1001)
        await self._user(202, 2002)
        self.assertFalse(await self.db.add_target_by_tg_user(
            101, 1001, chat_title=None, chat_type="private"
        ))
        self.assertTrue(await self.db.add_target_by_tg_user(
            101, -1005000, chat_title="Channel", chat_type="channel"
        ))
        self.assertTrue(await self.db.add_target_by_tg_user(
            202, -1005000, chat_title="Channel", chat_type="channel"
        ))
        a_targets = await self.db.list_targets_by_tg_user(101)
        b_targets = await self.db.list_targets_by_tg_user(202)
        self.assertEqual({target.chat_id for target in a_targets}, {1001, -1005000})
        self.assertEqual({target.chat_id for target in b_targets}, {2002, -1005000})
        self.assertEqual(await self.db.count_targets_by_tg_user(101), 2)
        self.assertEqual(await self.db.count_targets_by_tg_user(202), 2)

    async def test_pause_keyword_and_disabled_target_remove_polling_user(self):
        user = await self._user(101, 1001)
        _, keyword = await self.db.add_keyword(101, "dmit")
        target = (await self.db.list_targets_by_tg_user(101))[0]
        self.assertEqual(len(await self.db.get_polling_users()), 1)
        self.assertTrue(await self.db.set_user_enabled(101, False))
        self.assertEqual(await self.db.get_polling_users(), [])
        self.assertTrue(await self.db.set_user_enabled(101, True))
        self.assertTrue(await self.db.set_keyword_enabled(101, keyword.id, False))
        self.assertEqual(await self.db.get_polling_users(), [])
        self.assertTrue(await self.db.set_keyword_enabled(101, keyword.id, True))
        self.assertTrue(await self.db.set_target_enabled(user.id, target.id, False))
        self.assertEqual(await self.db.get_polling_users(), [])
        self.assertTrue(await self.db.set_target_enabled(user.id, target.id, True))
        self.assertEqual(len(await self.db.get_polling_users()), 1)

    async def test_delivery_history_is_per_user_and_filters_blocked_items(self):
        user_a = await self._user(101, 1001)
        user_b = await self._user(202, 2002)
        self.assertFalse(await self.db.is_delivered(user_a.id, "post-1"))
        await self.db.mark_delivered(user_a.id, "post-1", title="blocked",
                                     link="https://example.invalid/1",
                                     category_slug="trade",
                                     matched_keywords=["spam"], delivery_status="blocked")
        self.assertTrue(await self.db.is_delivered(user_a.id, "post-1"))
        self.assertFalse(await self.db.is_delivered(user_b.id, "post-1"))
        self.assertEqual(await self.db.list_history_by_tg_user(101, 5), [])
        await self.db.mark_delivered(user_b.id, "post-1", title="sent",
                                     link="https://example.invalid/1",
                                     category_slug="trade",
                                     matched_keywords=["dmit"])
        records = await self.db.list_history_by_tg_user(202, 5)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].item_key, "post-1")
        self.assertEqual(records[0].matched_keywords, "dmit")

    async def test_repeated_delivery_write_is_ignored_by_existing_user_post_unique_key(self):
        user = await self._user(101, 1001)
        values = dict(title="hello", link="https://example.invalid/1",
                      category_slug="tech", matched_keywords=["dmit"])
        await self.db.mark_delivered(user.id, "post-1", **values)
        await self.db.mark_delivered(user.id, "post-1", **values)
        self.assertEqual(len(await self.db.list_history_by_tg_user(101, 10)), 1)

    async def test_database_init_is_idempotent_and_data_survives_reopen(self):
        await self._user(101, 1001)
        created, _rule = await self.db.add_keyword(101, "Oracle")
        self.assertTrue(created)
        another = Database(self.path)
        await another.init()
        self.assertEqual(len(await another.list_keywords_by_tg_user(101)), 1)
        self.assertEqual((await another.list_targets_by_tg_user(101))[0].chat_id, 1001)


if __name__ == "__main__":
    unittest.main()
