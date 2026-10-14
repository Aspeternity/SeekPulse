"""Gate B's versioned push-target identities over the original SQLite schema.

Only explicit V1.1 preparation invokes init(), which changes targets.chat_id
to nullable transactionally. The existing app.main and S5 web_cli DO NOT.
No fake Telegram chat IDs, stored URLs or plaintext push credentials.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from app.route_store import Channel

_REF = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_NAME = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff _.-]{0,63}$")
_VERSION = "1"


def _owner_id(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("invalid owner or target ID")


def _push_channel(value: Channel) -> None:
    if value not in (Channel.BARK, Channel.NTFY):
        raise ValueError("push targets require Bark or ntfy")


class GateBTargetStore:
    """Opt-in migration + push target registration.

    Every transaction uses foreign keys; migration temporarily disables them
    only while rebuilding targets and fully checks all FKs before commit.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = asyncio.Lock()

    @staticmethod
    async def _require_schema(db: aiosqlite.Connection) -> None:
        present = await (await db.execute(
            """SELECT 1 FROM sqlite_master WHERE type='table'
               AND name='gate_b_schema_meta'"""
        )).fetchone()
        if present is None:
            raise ValueError("Gate B schema not initialized")
        row = await (await db.execute(
            "SELECT value FROM gate_b_schema_meta WHERE key='target_schema_version'"
        )).fetchone()
        if row is None or row[0] != _VERSION:
            raise ValueError("unsupported Gate B target schema")
        columns = await (await db.execute("PRAGMA table_info(targets)")).fetchall()
        col = next((r for r in columns if r[1] == "chat_id"), None)
        if col is None or col[3] != 0:
            raise ValueError("Gate B schema is not initialized")

    async def init(self) -> None:
        """Migrate ONLY in an explicitly authorized, isolated V1.1 path.

        The caller must own the process lock, ensure legacy processes stopped,
        and take a verified backup before using this on any real database.
        """
        async with self._lock:
            async with aiosqlite.connect(self.path, timeout=5.0) as db:
                await db.execute("PRAGMA busy_timeout=5000")
                # SQLite foreign_keys must be set outside a transaction.
                await db.execute("PRAGMA foreign_keys=OFF")
                await db.execute("BEGIN IMMEDIATE")
                try:
                    columns = await (await db.execute(
                        "PRAGMA table_info(targets)"
                    )).fetchall()
                    chat = next((r for r in columns if r[1] == "chat_id"), None)
                    if chat is None:
                        raise ValueError("legacy target schema missing")
                    if chat[3] != 0:
                        await db.execute(
                            """CREATE TABLE targets_gate_b_new (
                                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                                 user_id INTEGER NOT NULL
                                    REFERENCES users(id) ON DELETE CASCADE,
                                 chat_id INTEGER,
                                 chat_title TEXT,
                                 chat_type TEXT,
                                 enabled INTEGER NOT NULL DEFAULT 1
                                    CHECK(enabled IN (0,1)),
                                 created_at TEXT NOT NULL,
                                 updated_at TEXT NOT NULL,
                                 UNIQUE(user_id,chat_id),
                                 CHECK(chat_id IS NOT NULL OR chat_type='push')
                               )"""
                        )
                        await db.execute(
                            """INSERT INTO targets_gate_b_new
                               (id,user_id,chat_id,chat_title,chat_type,enabled,
                                created_at,updated_at)
                               SELECT id,user_id,chat_id,chat_title,chat_type,enabled,
                                      created_at,updated_at FROM targets"""
                        )
                        await db.execute("DROP TABLE targets")
                        await db.execute(
                            "ALTER TABLE targets_gate_b_new RENAME TO targets"
                        )
                        await db.execute(
                            "CREATE INDEX idx_targets_user_id ON targets(user_id)"
                        )
                    await db.execute(
                        """CREATE TABLE IF NOT EXISTS gate_b_schema_meta (
                            key TEXT PRIMARY KEY, value TEXT NOT NULL)"""
                    )
                    await db.execute(
                        """INSERT OR IGNORE INTO gate_b_schema_meta(key,value)
                           VALUES ('target_schema_version','1')"""
                    )
                    await self._require_schema(db)
                    violations = await (await db.execute(
                        "PRAGMA foreign_key_check"
                    )).fetchall()
                    if violations:
                        raise ValueError("foreign-key integrity failed")
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
                finally:
                    await db.execute("PRAGMA foreign_keys=ON")

    async def register(
        self, user_id: int, channel: Channel, name: str, secret_ref: str,
    ) -> int:
        """Create one DISABLED push target + S4 binding atomically."""
        _owner_id(user_id)
        _push_channel(channel)
        if not isinstance(name, str) or not _NAME.fullmatch(name.strip()):
            raise ValueError("invalid target label")
        if not isinstance(secret_ref, str) or not _REF.fullmatch(secret_ref):
            raise ValueError("invalid protected reference")
        async with self._lock:
            async with aiosqlite.connect(self.path, timeout=5.0) as db:
                await db.execute("PRAGMA foreign_keys=ON")
                await db.execute("PRAGMA busy_timeout=5000")
                await db.execute("BEGIN IMMEDIATE")
                try:
                    await self._require_schema(db)
                    owner = await (await db.execute(
                        "SELECT 1 FROM user_settings WHERE user_id=?",
                        (user_id,),
                    )).fetchone()
                    if owner is None:
                        raise ValueError("unknown user")
                    count = await (await db.execute(
                        """SELECT COUNT(*) FROM targets
                           WHERE user_id=? AND chat_id IS NULL
                             AND chat_type='push'""", (user_id,),
                    )).fetchone()
                    if count[0] >= 20:
                        raise ValueError("push target limit reached")
                    now = datetime.now(timezone.utc).isoformat()
                    inserted = await db.execute(
                        """INSERT INTO targets
                           (user_id,chat_id,chat_title,chat_type,enabled,
                            created_at,updated_at)
                           VALUES (?,NULL,?,'push',0,?,?)""",
                        (user_id, name.strip(), now, now),
                    )
                    target_id = inserted.lastrowid
                    await db.execute(
                        """INSERT INTO s4_target_channels
                           (target_id,channel,secret_ref) VALUES (?,?,?)""",
                        (target_id, channel.value, secret_ref),
                    )
                    await db.commit()
                    return int(target_id)
                except BaseException:
                    await db.rollback()
                    raise

    async def set_push_enabled(
        self, user_id: int, target_id: int, enabled: bool, resolver=None,
    ) -> bool:
        """Update only an owned push target; validate secret before activation.

        Lookup, configuration validation and state update share one write
        transaction so a simultaneous channel edit cannot change the target.
        """
        _owner_id(user_id)
        _owner_id(target_id)
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        async with self._lock:
            async with aiosqlite.connect(self.path, timeout=5.0) as db:
                await db.execute("PRAGMA foreign_keys=ON")
                await db.execute("PRAGMA busy_timeout=5000")
                await db.execute("BEGIN IMMEDIATE")
                try:
                    await self._require_schema(db)
                    row = await (await db.execute(
                        """SELECT c.channel,c.secret_ref FROM targets t
                           JOIN s4_target_channels c ON c.target_id=t.id
                           WHERE t.id=? AND t.user_id=? AND t.chat_id IS NULL
                             AND t.chat_type='push'""",
                        (target_id, user_id),
                    )).fetchone()
                    if row is None:
                        raise ValueError("unknown or invalid push target")
                    if enabled:
                        channel, secret_ref = row
                        if (channel not in ("bark", "ntfy")
                                or not isinstance(secret_ref, str)
                                or not _REF.fullmatch(secret_ref)
                                or not callable(resolver)):
                            raise ValueError("push target configuration unavailable")
                        from app.notifiers import AppriseNotifier

                        try:
                            AppriseNotifier.validated_url(
                                Channel(channel), resolver(secret_ref)
                            )
                        except ValueError as exc:
                            raise ValueError("invalid protected push config") from exc
                    await db.execute(
                        """UPDATE targets SET enabled=?,updated_at=?
                           WHERE id=? AND user_id=?""",
                        (
                            int(enabled),
                            datetime.now(timezone.utc).isoformat(),
                            target_id, user_id,
                        ),
                    )
                    await db.commit()
                    return True
                except BaseException:
                    await db.rollback()
                    raise

    async def delete_unused(self, user_id: int, target_id: int) -> bool:
        """Permanently delete only a disabled push target with ZERO task history."""
        _owner_id(user_id)
        _owner_id(target_id)
        async with self._lock:
            async with aiosqlite.connect(self.path, timeout=5.0) as db:
                await db.execute("PRAGMA foreign_keys=ON")
                await db.execute("BEGIN IMMEDIATE")
                try:
                    await self._require_schema(db)
                    row = await (await db.execute(
                        """SELECT 1 FROM targets
                           WHERE id=? AND user_id=? AND chat_id IS NULL
                             AND chat_type='push' AND enabled=0""",
                        (target_id, user_id),
                    )).fetchone()
                    if row is None:
                        raise ValueError("target must be owned, push and disabled")
                    used = await (await db.execute(
                        "SELECT 1 FROM delivery_tasks WHERE target_id=? LIMIT 1",
                        (target_id,),
                    )).fetchone()
                    if used:
                        raise ValueError("target has audit history; disable instead")
                    deleted = await db.execute(
                        "DELETE FROM targets WHERE id=? AND user_id=?",
                        (target_id, user_id),
                    )
                    await db.commit()
                    return deleted.rowcount == 1
                except BaseException:
                    await db.rollback()
                    raise

    async def assert_live_safe(self, *, resolver=None) -> None:
        """Refuse legacy prototypes; validate ENABLED push secrets before send."""
        async with aiosqlite.connect(self.path, timeout=5.0) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await self._require_schema(db)
            rows = await (await db.execute(
                """SELECT t.chat_id,t.chat_type,t.enabled,
                          c.channel,c.secret_ref
                   FROM targets t LEFT JOIN s4_target_channels c
                     ON c.target_id=t.id"""
            )).fetchall()
            for chat_id, chat_type, enabled, channel, secret_ref in rows:
                if chat_id is None:
                    if (chat_type != "push" or channel not in ("bark", "ntfy")
                            or not isinstance(secret_ref, str)
                            or not _REF.fullmatch(secret_ref)):
                        raise ValueError("unsafe push target")
                    if enabled and resolver is not None:
                        from app.notifiers import AppriseNotifier

                        raw = resolver(secret_ref)
                        try:
                            AppriseNotifier.validated_url(Channel(channel), raw)
                        except ValueError as exc:
                            raise ValueError(
                                "enabled push target has no valid protected secret"
                            ) from exc
                elif channel not in (None, "telegram"):
                    raise ValueError("legacy Telegram ID reused as push target")
            broken = await (await db.execute(
                "PRAGMA foreign_key_check"
            )).fetchone()
            if broken:
                raise ValueError("invalid target foreign keys")
