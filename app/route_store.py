"""S4 additive routing metadata over the already approved S1/S2 target IDs.

Legacy targets, users, keywords and delivery_history remain untouched. The
S4 tables store only routing choices, channel labels, safe secret references
and per-target cooldowns; never credentials or notification URLs.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

import aiosqlite

from app.domain import RuleSet
from app.routing import Priority, RuleRoute, UserPolicy


_SECRET_REF = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class Channel(str, Enum):
    TELEGRAM = "telegram"
    BARK = "bark"
    NTFY = "ntfy"


@dataclass(frozen=True, slots=True)
class ChannelTarget:
    target_id: int
    user_id: int
    channel: Channel
    chat_id: int | None
    secret_ref: str | None


def _positive(value: int, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"invalid {label}")


def _clock(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("invalid UTC epoch seconds")


@asynccontextmanager
async def _connection(path: Path):
    async with aiosqlite.connect(path, timeout=5.0) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        yield db


class RouteStore:
    """Use after Database.init() and CoreStore.init() on the same SQLite file."""

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
                CREATE TABLE IF NOT EXISTS s4_user_defaults (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id)
                        ON DELETE CASCADE,
                    override_enabled INTEGER NOT NULL DEFAULT 0
                        CHECK(override_enabled IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS s4_default_targets (
                    user_id INTEGER NOT NULL REFERENCES users(id)
                        ON DELETE CASCADE,
                    target_id INTEGER NOT NULL REFERENCES targets(id)
                        ON DELETE CASCADE,
                    PRIMARY KEY(user_id, target_id)
                );
                CREATE TABLE IF NOT EXISTS s4_rule_options (
                    keyword_id INTEGER PRIMARY KEY REFERENCES keywords(id)
                        ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id)
                        ON DELETE CASCADE,
                    priority INTEGER NOT NULL CHECK(priority IN (0, 1)),
                    override_enabled INTEGER NOT NULL CHECK(override_enabled IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS s4_rule_targets (
                    keyword_id INTEGER NOT NULL REFERENCES keywords(id)
                        ON DELETE CASCADE,
                    target_id INTEGER NOT NULL REFERENCES targets(id)
                        ON DELETE CASCADE,
                    PRIMARY KEY(keyword_id, target_id)
                );
                CREATE TABLE IF NOT EXISTS s4_target_channels (
                    target_id INTEGER PRIMARY KEY REFERENCES targets(id)
                        ON DELETE CASCADE,
                    channel TEXT NOT NULL
                        CHECK(channel IN ('telegram', 'bark', 'ntfy')),
                    secret_ref TEXT
                );
                CREATE TABLE IF NOT EXISTS s4_target_cooldowns (
                    target_id INTEGER PRIMARY KEY REFERENCES targets(id)
                        ON DELETE CASCADE,
                    available_at INTEGER NOT NULL CHECK(available_at >= 0)
                );
                CREATE TABLE IF NOT EXISTS s4_schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO s4_schema_meta(key, value)
                    VALUES ('routing_schema_version', '1');
                """
            )
            cursor = await db.execute(
                """SELECT value FROM s4_schema_meta
                   WHERE key='routing_schema_version'"""
            )
            row = await cursor.fetchone()
            if row is None or row["value"] != "1":
                raise RuntimeError("unsupported S4 routing schema version")
            await db.commit()

    @staticmethod
    async def _ensure_user(db: aiosqlite.Connection, user_id: int) -> None:
        row = await (await db.execute(
            "SELECT 1 FROM user_settings WHERE user_id=?", (user_id,)
        )).fetchone()
        if row is None:
            raise ValueError("unknown user")

    @staticmethod
    async def _ensure_targets(db: aiosqlite.Connection, user_id: int,
                              ids: Sequence[int]) -> None:
        for target in ids:
            _positive(target, "target ID")
            row = await (await db.execute(
                "SELECT 1 FROM targets WHERE id=? AND user_id=?",
                (target, user_id),
            )).fetchone()
            if row is None:
                raise ValueError("cross-user or unknown target")

    async def set_defaults(self, user_id: int,
                           target_ids: Sequence[int] | None) -> None:
        """None uses all existing legacy enabled targets; empty tuple uses none."""
        _positive(user_id, "user ID")
        selected = None if target_ids is None else sorted(set(target_ids))
        async with self._write() as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._ensure_user(db, user_id)
            if selected is not None:
                await self._ensure_targets(db, user_id, selected)
            await db.execute(
                "DELETE FROM s4_default_targets WHERE user_id=?", (user_id,)
            )
            await db.execute(
                """INSERT INTO s4_user_defaults(user_id,override_enabled)
                   VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET
                   override_enabled=excluded.override_enabled""",
                (user_id, int(selected is not None)),
            )
            if selected:
                await db.executemany(
                    "INSERT INTO s4_default_targets(user_id,target_id) VALUES (?,?)",
                    [(user_id, target_id) for target_id in selected],
                )
            await db.commit()

    async def set_rule(self, user_id: int, keyword_id: int, *,
                       priority: Priority = Priority.NORMAL,
                       override_targets: Sequence[int] | None = None) -> None:
        _positive(user_id, "user ID")
        _positive(keyword_id, "keyword ID")
        if not isinstance(priority, Priority):
            raise ValueError("invalid priority")
        selected = None if override_targets is None else sorted(set(override_targets))
        async with self._write() as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._ensure_user(db, user_id)
            row = await (await db.execute(
                "SELECT 1 FROM keywords WHERE id=? AND user_id=?",
                (keyword_id, user_id),
            )).fetchone()
            if row is None:
                raise ValueError("cross-user or unknown rule")
            if selected is not None:
                await self._ensure_targets(db, user_id, selected)
            await db.execute(
                """INSERT INTO s4_rule_options
                   (keyword_id,user_id,priority,override_enabled)
                   VALUES (?,?,?,?)
                   ON CONFLICT(keyword_id) DO UPDATE SET
                   priority=excluded.priority,
                   override_enabled=excluded.override_enabled""",
                (keyword_id, user_id, int(priority), int(selected is not None)),
            )
            await db.execute(
                "DELETE FROM s4_rule_targets WHERE keyword_id=?", (keyword_id,)
            )
            if selected:
                await db.executemany(
                    "INSERT INTO s4_rule_targets(keyword_id,target_id) VALUES (?,?)",
                    [(keyword_id, target_id) for target_id in selected],
                )
            await db.commit()

    async def bind_channel(self, user_id: int, target_id: int,
                           channel: Channel, secret_ref: str | None = None) -> None:
        """Bind an existing owned target ID; secrets remain outside SQLite.

        Creating generalized non-TG target IDs remains a separately audited
        registration/cutover task; this doesn't synthesize fake chat IDs.
        """
        _positive(user_id, "user ID")
        _positive(target_id, "target ID")
        if not isinstance(channel, Channel):
            raise ValueError("invalid channel")
        if channel is Channel.TELEGRAM:
            if secret_ref is not None:
                raise ValueError("Telegram token is owned by Bot, not a target")
        elif not isinstance(secret_ref, str) or not _SECRET_REF.fullmatch(secret_ref):
            raise ValueError("missing safe secret reference")
        async with self._write() as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._ensure_targets(db, user_id, [target_id])
            await db.execute(
                """INSERT INTO s4_target_channels(target_id,channel,secret_ref)
                   VALUES (?,?,?)
                   ON CONFLICT(target_id) DO UPDATE SET
                   channel=excluded.channel,secret_ref=excluded.secret_ref""",
                (target_id, channel.value, secret_ref),
            )
            await db.commit()

    async def load_policy(self, user_id: int) -> UserPolicy:
        """Read the CURRENT user/rule/target configuration for send-time checks."""
        _positive(user_id, "user ID")
        async with _connection(self.path) as db:
            user = await (await db.execute(
                """SELECT enabled,category_slugs FROM user_settings
                   WHERE user_id=?""", (user_id,)
            )).fetchone()
            if user is None:
                raise ValueError("unknown user")
            targets = await (await db.execute(
                "SELECT id FROM targets WHERE user_id=? AND enabled=1 ORDER BY id",
                (user_id,),
            )).fetchall()
            active = {int(row["id"]) for row in targets}
            override = await (await db.execute(
                "SELECT override_enabled FROM s4_user_defaults WHERE user_id=?",
                (user_id,),
            )).fetchone()
            if override is not None and override["override_enabled"]:
                chosen = await (await db.execute(
                    "SELECT target_id FROM s4_default_targets WHERE user_id=?",
                    (user_id,),
                )).fetchall()
                defaults = tuple(sorted(active & {row["target_id"] for row in chosen}))
            else:
                defaults = tuple(sorted(active))

            blockers = await (await db.execute(
                "SELECT normalized_keyword FROM block_keywords WHERE user_id=?",
                (user_id,),
            )).fetchall()
            block_terms = tuple(row["normalized_keyword"] for row in blockers)
            categories = frozenset(
                x.strip() for x in user["category_slugs"].split(",") if x.strip()
            )

            rules = await (await db.execute(
                """SELECT k.id,k.required_keywords,k.normalized_keyword,k.enabled,
                          COALESCE(o.priority,0) AS priority,
                          COALESCE(o.override_enabled,0) AS override_enabled
                   FROM keywords k LEFT JOIN s4_rule_options o
                     ON o.keyword_id=k.id AND o.user_id=k.user_id
                   WHERE k.user_id=? ORDER BY k.id""", (user_id,),
            )).fetchall()
            bindings = []
            for row in rules:
                terms = tuple(
                    term.strip() for term in
                    (row["required_keywords"] or row["normalized_keyword"]).split(",")
                    if term.strip()
                )
                if not terms:
                    # A broken stored rule may not bypass the keyword guard.
                    raise ValueError("invalid stored rule")
                selected = None
                if row["override_enabled"]:
                    own = await (await db.execute(
                        "SELECT target_id FROM s4_rule_targets WHERE keyword_id=?",
                        (row["id"],),
                    )).fetchall()
                    selected = tuple(sorted(active & {t["target_id"] for t in own}))
                bindings.append(RuleRoute(
                    keyword_id=row["id"],
                    rules=RuleSet(
                        clauses=(terms,), blocked=block_terms,
                        allowed_categories=categories,
                    ),
                    priority=Priority(row["priority"]),
                    override_targets=selected,
                    enabled=bool(row["enabled"]),
                ))
        return UserPolicy(user_id, defaults, tuple(bindings), bool(user["enabled"]))

    async def channel_for(self, user_id: int, target_id: int) -> ChannelTarget | None:
        _positive(user_id, "user ID")
        _positive(target_id, "target ID")
        async with _connection(self.path) as db:
            row = await (await db.execute(
                """SELECT t.id,t.user_id,t.chat_id,t.enabled,
                          c.channel,c.secret_ref
                   FROM targets t LEFT JOIN s4_target_channels c
                     ON c.target_id=t.id
                   WHERE t.id=? AND t.user_id=?""",
                (target_id, user_id),
            )).fetchone()
        if row is None or not row["enabled"]:
            return None
        channel = Channel(row["channel"] or Channel.TELEGRAM.value)
        async with _connection(self.path) as db:
            mode = await (await db.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table' AND name='gate_b_schema_meta'"""
            )).fetchone()
        if mode is not None:
            # Enforce actual channel identity after the versioned Gate B migration;
            # the previous offline S4 prototype allowed reusing TG chat IDs.
            if ((channel is Channel.TELEGRAM) != (row["chat_id"] is not None)):
                return None
        return ChannelTarget(
            target_id, user_id, channel,
            row["chat_id"] if channel is Channel.TELEGRAM else None,
            row["secret_ref"] if channel is not Channel.TELEGRAM else None,
        )

    async def blocked_targets(self, *, now: int) -> set[int]:
        _clock(now)
        async with _connection(self.path) as db:
            rows = await (await db.execute(
                """SELECT target_id FROM s4_target_cooldowns
                   WHERE available_at > ?""", (now,),
            )).fetchall()
        return {int(row["target_id"]) for row in rows}

    async def extend_cooldown(self, target_id: int, *, until: int) -> None:
        _positive(target_id, "target ID")
        _clock(until)
        async with self._write() as db:
            await db.execute(
                """INSERT INTO s4_target_cooldowns(target_id,available_at)
                   VALUES (?,?) ON CONFLICT(target_id) DO UPDATE SET
                   available_at=MAX(available_at,excluded.available_at)""",
                (target_id, until),
            )
            await db.commit()
