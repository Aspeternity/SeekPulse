"""Gate B reliable dispatch; bounded cursor, no backfill and crash replay tests."""

from __future__ import annotations

import asyncio
import sqlite3
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.db import Database
from app.delivery import CoreStore
from app.domain import Source, SourceObservation
from app.gate_b_dispatch import ObservationDispatcher
from app.route_store import RouteStore
from app.source_state import SourceStore


class Clock:
    def __init__(self):
        self.value = int(time.time())

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds

    def observed(self, *, seconds_ago=0):
        return datetime.fromtimestamp(
            self.value - seconds_ago, tz=timezone.utc
        )


class DispatchContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory(prefix="seekpulse-gb-dispatch-")
        self.addAsyncCleanup(self._clean)
        self.path = Path(self.folder.name) / "test.db"
        self.db = Database(self.path)
        await self.db.init()
        self.core = CoreStore(self.path)
        await self.core.init()
        self.states = SourceStore(self.path)
        await self.states.init()
        self.routes = RouteStore(self.path)
        await self.routes.init()
        self.clock = Clock()
        self.admin = await self.db.ensure_user_profile(
            101, 201, None, "Admin", None, "private",
        )
        # The pre-existing user predates the observation watermark.
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE users SET created_at=? WHERE id=?",
                (self.clock.observed(seconds_ago=86400).isoformat(), self.admin.id),
            )
        self.target = (await self.db.list_targets_by_tg_user(101))[0]
        await self.db.add_keyword(101, "DMIT")
        self.dispatch = ObservationDispatcher(
            self.path, self.core, self.routes, clock=self.clock
        )
        await self.dispatch.init()

    async def _clean(self):
        self.folder.cleanup()

    async def _observe(
        self, post_id=100, source=Source.RSS, event_id=None,
        seconds_ago=0, summary="available",
    ):
        return await self.core.observe(SourceObservation(
            source, event_id or f"{source.value}-{post_id}", post_id,
            self.clock.observed(seconds_ago=seconds_ago),
            title="DMIT restock", summary=summary, category="交易",
        ))

    async def test_unprimed_dispatch_fails_closed(self):
        await self._observe()
        with self.assertRaisesRegex(RuntimeError, "prime_required"):
            await self.dispatch.cursor()
        with self.assertRaisesRegex(RuntimeError, "prime_required"):
            await self.dispatch.run_once()
        self.assertEqual(await self.core.list_tasks(self.admin.id), [])

    async def test_explicit_prime_skips_historical_and_routes_only_new(self):
        await self._observe(100)
        self.assertEqual(await self.dispatch.prime(), 1)
        self.assertEqual(await self.dispatch.prime(), 1)
        self.assertEqual(await self.dispatch.run_once(), 0)
        self.assertEqual(await self.core.list_tasks(self.admin.id), [])
        await self._observe(101)
        self.assertEqual(await self.dispatch.run_once(), 1)
        tasks = await self.core.list_tasks(self.admin.id)
        self.assertEqual([t.post_id for t in tasks], [101])
        self.assertEqual(await self.dispatch.cursor(), 2)

    async def test_both_sources_one_post_one_target_unique(self):
        await self.dispatch.prime()
        await self._observe(205)
        self.assertEqual(await self.dispatch.run_once(), 1)
        await self._observe(
            205, source=Source.TELEGRAM, event_id="channel-222",
            summary=None,
        )
        self.assertEqual(await self.dispatch.run_once(), 0)
        self.assertEqual(len(await self.core.list_tasks(self.admin.id)), 1)

    async def test_partial_routing_failure_does_not_advance_cursor(self):
        another = await self.db.ensure_user_profile(
            102, 202, None, "Second", None, "private",
        )
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE users SET created_at=? WHERE id=?",
                (self.clock.observed(seconds_ago=86400).isoformat(), another.id),
            )
        await self.db.add_keyword(102, "DMIT")
        await self.dispatch.prime()
        await self._observe(303)
        original = self.routes.load_policy
        calls = 0

        async def unstable(user_id):
            nonlocal calls
            calls += 1
            if user_id == another.id:
                raise OSError("simulated database busy")
            return await original(user_id)

        with patch.object(self.routes, "load_policy", side_effect=unstable):
            with self.assertRaises(OSError):
                await self.dispatch.run_once()
        self.assertEqual(await self.dispatch.cursor(), 0)
        self.assertEqual(len(await self.core.list_tasks(self.admin.id)), 1)
        self.assertEqual(await self.dispatch.run_once(), 1)
        self.assertEqual(len(await self.core.list_tasks(self.admin.id)), 1)
        self.assertEqual(len(await self.core.list_tasks(another.id)), 1)
        self.assertEqual(await self.dispatch.cursor(), 1)

    async def test_old_post_never_renews_ttl_after_outage(self):
        await self.dispatch.prime()
        await self._observe(301, seconds_ago=3600)
        self.assertEqual(await self.dispatch.run_once(), 0)
        await self._observe(
            301, source=Source.TELEGRAM, event_id="second-301",
        )
        self.assertEqual(await self.dispatch.run_once(), 0)
        self.assertEqual(await self.core.list_tasks(self.admin.id), [])
        self.assertEqual(await self.dispatch.cursor(), 2)

    async def test_wrong_future_clock_blocks_cursor(self):
        await self.dispatch.prime()
        await self._observe(401)
        self.clock.advance(-400)
        with self.assertRaises(ValueError):
            await self.dispatch.run_once()
        self.assertEqual(await self.dispatch.cursor(), 0)
        self.assertEqual(await self.core.list_tasks(self.admin.id), [])

    async def test_old_pending_tasks_block_first_prime(self):
        await self._observe(500)
        await self.core.enqueue(
            self.admin.id, 500, [self.target.id],
            now=self.clock(),
        )
        with self.assertRaisesRegex(RuntimeError, "unresolved_queue"):
            await self.dispatch.prime()
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM gate_b_dispatch_state"
            ).fetchone()[0], 0)

    async def test_user_added_after_observation_gets_no_historical_message(self):
        await self.dispatch.prime()
        await self._observe(601)
        new_user = await self.db.ensure_user_profile(
            103, 203, None, "New", None, "private"
        )
        await self.db.add_keyword(103, "DMIT")
        self.assertEqual(await self.dispatch.run_once(), 1)
        self.assertEqual(await self.core.list_tasks(new_user.id), [])
        self.assertEqual(len(await self.core.list_tasks(self.admin.id)), 1)

    async def test_overlapping_cycles_no_double_enqueue(self):
        await self.dispatch.prime()
        await self._observe(707)
        values = await asyncio.gather(
            self.dispatch.run_once(), self.dispatch.run_once()
        )
        self.assertEqual(sorted(values), [0, 1])
        self.assertEqual(len(await self.core.list_tasks(self.admin.id)), 1)

    async def test_paused_user_does_not_receive_new_tasks(self):
        await self.dispatch.prime()
        await self.db.set_user_enabled(101, False)
        await self._observe(909)
        self.assertEqual(await self.dispatch.run_once(), 0)
        self.assertEqual(await self.core.list_tasks(self.admin.id), [])


if __name__ == "__main__":
    unittest.main()
