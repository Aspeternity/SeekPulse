"""Gate B: durable new-observation -> S4 route -> S2 task handoff.

Never invoked by legacy app.main. Prime explicitly establishes a baseline and
requires a quiet legacy handoff; the V1.1 runner refuses an unprimed database.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import aiosqlite

from app.delivery import CoreStore
from app.route_store import RouteStore
from app.routing import enqueue_route


class ObservationDispatcher:
    def __init__(
        self, path: Path, core: CoreStore, routes: RouteStore,
        *, clock: Callable[[], int] | None = None,
        ttl_seconds: int = 1800, batch_size: int = 50,
    ):
        if (type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 86400
                or type(batch_size) is not int or not 1 <= batch_size <= 200):
            raise ValueError("invalid dispatch limits")
        self.path = Path(path)
        self.core, self.routes = core, routes
        self.clock = clock or (lambda: int(time.time()))
        self.ttl_seconds, self.batch_size = ttl_seconds, batch_size
        self._lock = asyncio.Lock()

    def _now(self) -> int:
        value = self.clock()
        if type(value) is not int or value < 0:
            raise ValueError("UTC clock must return nonnegative integer seconds")
        return value

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS gate_b_dispatch_state (
                     singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                     last_observation_id INTEGER NOT NULL
                         CHECK(last_observation_id >= 0),
                     primed_at INTEGER NOT NULL CHECK(primed_at >= 0)
                   )"""
            )
            await db.commit()

    async def cursor(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT last_observation_id FROM gate_b_dispatch_state WHERE singleton=1"
            )).fetchone()
        if row is None:
            raise RuntimeError("gate_b_prime_required")
        return int(row[0])

    async def prime(self) -> int:
        """Explicit cutover watermark. NEVER create tasks from old observations.

        Operator must independently ensure old instance stopped; an initial
        nonterminal S2 queue is a hard blocker rather than a replay hazard.
        """
        async with self._lock:
            async with aiosqlite.connect(self.path, timeout=5.0) as db:
                await db.execute("PRAGMA busy_timeout=5000")
                await db.execute("BEGIN IMMEDIATE")
                try:
                    existing = await (await db.execute(
                        """SELECT last_observation_id FROM gate_b_dispatch_state
                           WHERE singleton=1"""
                    )).fetchone()
                    if existing:
                        await db.commit()
                        return int(existing[0])
                    waiting = await (await db.execute(
                        """SELECT 1 FROM delivery_tasks
                           WHERE status IN ('pending','leased','retry_wait')
                           LIMIT 1"""
                    )).fetchone()
                    if waiting:
                        raise RuntimeError("existing_unresolved_queue")
                    row = await (await db.execute(
                        "SELECT COALESCE(MAX(id),0) FROM source_observations"
                    )).fetchone()
                    watermark = int(row[0])
                    await db.execute(
                        """INSERT INTO gate_b_dispatch_state
                           (singleton,last_observation_id,primed_at)
                           VALUES (1,?,?)""",
                        (watermark, self._now()),
                    )
                    await db.commit()
                    return watermark
                except BaseException:
                    await db.rollback()
                    raise

    async def _advance(self, before: int, after: int) -> None:
        async with aiosqlite.connect(self.path, timeout=5.0) as db:
            cursor = await db.execute(
                """UPDATE gate_b_dispatch_state
                   SET last_observation_id=?
                   WHERE singleton=1 AND last_observation_id=?""",
                (after, before),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                raise RuntimeError("dispatch_cursor_conflict")
            await db.commit()

    async def run_once(self) -> int:
        """Process no more than batch_size committed observations per cycle.

        A partial failure leaves the cursor at the previous event, so a restart
        replays its user routing without duplicating unique S2 target tasks.
        """
        async with self._lock:
            previous = await self.cursor()
            async with aiosqlite.connect(self.path) as db:
                rows = await (await db.execute(
                    """SELECT id,post_id,observed_at FROM source_observations
                       WHERE id > ? ORDER BY id ASC LIMIT ?""",
                    (previous, self.batch_size),
                )).fetchall()
                users = await (await db.execute(
                    """SELECT us.user_id,u.created_at
                       FROM user_settings us JOIN users u ON u.id=us.user_id
                       WHERE us.enabled=1 ORDER BY us.user_id"""
                )).fetchall()

            total = 0
            for event_id, post_id, stamp in rows:
                observed = datetime.fromisoformat(stamp)
                if observed.tzinfo is None:
                    raise ValueError("source observation clock not timezone aware")
                observed_at = observed.astimezone(timezone.utc).timestamp()
                age = self._now() - observed_at
                if age < -60:
                    raise ValueError("source observation is in the future")
                if 0 <= age < self.ttl_seconds:
                    post = await self.core.get_post(post_id)
                    if post is None:
                        raise RuntimeError("source observation missing canonical post")
                    # Always enforce first-source age too; a late second source
                    # may enrich fields, but must not revive a stale old post.
                    first_age = self._now() - post.first_seen_at.timestamp()
                    if -60 <= first_age < self.ttl_seconds:
                        ttl = min(self.ttl_seconds, max(1, int(
                            self.ttl_seconds - max(0, first_age)
                        )))
                        for user_id, user_created in users:
                            joined = datetime.fromisoformat(user_created)
                            if joined.tzinfo is None:
                                raise ValueError("user creation time is invalid")
                            # Newly joined users never receive an older post.
                            if joined.timestamp() > observed_at:
                                continue
                            policy = await self.routes.load_policy(int(user_id))
                            _, added = await enqueue_route(
                                self.core, post, policy,
                                now=self._now(), ttl_seconds=ttl,
                            )
                            total += added
                # Durable cursor commit happens ONLY after all affected user
                # routes have been persisted; crash => replay is idempotent.
                await self._advance(previous, int(event_id))
                previous = int(event_id)
            return total

    async def run_forever(self, stop: asyncio.Event, interval: float = 1.0) -> None:
        if not 0.5 <= interval <= 30:
            raise ValueError("invalid dispatch interval")
        await self.cursor()  # Fail closed if Prime never happened.
        while not stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
