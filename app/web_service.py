"""S5 administrator Web service facade over existing Bot/S2/S3/S4 stores.

No second keywords/targets table. Every user-owned read/write is scoped to
the configured administrator's Telegram user ID, and the original Bot sees
changes immediately through the same SQLite file.
"""

from __future__ import annotations

import math
import os
import re
import time
from datetime import datetime
from pathlib import Path

import aiosqlite

from app.categories import CATEGORY_LABELS
from app.db import Database, UserSettingsRecord
from app.gate_b_targets import GateBTargetStore
from app.delivery import CoreStore
from app.domain import Source
from app.route_store import Channel, RouteStore
from app.routing import Priority
from app.source_state import SourceStore


class MissingAdminProfile(Exception):
    """The administrator must first use /start with the existing Telegram Bot."""


class WebService:
    def __init__(self, path: Path, admin_tg_id: int):
        if type(admin_tg_id) is not int or admin_tg_id <= 0:
            raise ValueError("invalid administrator Telegram user ID")
        self.path = Path(path)
        self.admin_tg_id = admin_tg_id
        self.db = Database(self.path)
        self.core = CoreStore(self.path)
        self.sources = SourceStore(self.path)
        self.routes = RouteStore(self.path)
        self.push_targets = GateBTargetStore(self.path)

    async def ensure_schema(self) -> None:
        """Idempotent initialization; does not replay or send notifications."""
        await self.db.init()
        await self.core.init()
        await self.sources.init()
        await self.routes.init()

    async def _owner(self) -> UserSettingsRecord:
        user = await self.db.get_user_settings_by_tg_user(self.admin_tg_id)
        if user is None:
            raise MissingAdminProfile("start the Telegram Bot as administrator first")
        return user

    async def rules(self) -> dict:
        owner = await self._owner()
        policy = await self.routes.load_policy(owner.user_id)
        return {
            "owner": owner,
            "keywords": await self.db.list_keywords_by_tg_user(self.admin_tg_id),
            "blocks": await self.db.list_block_keywords_by_tg_user(self.admin_tg_id),
            "routes": {r.keyword_id: r for r in policy.rules},
            "targets": await self.db.list_targets_by_tg_user(
                self.admin_tg_id, include_push=True
            ),
        }

    async def sources_view(self) -> dict:
        await self._owner()
        return {"sources": [
            await self.sources.status(Source.RSS),
            await self.sources.status(Source.TELEGRAM),
        ]}

    async def channels(self) -> dict:
        owner = await self._owner()
        targets = await self.db.list_targets_by_tg_user(
            self.admin_tg_id, include_push=True
        )
        policy = await self.routes.load_policy(owner.user_id)
        result = []
        for item in targets:
            binding = await self.routes.channel_for(owner.user_id, item.id)
            result.append({
                "target": item, "channel": binding.channel.value if binding else "disabled",
                "configured": binding is not None and (
                    binding.channel is Channel.TELEGRAM or bool(binding.secret_ref)
                ),
            })
        async with aiosqlite.connect(self.path) as conn:
            row = await (await conn.execute(
                "SELECT override_enabled FROM s4_user_defaults WHERE user_id=?",
                (owner.user_id,),
            )).fetchone()
        return {
            "targets": result, "defaults": policy.default_targets,
            "default_override": bool(row[0]) if row else False,
        }

    async def dashboard(self) -> dict:
        owner = await self._owner()
        async with aiosqlite.connect(self.path) as conn:
            entries = await (await conn.execute(
                """SELECT status, COUNT(*) AS n
                   FROM delivery_tasks WHERE user_id=? GROUP BY status""",
                (owner.user_id,),
            )).fetchall()
            posts = await (await conn.execute(
                """SELECT COUNT(DISTINCT post_id)
                   FROM delivery_tasks WHERE user_id=?""",
                (owner.user_id,),
            )).fetchone()
            oldest = await (await conn.execute(
                """SELECT MIN(created_at) FROM delivery_tasks
                   WHERE user_id=? AND status IN ('pending','retry_wait')""",
                (owner.user_id,),
            )).fetchone()
            # Only source-observation -> API-accepted latency is measurable.
            # Sample is limited and per-user; never call this mobile delivery.
            samples = await (await conn.execute(
                """SELECT dt.sent_at,
                          (SELECT MIN(so.observed_at) FROM source_observations so
                           WHERE so.post_id=dt.post_id) AS first_seen
                   FROM delivery_tasks dt
                   WHERE dt.user_id=? AND dt.status='sent' AND dt.sent_at IS NOT NULL
                   ORDER BY dt.id DESC LIMIT 200""",
                (owner.user_id,),
            )).fetchall()
        latencies = []
        for sent_at, observed_at in samples:
            try:
                when = datetime.fromisoformat(observed_at)
                if when.tzinfo is None:
                    continue
                diff = round((sent_at - when.timestamp()) * 1000)
                if diff >= 0:
                    latencies.append(diff)
            except (TypeError, ValueError, OverflowError):
                continue
        latencies.sort()

        def percentile(level: float) -> int | None:
            if not latencies:
                return None
            return latencies[max(0, math.ceil(level * len(latencies)) - 1)]

        counts = {name: n for name, n in entries}
        return {
            "count_tasks": sum(counts.values()),
            "count_posts": int(posts[0] or 0),
            "count_sent": counts.get("sent", 0),
            "count_waiting": counts.get("pending", 0) + counts.get("retry_wait", 0),
            "count_failed": counts.get("failed_permanent", 0),
            "oldest_wait_seconds": (
                max(0, int(time.time()) - int(oldest[0])) if oldest[0] is not None else 0
            ),
            "counts": counts,
            "source_api_p50_ms": percentile(0.50),
            "source_api_p95_ms": percentile(0.95),
            "latency_samples": len(latencies),
            "sources": (await self.sources_view())["sources"],
        }

    async def history(self) -> dict:
        owner = await self._owner()
        # SQL LIMIT at the database boundary prevents unbounded memory
        # growth on a 1 GiB VPS; data is strictly administrator-scoped.
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await (await conn.execute(
                """SELECT post_id, target_id, status, priority, attempts,
                          sent_at, last_error_code
                   FROM delivery_tasks WHERE user_id=?
                   ORDER BY id DESC LIMIT 50""",
                (owner.user_id,),
            )).fetchall()
        return {
            "legacy": await self.db.list_history_by_tg_user(self.admin_tg_id, 40),
            "tasks": [dict(row) for row in rows],
        }

    async def settings(self) -> dict:
        owner = await self._owner()
        return {
            "owner": owner,
            "categories": CATEGORY_LABELS,
            "selected_categories": set(owner.category_slugs.split(",")) if owner.category_slugs else set(),
        }

    @staticmethod
    def _keyword(raw: str) -> tuple[str, list[str]]:
        if not isinstance(raw, str):
            raise ValueError("invalid keyword")
        raw = raw.strip()
        if not 1 <= len(raw) <= 100 or "<" in raw or ">" in raw or "," in raw:
            raise ValueError("keyword must be 1..100 characters, no commas or HTML")
        parts = [p.strip() for p in raw.split("+")]
        if len(parts) > 5 or any(not p or len(p) > 50 for p in parts):
            raise ValueError("invalid AND keyword syntax")
        return raw, parts

    async def add_rule(self, keyword: str) -> bool:
        await self._owner()
        raw, terms = self._keyword(keyword)
        # Honor exactly the same keyword-count limit as existing Bot commands.
        limit_raw = os.getenv(
            "MAX_KEYWORDS_PER_USER", os.getenv("MAX_SUBSCRIPTIONS_PER_USER", "50")
        )
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            raise ValueError("invalid keyword limit") from exc
        if not 1 <= limit <= 1000:
            raise ValueError("invalid keyword limit")
        if await self.db.count_keywords_by_tg_user(self.admin_tg_id) >= limit:
            raise ValueError("keyword limit reached")
        created, _ = await self.db.add_keyword(self.admin_tg_id, raw, terms)
        return created

    async def update_rule(self, rule_id: int, enabled: bool) -> bool:
        await self._owner()
        return await self.db.set_keyword_enabled(self.admin_tg_id, rule_id, enabled)

    async def delete_rule(self, rule_id: int) -> bool:
        await self._owner()
        return await self.db.delete_keyword(self.admin_tg_id, rule_id)

    async def add_block(self, text: str) -> bool:
        await self._owner()
        if (not isinstance(text, str) or not 1 <= len(text.strip()) <= 50
                or "<" in text or ">" in text or "," in text):
            raise ValueError("invalid blocked keyword")
        created, _ = await self.db.add_block_keyword(self.admin_tg_id, text.strip())
        return created

    async def delete_block(self, block_id: int) -> bool:
        await self._owner()
        return await self.db.delete_block_keyword(self.admin_tg_id, block_id)

    async def update_rule_route(
        self, rule_id: int, priority: str, override: bool,
        targets: list[int],
    ) -> None:
        owner = await self._owner()
        if priority not in ("normal", "urgent"):
            raise ValueError("invalid priority")
        await self.routes.set_rule(
            owner.user_id, rule_id,
            priority=Priority.URGENT if priority == "urgent" else Priority.NORMAL,
            override_targets=targets if override else None,
        )

    async def update_default_targets(self, targets: list[int] | None) -> None:
        owner = await self._owner()
        await self.routes.set_defaults(owner.user_id, targets)

    async def update_channel(
        self, target_id: int, channel: str, secret_ref: str,
    ) -> None:
        owner = await self._owner()
        try:
            choice = Channel(channel)
        except ValueError as exc:
            raise ValueError("invalid notification channel") from exc
        # Config values must be references only. Never accept a service URL.
        if (choice is not Channel.TELEGRAM
                and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", secret_ref)):
            raise ValueError("notification secret must be configured outside Web")
        async with aiosqlite.connect(self.path) as conn:
            ready = await (await conn.execute(
                """SELECT 1 FROM sqlite_master WHERE type='table'
                   AND name='gate_b_schema_meta'"""
            )).fetchone()
            if ready:
                target = await (await conn.execute(
                    "SELECT chat_id FROM targets WHERE id=? AND user_id=?",
                    (target_id, owner.user_id),
                )).fetchone()
                if target is None:
                    raise ValueError("unknown target")
                if (choice is Channel.TELEGRAM) != (target[0] is not None):
                    raise ValueError("channel identity mismatch")
        await self.routes.bind_channel(
            owner.user_id, target_id, choice,
            None if choice is Channel.TELEGRAM else secret_ref,
        )

    async def add_push_target(
        self, channel: str, name: str, secret_ref: str,
    ) -> int:
        owner = await self._owner()
        try:
            choice = Channel(channel)
        except ValueError as exc:
            raise ValueError("invalid push channel") from exc
        return await self.push_targets.register(
            owner.user_id, choice, name, secret_ref
        )

    async def delete_unused_push_target(self, target_id: int) -> bool:
        owner = await self._owner()
        return await self.push_targets.delete_unused(owner.user_id, target_id)

    async def update_target(self, target_id: int, enabled: bool) -> bool:
        owner = await self._owner()
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT chat_id FROM targets WHERE id=? AND user_id=?",
                (target_id, owner.user_id),
            )).fetchone()
        if row is not None and row[0] is None:
            return await self.push_targets.set_push_enabled(
                owner.user_id, target_id, enabled,
                resolver=lambda reference: os.getenv("SEEKPULSE_PUSH_" + reference),
            )
        return await self.db.set_target_enabled(owner.user_id, target_id, enabled)

    async def set_source(self, source: str, enabled: bool) -> None:
        await self._owner()
        try:
            value = Source(source)
        except ValueError as exc:
            raise ValueError("invalid source") from exc
        await self.sources.set_enabled(value, enabled)

    async def set_categories(self, categories: list[str]) -> None:
        await self._owner()
        if len(categories) != len(set(categories)) or any(c not in CATEGORY_LABELS for c in categories):
            raise ValueError("invalid category")
        ok = await self.db.set_user_categories(self.admin_tg_id, categories)
        if not ok:
            raise MissingAdminProfile()

    async def set_paused(self, enabled: bool) -> None:
        await self._owner()
        if not await self.db.set_user_enabled(self.admin_tg_id, enabled):
            raise MissingAdminProfile()
