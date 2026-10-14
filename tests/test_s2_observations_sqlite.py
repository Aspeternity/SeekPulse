"""S2-02 observed posts in the real SQLite core (all temporary databases)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db import Database
from app.delivery import CoreStore
from app.domain import RuleOutcome, RuleSet, Source, SourceObservation, evaluate_rules


NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def obs(post_id=123, source=Source.RSS, event_id="r1", **parts):
    return SourceObservation(
        post_id=post_id, source=source, event_id=event_id,
        observed_at=parts.pop("observed_at", NOW), **parts,
    )


class DurableObservationContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(prefix="seekpulse-s2-observations-")
        self.addAsyncCleanup(self._cleanup)
        self.file = Path(self.temp.name) / "core.db"
        await Database(self.file).init()
        self.store = CoreStore(self.file)
        await self.store.init()

    async def _cleanup(self):
        self.temp.cleanup()

    async def test_a_later_source_completes_missing_fields_after_reload(self):
        first = await self.store.observe(obs(
            source=Source.TELEGRAM, event_id="t5",
            observed_at=NOW, title="DMIT", category=None, summary=None
        ))
        self.assertIsNone(first.category_slug)
        self.assertEqual(evaluate_rules(
            first, RuleSet(clauses=(("dmit",),), allowed_categories=frozenset({"trade"}))
        ).outcome, RuleOutcome.INSUFFICIENT_DATA)
        await self.store.observe(obs(
            source=Source.RSS, event_id="r5",
            observed_at=NOW + timedelta(seconds=5),
            title="later title", category="交易", summary="补货"
        ))
        reopened = CoreStore(self.file)
        final = await reopened.get_post(123)
        self.assertIsNotNone(final)
        self.assertEqual(final.title, "DMIT")
        self.assertEqual(final.summary, "补货")
        self.assertEqual(final.category_slug, "trade")
        self.assertEqual(final.origin_for("title").source, Source.TELEGRAM)
        self.assertEqual(final.origin_for("category_slug").source, Source.RSS)
        self.assertEqual(final.first_seen_by_source()[Source.RSS], NOW + timedelta(seconds=5))

    async def test_same_source_event_repeat_stays_idempotent(self):
        base = obs(title="Original")
        await self.store.observe(base)
        await self.store.observe(base)
        await self.store.observe(obs(title="Edited but same ID"))
        q = await self.store.get_post(123)
        self.assertEqual(len(q.observations), 1)
        self.assertEqual(q.title, "Original")

    async def test_same_source_event_id_cannot_be_reassigned_to_other_post(self):
        await self.store.observe(obs(post_id=123, event_id="r123"))
        with self.assertRaisesRegex(ValueError, "reassigned"):
            await self.store.observe(obs(post_id=456, event_id="r123"))
        self.assertIsNone(await self.store.get_post(456))

    async def test_concurrent_two_sources_same_post_only_has_two_observations(self):
        sources = [
            obs(source=Source.RSS, event_id="r-2", title="DMIT", category="trade"),
            obs(source=Source.TELEGRAM, event_id="t-2", summary="补货"),
        ]
        await asyncio.gather(*(self.store.observe(s) for s in sources * 5))
        post = await self.store.get_post(123)
        self.assertEqual(len(post.observations), 2)
        self.assertEqual(post.title, "DMIT")
        self.assertEqual(post.summary, "补货")
        self.assertEqual(post.category_slug, "trade")

    async def test_1000_distinct_posts_across_two_sources_remain_unique(self):
        # 1000 distinct post IDs with identical titles, across two observation
        # sources. A modest semaphore tests overlap without connection floods.
        gate = asyncio.Semaphore(8)

        async def insert(one):
            async with gate:
                return await self.store.observe(one)

        records = [
            obs(post_id=i, source=source,
                event_id=f"{source.value}-{i}", title="same title")
            for i in range(1, 1001)
            for source in (Source.RSS, Source.TELEGRAM)
        ]
        await asyncio.gather(*(insert(item) for item in records))
        import aiosqlite
        async with aiosqlite.connect(self.file) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM canonical_posts")
            self.assertEqual((await cursor.fetchone())[0], 1000)
            cursor = await db.execute("SELECT COUNT(*) FROM source_observations")
            self.assertEqual((await cursor.fetchone())[0], 2000)
        for post_id in (1, 50, 500, 1000):
            post = await self.store.get_post(post_id)
            self.assertEqual(len(post.observations), 2)
            self.assertEqual(post.title, "same title")

    async def test_additive_migration_keeps_legacy_tables_and_history(self):
        db = Database(self.file)
        user = await db.ensure_user_profile(101, 1101, None, "A", None, "private")
        await db.mark_delivered(
            user.id, "legacy-post-key", title="old", link="old",
            category_slug=None, matched_keywords=["dmit"],
        )
        self.assertEqual(len(await db.list_history_by_tg_user(101, 5)), 1)
        await self.store.init()
        await self.store.init()
        self.assertEqual(len(await db.list_history_by_tg_user(101, 5)), 1)
        self.assertIsNone(await self.store.get_post(123))
        self.assertEqual(await self.store.list_tasks(user.id), [])


if __name__ == "__main__":
    unittest.main()
