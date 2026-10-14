"""S2 durable observations and atomic per-target delivery queue.

All methods perform local SQLite I/O only. No method calls an HTTP API or
waits on Telegram while holding a database transaction. Live integration is
explicitly deferred to the separately authorized S3/S4 stages.
"""

from __future__ import annotations

import asyncio
import re
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Sequence

import aiosqlite

from app.domain import CanonicalPost, Source, SourceObservation, canonical_post_url


class TaskStatus(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    SENT = "sent"
    RETRY_WAIT = "retry_wait"
    FAILED_PERMANENT = "failed_permanent"
    SUPPRESSED = "suppressed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class DeliveryTask:
    id: int
    user_id: int
    post_id: int
    target_id: int
    status: TaskStatus
    priority: int
    attempts: int
    max_attempts: int
    available_at: int
    expires_at: int
    lease_token: str | None
    lease_until: int | None
    created_at: int
    updated_at: int
    sent_at: int | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class RecoveryCounts:
    expired: int
    leases_requeued: int
    leases_exhausted: int


_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


def _positive(name: str, value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _clock(now: int) -> None:
    if type(now) is not int or now < 0:
        raise ValueError("now must be a nonnegative UTC epoch-second integer")


@asynccontextmanager
async def _db(path: Path):
    async with aiosqlite.connect(path, timeout=5.0) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        yield db


class CoreStore:
    """Use with the same SQLite file already initialized by app.db.Database.

    S2 tables are additive: no changes to legacy delivery_history or source
    polling are performed and no legacy sent rows are replayed as new tasks.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        # SQLite permits only one writer. In the one-process service, keep
        # writes serial per CoreStore instance instead of making dozens of
        # BEGIN IMMEDIATE connections compete until busy_timeout expires.
        # DB transactions still fence writers in other connections/processes.
        self._write_lock = asyncio.Lock()

    @asynccontextmanager
    async def _write_db(self):
        async with self._write_lock:
            async with _db(self.path) as db:
                yield db

    async def init(self) -> None:
        async with self._write_db() as db:
            await db.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS canonical_posts (
                    post_id INTEGER PRIMARY KEY CHECK(post_id > 0)
                );

                CREATE TABLE IF NOT EXISTS source_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL CHECK(source IN ('rss','telegram')),
                    event_id TEXT NOT NULL,
                    post_id INTEGER NOT NULL
                        REFERENCES canonical_posts(post_id),
                    observed_at TEXT NOT NULL,
                    title TEXT,
                    summary TEXT,
                    category TEXT,
                    link TEXT,
                    UNIQUE(source, event_id)
                );
                CREATE INDEX IF NOT EXISTS ix_s2_obs_post
                    ON source_observations(post_id, id);

                CREATE TABLE IF NOT EXISTS delivery_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    post_id INTEGER NOT NULL REFERENCES canonical_posts(post_id),
                    target_id INTEGER NOT NULL REFERENCES targets(id),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','leased','sent','retry_wait',
                                         'failed_permanent','suppressed','expired')),
                    priority INTEGER NOT NULL DEFAULT 0
                        CHECK(priority IN (0,1)),
                    attempts INTEGER NOT NULL DEFAULT 0
                        CHECK(attempts >= 0),
                    max_attempts INTEGER NOT NULL DEFAULT 3
                        CHECK(max_attempts > 0),
                    available_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    lease_token TEXT,
                    lease_until INTEGER,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    sent_at INTEGER,
                    last_error_code TEXT,
                    UNIQUE(user_id, post_id, target_id),
                    CHECK(expires_at > created_at),
                    CHECK((status = 'leased') =
                          (lease_token IS NOT NULL AND lease_until IS NOT NULL))
                );
                CREATE INDEX IF NOT EXISTS ix_s2_claim
                    ON delivery_tasks(status, available_at, priority, created_at, id);
                CREATE INDEX IF NOT EXISTS ix_s2_user
                    ON delivery_tasks(user_id, post_id);

                CREATE TABLE IF NOT EXISTS s2_schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO s2_schema_meta(key, value)
                    VALUES ('core_schema_version', '1');
                """
            )
            cursor = await db.execute(
                "SELECT value FROM s2_schema_meta WHERE key='core_schema_version'"
            )
            row = await cursor.fetchone()
            if row is None or row["value"] != "1":
                raise RuntimeError("unsupported S2 core schema version")
            await db.commit()

    async def observe(self, observation: SourceObservation) -> CanonicalPost:
        """Idempotently insert a source event under BEGIN IMMEDIATE."""
        async with self._write_db() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT post_id FROM source_observations WHERE source=? AND event_id=?",
                (observation.source.value, observation.event_id),
            )
            existing = await cursor.fetchone()
            if existing is not None and existing["post_id"] != observation.post_id:
                await db.rollback()
                raise ValueError("source event cannot be reassigned to another post")
            if existing is None:
                await db.execute(
                    "INSERT OR IGNORE INTO canonical_posts(post_id) VALUES (?)",
                    (observation.post_id,),
                )
                await db.execute(
                    """
                    INSERT INTO source_observations
                    (source, event_id, post_id, observed_at, title, summary, category, link)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation.source.value,
                        observation.event_id,
                        observation.post_id,
                        observation.observed_at.isoformat(),
                        observation.title,
                        observation.summary,
                        observation.category,
                        observation.link,
                    ),
                )
            await db.commit()
        result = await self.get_post(observation.post_id)
        if result is None:
            raise RuntimeError("committed post disappeared")
        return result

    async def get_post(self, post_id: int) -> CanonicalPost | None:
        canonical_post_url(post_id)
        async with _db(self.path) as db:
            cursor = await db.execute(
                """SELECT source, event_id, post_id, observed_at,
                          title, summary, category, link
                   FROM source_observations WHERE post_id=? ORDER BY id ASC""",
                (post_id,),
            )
            rows = await cursor.fetchall()
        if not rows:
            return None
        post: CanonicalPost | None = None
        for row in rows:
            obs = SourceObservation(
                source=Source(row["source"]),
                event_id=row["event_id"],
                post_id=row["post_id"],
                observed_at=datetime.fromisoformat(row["observed_at"]),
                title=row["title"],
                summary=row["summary"],
                category=row["category"],
                link=row["link"],
            )
            post = CanonicalPost.from_observation(obs) if post is None else post.enrich(obs)
        return post

    @staticmethod
    def _task(row: aiosqlite.Row) -> DeliveryTask:
        return DeliveryTask(
            id=row["id"], user_id=row["user_id"], post_id=row["post_id"],
            target_id=row["target_id"], status=TaskStatus(row["status"]),
            priority=row["priority"], attempts=row["attempts"],
            max_attempts=row["max_attempts"], available_at=row["available_at"],
            expires_at=row["expires_at"], lease_token=row["lease_token"],
            lease_until=row["lease_until"], created_at=row["created_at"],
            updated_at=row["updated_at"], sent_at=row["sent_at"],
            last_error_code=row["last_error_code"],
        )

    async def enqueue(
        self, user_id: int, post_id: int, target_ids: Sequence[int], *,
        now: int, ttl_seconds: int = 1800, max_attempts: int = 3,
        priority: int = 0,
    ) -> int:
        """Create each user/post/target task exactly once, preserving old states.

        Reject mis-owned targets atomically, and do not enqueue to disabled
        targets or paused users. No send or other network call occurs here.
        """
        _positive("user_id", user_id)
        canonical_post_url(post_id)
        _clock(now)
        _positive("ttl_seconds", ttl_seconds)
        _positive("max_attempts", max_attempts)
        if type(priority) is not int or priority not in (0, 1):
            raise ValueError("priority must be normal=0 or urgent=1")
        targets = sorted(set(target_ids))
        for target_id in targets:
            _positive("target_id", target_id)
        if not targets:
            return 0
        async with self._write_db() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT enabled FROM user_settings WHERE user_id=?", (user_id,)
            )
            user = await cursor.fetchone()
            if user is None:
                await db.rollback()
                raise ValueError("unknown user")
            cursor = await db.execute(
                "SELECT 1 FROM canonical_posts WHERE post_id=?", (post_id,)
            )
            if await cursor.fetchone() is None:
                await db.rollback()
                raise ValueError("post was not observed")
            found = []
            for target_id in targets:
                cursor = await db.execute(
                    "SELECT enabled FROM targets WHERE id=? AND user_id=?",
                    (target_id, user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    await db.rollback()
                    raise ValueError("target does not belong to this user")
                if row["enabled"]:
                    found.append(target_id)
            if not user["enabled"]:
                await db.commit()
                return 0
            inserted = 0
            for target_id in found:
                cursor = await db.execute(
                    """
                    INSERT OR IGNORE INTO delivery_tasks
                    (user_id, post_id, target_id, status, priority,
                     attempts, max_attempts, available_at, expires_at,
                     created_at, updated_at)
                    VALUES (?, ?, ?, 'pending', ?, 0, ?, ?, ?, ?, ?)
                    """,
                    (user_id, post_id, target_id, priority, max_attempts,
                     now, now + ttl_seconds, now, now),
                )
                inserted += cursor.rowcount
            await db.commit()
            return inserted

    @staticmethod
    async def _recover_locked(db: aiosqlite.Connection, now: int) -> RecoveryCounts:
        cursor = await db.execute(
            """
            UPDATE delivery_tasks
            SET status='expired', lease_token=NULL, lease_until=NULL,
                updated_at=?, last_error_code='expired'
            WHERE status IN ('pending', 'retry_wait', 'leased')
              AND expires_at <= ?
            """,
            (now, now),
        )
        expired = cursor.rowcount
        cursor = await db.execute(
            """
            UPDATE delivery_tasks
            SET status='failed_permanent', lease_token=NULL, lease_until=NULL,
                updated_at=?, last_error_code='lease_exhausted'
            WHERE status='leased' AND lease_until <= ?
              AND expires_at > ? AND attempts >= max_attempts
            """,
            (now, now, now),
        )
        exhausted = cursor.rowcount
        cursor = await db.execute(
            """
            UPDATE delivery_tasks
            SET status='retry_wait', lease_token=NULL, lease_until=NULL,
                available_at=?, updated_at=?, last_error_code='lease_lost'
            WHERE status='leased' AND lease_until <= ?
              AND expires_at > ? AND attempts < max_attempts
            """,
            (now, now, now, now),
        )
        return RecoveryCounts(expired, cursor.rowcount, exhausted)

    async def recover(self, *, now: int) -> RecoveryCounts:
        """Recover expired leases/old tasks after restart; no external send."""
        _clock(now)
        async with self._write_db() as db:
            await db.execute("BEGIN IMMEDIATE")
            result = await self._recover_locked(db, now)
            await db.commit()
            return result

    async def claim(self, *, now: int, lease_seconds: int = 30,
                    limit: int = 10) -> list[DeliveryTask]:
        """Atomic fenced lease claims; never wait for HTTP under this lock."""
        _clock(now)
        _positive("lease_seconds", lease_seconds)
        _positive("limit", limit)
        if limit > 100:
            raise ValueError("claim limit must be <=100")
        async with self._write_db() as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._recover_locked(db, now)
            cursor = await db.execute(
                """
                SELECT dt.id FROM delivery_tasks AS dt
                JOIN user_settings AS us ON us.user_id=dt.user_id
                JOIN targets AS t ON t.id=dt.target_id AND t.user_id=dt.user_id
                WHERE dt.status IN ('pending','retry_wait')
                  AND dt.available_at <= ? AND dt.expires_at > ?
                  AND dt.attempts < dt.max_attempts
                  AND us.enabled=1 AND t.enabled=1
                ORDER BY dt.priority DESC, dt.created_at ASC, dt.id ASC
                LIMIT ?
                """,
                (now, now, limit),
            )
            ids = [row["id"] for row in await cursor.fetchall()]
            results: list[DeliveryTask] = []
            for task_id in ids:
                token = secrets.token_hex(16)
                await db.execute(
                    """
                    UPDATE delivery_tasks
                    SET status='leased', lease_token=?, lease_until=?,
                        attempts=attempts+1, updated_at=?
                    WHERE id=? AND status IN ('pending','retry_wait')
                    """,
                    (token, now + lease_seconds, now, task_id),
                )
                cursor = await db.execute(
                    "SELECT * FROM delivery_tasks WHERE id=?", (task_id,)
                )
                results.append(self._task(await cursor.fetchone()))
            await db.commit()
            return results

    async def mark_sent(self, task_id: int, token: str, *, now: int) -> bool:
        _positive("task_id", task_id)
        _clock(now)
        if not token:
            return False
        async with self._write_db() as db:
            cursor = await db.execute(
                """
                UPDATE delivery_tasks
                SET status='sent', lease_token=NULL, lease_until=NULL,
                    sent_at=?, updated_at=?, last_error_code=NULL
                WHERE id=? AND status='leased' AND lease_token=?
                  AND lease_until > ? AND expires_at > ?
                """,
                (now, now, task_id, token, now, now),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def mark_failed(
        self, task_id: int, token: str, *, now: int,
        retryable: bool, error_code: str,
        retry_after_seconds: int = 0, backoff_base: int = 10,
        backoff_cap: int = 600,
    ) -> TaskStatus | None:
        """Fenced completion. Error code is a safe category, NOT an exception."""
        _positive("task_id", task_id)
        _clock(now)
        if not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("error_code must be a safe short category")
        if type(retryable) is not bool:
            raise ValueError("retryable must be boolean")
        if type(retry_after_seconds) is not int or retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be >=0")
        _positive("backoff_base", backoff_base)
        _positive("backoff_cap", backoff_cap)
        if not token:
            return None
        async with self._write_db() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT attempts, max_attempts, expires_at
                FROM delivery_tasks
                WHERE id=? AND status='leased' AND lease_token=?
                  AND lease_until > ? AND expires_at > ?
                """,
                (task_id, token, now, now),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.rollback()
                return None
            if row["attempts"] >= row["max_attempts"] or not retryable:
                status = TaskStatus.FAILED_PERMANENT
                when = now
            else:
                bounded_exp = min(row["attempts"] - 1, 16)
                backoff = min(backoff_cap, backoff_base * 2**bounded_exp)
                when = now + max(backoff, retry_after_seconds)
                status = (TaskStatus.RETRY_WAIT if when < row["expires_at"]
                          else TaskStatus.EXPIRED)
            await db.execute(
                """
                UPDATE delivery_tasks
                SET status=?, available_at=?, lease_token=NULL, lease_until=NULL,
                    updated_at=?, last_error_code=?
                WHERE id=? AND status='leased' AND lease_token=?
                """,
                (status.value, when, now, error_code, task_id, token),
            )
            await db.commit()
            return status

    async def suppress(
        self, user_id: int, *, now: int, post_id: int | None = None,
        target_id: int | None = None,
    ) -> int:
        """Cancel ONLY unclaimed work after rules/targets change.

        Already leased external sends cannot reliably be recalled.
        """
        _positive("user_id", user_id)
        _clock(now)
        clauses = ["user_id=?", "status IN ('pending','retry_wait')"]
        args: list[int] = [user_id]
        if post_id is not None:
            canonical_post_url(post_id)
            clauses.append("post_id=?")
            args.append(post_id)
        if target_id is not None:
            _positive("target_id", target_id)
            clauses.append("target_id=?")
            args.append(target_id)
        sql = (
            "UPDATE delivery_tasks SET status='suppressed', updated_at=?, "
            "last_error_code='rule_suppressed' WHERE " + " AND ".join(clauses)
        )
        async with self._write_db() as db:
            cursor = await db.execute(sql, (now, *args))
            await db.commit()
            return cursor.rowcount

    async def list_tasks(self, user_id: int, post_id: int | None = None
                         ) -> list[DeliveryTask]:
        _positive("user_id", user_id)
        clause = "AND post_id=?" if post_id is not None else ""
        args = [user_id]
        if post_id is not None:
            canonical_post_url(post_id)
            args.append(post_id)
        async with _db(self.path) as db:
            cursor = await db.execute(
                "SELECT * FROM delivery_tasks WHERE user_id=? " +
                clause + " ORDER BY id ASC",
                args,
            )
            return [self._task(row) for row in await cursor.fetchall()]
