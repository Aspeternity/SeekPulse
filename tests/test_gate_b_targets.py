"""Gate B target migration, Web ownership and non-TG identity tests.

No real keys, API calls, VPS or production SQLite; isolated temp DB only.
"""

from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.db import Database
from app.delivery import CoreStore
from app.domain import Source, SourceObservation
from app.gate_b_targets import GateBTargetStore
from app.route_store import Channel, RouteStore
from app.source_state import SourceStore

try:
    from httpx import ASGITransport, AsyncClient
    from app.web import create_web_app
    from app.web_auth import AdminWebConfig, password_hash
except ModuleNotFoundError:
    AsyncClient = None
    create_web_app = None


class TargetRegistryContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory(prefix="seekpulse-gb-targets-")
        self.addAsyncCleanup(self._cleanup)
        self.path = Path(self.folder.name) / "test.db"
        self.db = Database(self.path)
        await self.db.init()
        self.core = CoreStore(self.path)
        await self.core.init()
        self.source = SourceStore(self.path)
        await self.source.init()
        self.routes = RouteStore(self.path)
        await self.routes.init()
        self.admin = await self.db.ensure_user_profile(
            1001, 2001, None, "A", None, "private",
        )
        self.other = await self.db.ensure_user_profile(
            9999, 2999, None, "B", None, "private",
        )
        self.old = (await self.db.list_targets_by_tg_user(1001))[0]
        self.registry = GateBTargetStore(self.path)

    async def _cleanup(self):
        self.folder.cleanup()

    async def test_versioned_migration_preserves_id_fk_and_history(self):
        await self.db.add_keyword(1001, "DMIT")
        await self.core.observe(SourceObservation(
            Source.RSS, "pre-gate-b", 20,
            datetime.now(timezone.utc), title="DMIT",
        ))
        await self.core.enqueue(
            self.admin.id, 20, [self.old.id], now=1000
        )
        with sqlite3.connect(self.path) as db:
            self.assertEqual(next(
                row[3] for row in db.execute("PRAGMA table_info(targets)")
                if row[1] == "chat_id"
            ), 1)
        await self.registry.init()
        await self.registry.init()  # idempotent
        with sqlite3.connect(self.path) as db:
            self.assertEqual(next(
                row[3] for row in db.execute("PRAGMA table_info(targets)")
                if row[1] == "chat_id"
            ), 0)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(db.execute(
                "SELECT chat_id FROM targets WHERE id=?", (self.old.id,)
            ).fetchone()[0], 2001)
            self.assertEqual(db.execute(
                "SELECT target_id FROM delivery_tasks"
            ).fetchone()[0], self.old.id)
        await self.db.init()  # old schema initializer must not undo migration
        self.assertEqual(
            (await self.db.list_targets_by_tg_user(1001))[0].id,
            self.old.id,
        )

    async def test_push_is_disabled_and_not_fake_tg_id(self):
        await self.registry.init()
        push = await self.registry.register(
            self.admin.id, Channel.BARK, "我的手机", "BARK_PRIMARY"
        )
        items = await self.db.list_targets_by_tg_user(1001, include_push=True)
        self.assertEqual(len(items), 2)
        created = next(x for x in items if x.id == push)
        self.assertIsNone(created.chat_id)
        self.assertEqual(created.chat_type, "push")
        self.assertFalse(created.enabled)
        self.assertEqual(
            len(await self.db.list_targets_by_tg_user(1001)), 1
        )
        self.assertEqual(
            await self.db.count_targets_by_tg_user(1001), 1
        )
        self.assertIsNone(await self.routes.channel_for(self.admin.id, push))
        await self.db.set_target_enabled(self.admin.id, push, True)
        binding = await self.routes.channel_for(self.admin.id, push)
        self.assertEqual(binding.channel, Channel.BARK)
        self.assertIsNone(binding.chat_id)
        self.assertEqual(binding.secret_ref, "BARK_PRIMARY")
        # Legacy poller must NEVER try to send to the nullable push target.
        await self.db.add_keyword(1001, "DMIT")
        await self.db.set_user_initialized(self.admin.id)
        legacy = await self.db.get_polling_users()
        self.assertEqual([x.chat_id for x in legacy[0].targets], [2001])
        self.assertEqual((await self.routes.load_policy(self.admin.id)).default_targets,
                         (self.old.id, push))

    async def test_owner_isolation_and_bad_secret_or_channel(self):
        await self.registry.init()
        for channel, name, reference in [
            (Channel.TELEGRAM, "fake", "BARK_PRIMARY"),
            (Channel.BARK, "good", "barks://api.day.app/key"),
            (Channel.NTFY, "<script>", "NTFY_PRIMARY"),
            (Channel.NTFY, "good", " BOT_TOKEN"),
        ]:
            with self.subTest(channel=channel, label=name), self.assertRaises(ValueError):
                await self.registry.register(self.admin.id, channel, name, reference)
        with self.assertRaises(ValueError):
            await self.registry.register(999999, Channel.NTFY, "not-owned", "NTFY_DEV")
        own = await self.registry.register(
            self.admin.id, Channel.NTFY, "平板", "NTFY_DEV"
        )
        with self.assertRaises(ValueError):
            await self.registry.delete_unused(self.other.id, own)
        self.assertEqual(
            (await self.db.list_targets_by_tg_user(9999)), [
                (await self.db.list_targets_by_tg_user(9999))[0]
            ],
        )

    async def test_preflight_requires_real_identity_and_safe_active_secret(self):
        await self.registry.init()
        push = await self.registry.register(
            self.admin.id, Channel.BARK, "Laptop", "BARK_PRIMARY"
        )
        await self.registry.assert_live_safe()
        await self.db.set_target_enabled(self.admin.id, push, True)
        with self.assertRaises(ValueError):
            await self.registry.assert_live_safe(resolver=lambda _: None)
        with self.assertRaises(ValueError):
            await self.registry.assert_live_safe(
                resolver=lambda _: "barks://127.0.0.1/device"
            )
        await self.registry.assert_live_safe(
            resolver=lambda _: "barks://api.day.app/dummy-device"
        )
        # Old S4 proto allowed legacy TG-ID -> Bark binding; now it cannot send.
        await self.routes.bind_channel(
            self.admin.id, self.old.id, Channel.NTFY, "NTFY_DEV"
        )
        with self.assertRaises(ValueError):
            await self.registry.assert_live_safe()
        self.assertIsNone(await self.routes.channel_for(
            self.admin.id, self.old.id,
        ))

    async def test_delete_requires_disabled_and_zero_audit_history(self):
        await self.registry.init()
        push = await self.registry.register(
            self.admin.id, Channel.NTFY, "Tablet", "NTFY_DEV"
        )
        await self.db.set_target_enabled(self.admin.id, push, True)
        with self.assertRaises(ValueError):
            await self.registry.delete_unused(self.admin.id, push)
        await self.db.set_target_enabled(self.admin.id, push, False)
        self.assertTrue(await self.registry.delete_unused(self.admin.id, push))
        self.assertFalse(any(
            x.id == push
            for x in await self.db.list_targets_by_tg_user(1001, include_push=True)
        ))
        used = await self.registry.register(
            self.admin.id, Channel.BARK, "Phone", "BARK_PRIMARY"
        )
        await self.core.observe(SourceObservation(
            Source.RSS, "used-push", 21, datetime.now(timezone.utc),
            title="DMIT",
        ))
        # S2 refuses disabled destinations. Enable to create a real durable
        # task, then pause again to exercise the audit-history deletion guard.
        await self.db.set_target_enabled(self.admin.id, used, True)
        self.assertEqual(
            await self.core.enqueue(self.admin.id, 21, [used], now=1000), 1
        )
        await self.db.set_target_enabled(self.admin.id, used, False)
        with self.assertRaises(ValueError):
            await self.registry.delete_unused(self.admin.id, used)

    async def test_failed_migration_rolls_back_old_schema(self):
        # A pre-existing foreign-key orphan must stop the migration.
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute(
                """INSERT INTO s4_target_channels(target_id,channel,secret_ref)
                   VALUES (888888,'bark','SAFE_REF')"""
            )
            db.commit()
        with self.assertRaises(ValueError):
            await self.registry.init()
        with sqlite3.connect(self.path) as db:
            notnull = next(
                row[3] for row in db.execute("PRAGMA table_info(targets)")
                if row[1] == "chat_id"
            )
            self.assertEqual(notnull, 1)
            self.assertIsNone(db.execute(
                "SELECT name FROM sqlite_master WHERE name='gate_b_schema_meta'"
            ).fetchone())


@unittest.skipUnless(create_web_app is not None, "Gate B Web optional deps are installed")
class WebRegistrationContracts(unittest.IsolatedAsyncioTestCase):
    _cleanup = TargetRegistryContracts._cleanup

    async def asyncSetUp(self):
        await TargetRegistryContracts.asyncSetUp(self)
        await self.registry.init()
        config = AdminWebConfig(
            1001, password_hash("Gate B test password! 2026",
                                salt=b"0123456789abcdef"),
        )
        self.app = create_web_app(self.path, config)
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app, client=("127.0.0.1", 5252)),
            base_url="http://localhost",
        )
        await self.client.__aenter__()
        self.addAsyncCleanup(self.client.__aexit__, None, None, None)
        import re

        form = await self.client.get("/login")
        csrf = re.search(r'name="_csrf"\s+value="([^"]+)"', form.text).group(1)
        signed = await self.client.post(
            "/login", data={"_csrf": csrf, "password": "Gate B test password! 2026"},
        )
        self.assertEqual(signed.status_code, 303)
        page = await self.client.get("/channels")
        self.csrf = re.search(
            r'name="_csrf"\s+value="([^"]+)"', page.text
        ).group(1)

    async def test_web_adds_owned_push_without_url_then_enables(self):
        bad = await self.client.post("/channels/push/add", data={
            "name": "Tablet", "channel": "bark",
            "secret_ref": "barks://api.day.app/my-key", "_csrf": self.csrf,
        })
        self.assertEqual(bad.status_code, 422)
        r = await self.client.post("/channels/push/add", data={
            "name": "平板", "channel": "ntfy",
            "secret_ref": "NTFY_MAIN", "_csrf": self.csrf,
        })
        self.assertEqual(r.status_code, 303, r.text)
        row = next(t for t in await self.db.list_targets_by_tg_user(
            1001, include_push=True
        ) if t.chat_id is None)
        self.assertFalse(row.enabled)
        page = await self.client.get("/channels")
        self.assertIn("平板", page.text)
        self.assertNotIn("ntfys://", page.text)
        enabled = await self.client.post(
            f"/channels/{row.id}/state",
            data={"enabled": "1", "_csrf": self.csrf},
        )
        self.assertEqual(enabled.status_code, 303)
        self.assertEqual((await self.routes.channel_for(
            self.admin.id, row.id
        )).channel, Channel.NTFY)
        self.assertEqual(len(await self.db.list_targets_by_tg_user(9999)), 1)

    async def test_web_blocks_cross_user_and_type_change_and_csrf(self):
        other_push = await self.registry.register(
            self.other.id, Channel.BARK, "Other", "BARK_OTHER"
        )
        self.assertEqual((await self.client.post("/channels/push/add", data={
            "name": "Phone", "channel": "bark", "secret_ref": "BARK_MAIN",
        })).status_code, 403)
        self.assertEqual((await self.client.post(
            f"/channels/push/{other_push}/delete",
            data={"confirm": "DELETE", "_csrf": self.csrf},
        )).status_code, 422)
        old_to_push = await self.client.post(
            f"/channels/{self.old.id}/bind",
            data={"channel": "bark", "secret_ref": "BARK_MAIN",
                  "_csrf": self.csrf},
        )
        self.assertEqual(old_to_push.status_code, 422)
        self.assertEqual((await self.routes.channel_for(
            self.admin.id, self.old.id
        )).channel, Channel.TELEGRAM)


if __name__ == "__main__":
    unittest.main()
