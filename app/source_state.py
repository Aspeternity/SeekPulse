"""S3 source checkpoints and health. Additive SQLite state; no network I/O.

This module does not migrate or replay legacy delivery_history. Source cursors
are independent from per-user delivery state and never mean "sent to a user".
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from app.domain import Source, canonical_post_url


_CODE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


@dataclass(frozen=True, slots=True)
class SourceStatus:
    source: Source
    enabled: bool
    initialized: bool
    cursor: int
    last_success_at: int | None
    failures: int
    retry_at: int
    last_error_code: str | None
    gap_code: str | None


def _epoch(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("time must be a nonnegative epoch second integer")


def _source(value: Source) -> Source:
    if not isinstance(value, Source):
        raise ValueError("unsupported source")
    return value


@asynccontextmanager
async def _connection(path: Path):
    async with aiosqlite.connect(path, timeout=5.0) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        yield db


class SourceStore:
    """Use an initialized Database + CoreStore SQLite file.

    The caller must run init() once before using this instance. Writes from
    one instance are serialized; BEGIN IMMEDIATE fences other connections.
    RSS seen IDs and TG history cursor are independent, so one failing source
    cannot reset or advance the other source.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._write_lock = asyncio.Lock()

    @asynccontextmanager
    async def _write(self):
        async with self._write_lock:
            async with _connection(self.path) as db:
                yield db

    async def init(self) -> None:
        async with self._write() as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS s3_source_status (
                    source TEXT PRIMARY KEY CHECK(source IN ('rss', 'telegram')),
                    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
                    initialized INTEGER NOT NULL DEFAULT 0 CHECK(initialized IN (0, 1)),
                    cursor INTEGER NOT NULL DEFAULT 0 CHECK(cursor >= 0),
                    last_success_at INTEGER,
                    failures INTEGER NOT NULL DEFAULT 0 CHECK(failures >= 0),
                    retry_at INTEGER NOT NULL DEFAULT 0 CHECK(retry_at >= 0),
                    last_error_code TEXT,
                    gap_code TEXT
                );
                CREATE TABLE IF NOT EXISTS s3_rss_seen (
                    post_id INTEGER PRIMARY KEY CHECK(post_id > 0),
                    first_seen_at INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO s3_source_status(source, enabled)
                    VALUES ('rss', 1), ('telegram', 0);
                """
            )
            await db.commit()

    async def status(self, source: Source) -> SourceStatus:
        _source(source)
        async with _connection(self.path) as db:
            row = await (await db.execute(
                "SELECT * FROM s3_source_status WHERE source=?", (source.value,)
            )).fetchone()
        if row is None:
            raise RuntimeError("SourceStore.init() is required")
        return SourceStatus(
            source=source, enabled=bool(row["enabled"]),
            initialized=bool(row["initialized"]), cursor=row["cursor"],
            last_success_at=row["last_success_at"], failures=row["failures"],
            retry_at=row["retry_at"], last_error_code=row["last_error_code"],
            gap_code=row["gap_code"],
        )

    async def set_enabled(self, source: Source, enabled: bool) -> None:
        _source(source)
        if type(enabled) is not bool:
            raise ValueError("enabled must be bool")
        async with self._write() as db:
            await db.execute(
                "UPDATE s3_source_status SET enabled=? WHERE source=?",
                (int(enabled), source.value),
            )
            await db.commit()

    async def rss_seen(self, post_id: int) -> bool:
        canonical_post_url(post_id)
        async with _connection(self.path) as db:
            row = await (await db.execute(
                "SELECT 1 FROM s3_rss_seen WHERE post_id=?", (post_id,)
            )).fetchone()
            return row is not None

    async def remember_rss(self, post_id: int, *, now: int) -> bool:
        canonical_post_url(post_id)
        _epoch(now)
        async with self._write() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "INSERT OR IGNORE INTO s3_rss_seen(post_id,first_seen_at) VALUES (?,?)",
                (post_id, now),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def bootstrap_rss(self, post_ids: list[int], *, now: int) -> bool:
        """Mark the initial feed window seen without adding delivery tasks.

        All IDs and the initialized bit commit together. Failure before commit
        leaves the source uninitialized, so the first-run no-backfill policy
        remains effective after a crash.
        """
        _epoch(now)
        for post_id in post_ids:
            canonical_post_url(post_id)
        async with self._write() as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute(
                "SELECT initialized FROM s3_source_status WHERE source='rss'"
            )).fetchone()
            if row is None:
                await db.rollback()
                raise RuntimeError("SourceStore.init() is required")
            if row["initialized"]:
                await db.rollback()
                return False
            await db.executemany(
                "INSERT OR IGNORE INTO s3_rss_seen(post_id, first_seen_at) VALUES (?, ?)",
                [(post_id, now) for post_id in set(post_ids)],
            )
            await db.execute(
                """UPDATE s3_source_status SET initialized=1, last_success_at=?,
                   failures=0, retry_at=0, last_error_code=NULL WHERE source='rss'""",
                (now,),
            )
            await db.commit()
            return True

    async def bootstrap_telegram(self, latest_message_id: int) -> bool:
        """On first connection only, skip old channel history."""
        _epoch(latest_message_id)
        async with self._write() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """UPDATE s3_source_status SET cursor=?, initialized=1
                   WHERE source='telegram' AND initialized=0""",
                (latest_message_id,),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def advance_telegram(self, latest_message_id: int) -> None:
        """Advance ONLY after all fetched history was durably ingested."""
        _epoch(latest_message_id)
        async with self._write() as db:
            await db.execute(
                """UPDATE s3_source_status
                   SET cursor=MAX(cursor, ?) WHERE source='telegram'
                   AND initialized=1""",
                (latest_message_id,),
            )
            await db.commit()

    async def mark_success(self, source: Source, *, now: int) -> None:
        _source(source)
        _epoch(now)
        async with self._write() as db:
            await db.execute(
                """UPDATE s3_source_status SET last_success_at=?, failures=0,
                   retry_at=0, last_error_code=NULL WHERE source=?""",
                (now, source.value),
            )
            await db.commit()

    async def mark_gap(self, source: Source, code: str) -> None:
        _source(source)
        if not _CODE.fullmatch(code):
            raise ValueError("invalid gap code")
        async with self._write() as db:
            await db.execute(
                "UPDATE s3_source_status SET gap_code=? WHERE source=?",
                (code, source.value),
            )
            await db.commit()

    async def acknowledge_gap(self, source: Source) -> None:
        _source(source)
        async with self._write() as db:
            await db.execute(
                "UPDATE s3_source_status SET gap_code=NULL WHERE source=?",
                (source.value,),
            )
            await db.commit()

    async def mark_failure(
        self, source: Source, code: str, *, now: int,
        retry_after_seconds: int = 0,
    ) -> int:
        """Bounded backoff; persist only safe short codes, never exceptions."""
        _source(source)
        _epoch(now)
        if not _CODE.fullmatch(code):
            raise ValueError("invalid error code")
        if type(retry_after_seconds) is not int or not 0 <= retry_after_seconds <= 86400:
            raise ValueError("invalid Retry-After")
        async with self._write() as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute(
                "SELECT failures FROM s3_source_status WHERE source=?",
                (source.value,),
            )).fetchone()
            if row is None:
                await db.rollback()
                raise RuntimeError("SourceStore.init() is required")
            failures = row["failures"] + 1
            delay = min(600, 10 * 2 ** min(failures - 1, 6))
            if code in {"http_403", "auth_required", "backfill_limit"}:
                delay = max(delay, 3600)
            delay = max(delay, retry_after_seconds)
            await db.execute(
                """UPDATE s3_source_status SET failures=?, retry_at=?,
                   last_error_code=? WHERE source=?""",
                (failures, now + delay, code, source.value),
            )
            await db.commit()
            return now + delay
