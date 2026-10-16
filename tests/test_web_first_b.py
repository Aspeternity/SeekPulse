"""Web-first B first-page registration contract: no generated credentials or log code.

All tests use a temporary private directory and ASGI in-process transport.
No Telegram/Bark/ntfy connection, no external sockets, no real NAS/PVE data.
"""

from __future__ import annotations

import re
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.instance_lock import database_owner_lock
from app.web_first_store import UnsafeWebFirstData, WebFirstStore

try:
    from httpx import ASGITransport, AsyncClient
    from app.web_first import create_web_first_app
except ModuleNotFoundError:
    ASGITransport = AsyncClient = create_web_first_app = None


PASSWORD = "A strong local Web password 2026!"
NEW_PASSWORD = "Another strong Web password 2026!"


class WebFirstBootstrapContracts(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="seekpulse-webfirst-b-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.base.chmod(0o700)
        self.store = WebFirstStore(self.base)

    def test_new_volume_initializes_without_creating_any_account_or_secret(self):
        with database_owner_lock(self.store.path):
            self.assertIsNone(self.store.prepare_locked())
            self.assertFalse(self.store.admin_exists())
            files = {path.name for path in self.base.iterdir()}
            self.assertEqual(
                files, {"web-first.sqlite", "web-first.sqlite.owner.lock"}
            )
            with sqlite3.connect(self.store.path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_admin").fetchone()[0], 0)
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone(), (1,))
        self.assertFalse(any("setup" in p.name or "password" in p.name for p in self.base.iterdir()))

    def test_user_chooses_username_password_once_then_logs_in_after_restart(self):
        with database_owner_lock(self.store.path):
            self.store.prepare_locked()
            self.assertTrue(self.store.create_admin("my_admin", PASSWORD))
            self.assertFalse(self.store.create_admin("another", NEW_PASSWORD))
            self.assertTrue(self.store.admin_exists())
            self.assertTrue(self.store.check_login("my_admin", PASSWORD))
            self.assertFalse(self.store.check_login("my_admin", "wrong"))
            self.store.save_preferences({"theme": "dark", "home": "rules"})
        # Simulate a process restart without resetting the DB.
        recovered = WebFirstStore(self.base)
        with database_owner_lock(recovered.path):
            self.assertIsNone(recovered.prepare_locked())
            self.assertEqual(recovered.admin_name(), "my_admin")
            self.assertTrue(recovered.check_login("my_admin", PASSWORD))
            self.assertEqual(recovered.preferences()["theme"], "dark")
            self.assertEqual(recovered.preferences()["home"], "rules")
            self.assertTrue(recovered.change_password(PASSWORD, NEW_PASSWORD))
            self.assertFalse(recovered.check_login("my_admin", PASSWORD))
            self.assertTrue(recovered.check_login("my_admin", NEW_PASSWORD))

    def test_bad_and_repeat_registrations_fail_without_creating_users(self):
        with database_owner_lock(self.store.path):
            self.store.prepare_locked()
            for bad in ("", "a", "space name", "x" * 33):
                self.assertFalse(self.store.create_admin(bad, PASSWORD))
            self.assertFalse(self.store.create_admin("admin", "short"))
            self.assertFalse(self.store.admin_exists())
            self.assertTrue(self.store.create_admin("admin", PASSWORD))
            self.assertFalse(self.store.create_admin("admin2", PASSWORD))
            with sqlite3.connect(self.store.path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_admin").fetchone()[0], 1)

    def test_nonempty_data_volume_or_corrupted_db_fails_closed(self):
        (self.base / "bot.db").write_bytes(b"legacy data do not destroy")
        before = (self.base / "bot.db").read_bytes()
        with database_owner_lock(self.store.path), self.assertRaises(UnsafeWebFirstData):
            self.store.prepare_locked()
        self.assertEqual((self.base / "bot.db").read_bytes(), before)
        (self.base / "bot.db").unlink()
        self.store.path.write_bytes(b"this is not a sqlite database")
        self.store.path.chmod(0o600)
        with database_owner_lock(self.store.path), self.assertRaises(UnsafeWebFirstData):
            self.store.prepare_locked()
        self.assertEqual(self.store.path.read_bytes(), b"this is not a sqlite database")


@unittest.skipUnless(
    create_web_first_app is not None,
    "optional Web packages are provided by B/S5 integration CI",
)
class WebFirstPageContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(prefix="seekpulse-webfirst-asgi-")
        self.addAsyncCleanup(self._cleanup)
        self.base = Path(self.temp.name)
        self.base.chmod(0o700)
        self.store = WebFirstStore(self.base)
        # A real process holds the owner lock throughout its lifetime.
        self.lock = database_owner_lock(self.store.path)
        self.lock.__enter__()
        self.addAsyncCleanup(self._unlock)
        self.store.prepare_locked()
        app = create_web_first_app(self.store)
        transport = ASGITransport(
            app=app, client=("192.168.1.20", 55555), raise_app_exceptions=True
        )
        self.client = AsyncClient(
            transport=transport, base_url="http://192.168.1.10:8765"
        )
        await self.client.__aenter__()
        self.addAsyncCleanup(self.client.__aexit__, None, None, None)

    async def _unlock(self):
        self.lock.__exit__(None, None, None)

    async def _cleanup(self):
        self.temp.cleanup()

    @staticmethod
    def csrf(html):
        m = re.search(r'name="_csrf"\s+value="([^"]+)"', html)
        assert m, "CSRF must be present on first registration and login"
        return m.group(1)

    async def test_first_url_is_registration_without_codes_then_login(self):
        first = await self.client.get("/", follow_redirects=False)
        self.assertEqual(first.status_code, 303)
        self.assertEqual(first.headers.get("location"), "/register")
        registration = await self.client.get("/register")
        self.assertEqual(registration.status_code, 200)
        self.assertIn("创建管理员账号", registration.text)
        self.assertIn('name="username"', registration.text)
        self.assertIn('name="password"', registration.text)
        self.assertIn('name="confirm"', registration.text)
        self.assertNotIn("setup_code", registration.text)
        self.assertNotIn("初始化码", registration.text)
        self.assertNotIn("容器日志", registration.text)

        csrf = self.csrf(registration.text)
        rejected = await self.client.post(
            "/register", data={
                "_csrf": csrf, "username": "owner",
                "password": PASSWORD, "confirm": "wrong",
            }, follow_redirects=False
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertFalse(self.store.admin_exists())

        form = await self.client.get("/register")
        registered = await self.client.post(
            "/register", data={
                "_csrf": self.csrf(form.text),
                "username": "owner", "password": PASSWORD, "confirm": PASSWORD,
            }, follow_redirects=False
        )
        self.assertEqual(registered.status_code, 303)
        self.assertEqual(registered.headers.get("location"), "/login")
        self.assertEqual(self.store.admin_name(), "owner")
        self.assertEqual((await self.client.get("/register", follow_redirects=False)).status_code, 303)

        login = await self.client.get("/login")
        logged_in = await self.client.post(
            "/login", data={
                "_csrf": self.csrf(login.text), "username": "owner",
                "password": PASSWORD,
            }, follow_redirects=False
        )
        self.assertEqual(logged_in.status_code, 303)
        self.assertEqual(logged_in.headers.get("location"), "/")
        dashboard = await self.client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("运行概览", dashboard.text)
        self.assertIn("B 阶段", dashboard.text)

    async def test_csrf_rejects_form_posts(self):
        await self.client.get("/register")
        bad = await self.client.post(
            "/register", data={
                "_csrf": "bad", "username": "owner",
                "password": PASSWORD, "confirm": PASSWORD,
            }, follow_redirects=False
        )
        self.assertEqual(bad.status_code, 403)
        self.assertFalse(self.store.admin_exists())

    async def test_host_forwarded_and_origin_rejected(self):
        for headers in (
            {"host": "evil.example"},
            {"forwarded": "for=192.168.1.20"},
            {"x-forwarded-host": "192.168.1.10"},
        ):
            res = await self.client.get("/register", headers=headers)
            self.assertEqual(res.status_code, 403)
        await self.client.get("/register")
        res = await self.client.post(
            "/register", headers={"origin": "http://evil.example"},
            data={"username": "owner", "password": PASSWORD, "confirm": PASSWORD},
        )
        self.assertEqual(res.status_code, 403)
