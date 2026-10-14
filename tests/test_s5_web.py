"""S5 ASGI in-memory Web, authorization, CSRF/XSS and Bot/SQLite consistency.

No network socket, password uploads, real notifications, Telegram Session or
server deployment. Baseline S1/G0 jobs lack optional FastAPI dependencies:
skip these integration cases there; S5 CI installs requirements-s5.txt and
must run all cases without skips.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db import Database
from app.delivery import CoreStore
from app.domain import Source, SourceObservation
from app.route_store import Channel, RouteStore
from app.source_state import SourceStore
from app.web_auth import AdminWebConfig, WebAuth, password_hash

try:
    from httpx import ASGITransport, AsyncClient
    from app.web import create_web_app
except ModuleNotFoundError:
    ASGITransport = None
    AsyncClient = None
    create_web_app = None


PASSWORD = "SeekPulse test only! 2026"
HASH = password_hash(PASSWORD, salt=b"1234567890abcdef")
STAMP = datetime(2026, 10, 14, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, amount):
        self.t += amount


@unittest.skipUnless(create_web_app is not None, "optional FastAPI is installed only in S5 CI")
class S5WebContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory(prefix="seekpulse-s5-")
        self.addAsyncCleanup(self._clean)
        self.path = Path(self.tmp.name) / "web.sqlite3"
        self.db = Database(self.path)
        await self.db.init()
        self.core = CoreStore(self.path)
        await self.core.init()
        self.states = SourceStore(self.path)
        await self.states.init()
        self.routes = RouteStore(self.path)
        await self.routes.init()
        self.admin = await self.db.ensure_user_profile(
            1001, 2001, None, "Admin", None, "private"
        )
        self.other = await self.db.ensure_user_profile(
            9999, 2999, None, "Other", None, "private"
        )
        _, self.rule = await self.db.add_keyword(1001, "DMIT")
        _, self.other_rule = await self.db.add_keyword(9999, "PRIVATE_ACCOUNT")
        self.admin_target = (await self.db.list_targets_by_tg_user(1001))[0]
        self.other_target = (await self.db.list_targets_by_tg_user(9999))[0]
        self.clock = Clock()
        self.conf = AdminWebConfig(1001, HASH)
        self.auth = WebAuth(self.conf, clock=self.clock)
        self.app = create_web_app(self.path, self.conf, auth=self.auth)
        self.transport = ASGITransport(
            app=self.app, client=("127.0.0.1", 55555), raise_app_exceptions=True
        )
        self.client = AsyncClient(transport=self.transport, base_url="http://localhost")
        await self.client.__aenter__()
        self.addAsyncCleanup(self.client.__aexit__, None, None, None)

    async def _clean(self):
        self.tmp.cleanup()

    @staticmethod
    def csrf(html: str) -> str:
        token = re.search(r'name="_csrf"\s+value="([^"]+)"', html)
        if token is None:
            raise AssertionError("CSRF form field missing")
        return token.group(1)

    async def sign_in(self):
        form = await self.client.get("/login")
        self.assertEqual(form.status_code, 200, form.text)
        response = await self.client.post(
            "/login",
            data={"password": PASSWORD, "_csrf": self.csrf(form.text)},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers.get("location"), "/")
        return self.csrf((await self.client.get("/rules")).text)

    async def test_all_admin_pages_require_login_and_suppress_openapi(self):
        for path in (
            "/", "/rules", "/sources", "/channels", "/history",
            "/settings", "/fragments/summary",
        ):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 401)
        for path in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual((await self.client.get(path)).status_code, 404)
        script = await self.client.get("/assets/htmx.min.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("htmx", script.text)
        self.assertNotIn("unsafe-inline", script.headers["content-security-policy"])

    async def test_login_password_csrf_cannot_be_bypassed(self):
        r = await self.client.get("/login")
        token = self.csrf(r.text)
        self.assertEqual((await self.client.post(
            "/login", data={"password": PASSWORD}
        )).status_code, 403)
        self.assertEqual((await self.client.post(
            "/login", data={"password": "wrong", "_csrf": token}
        )).status_code, 200)
        self.assertEqual((await self.client.get("/rules")).status_code, 401)
        self.assertEqual((await self.client.post(
            "/login", data={"password": PASSWORD, "_csrf": token},
            headers={"Origin": "http://evil.invalid"},
        )).status_code, 403)
        r = await self.client.post(
            "/login", data={"password": PASSWORD, "_csrf": token}
        )
        self.assertEqual(r.status_code, 303)
        self.assertIn("HttpOnly", r.headers.get("set-cookie", ""))
        self.assertIn("SameSite=strict", r.headers.get("set-cookie", ""))

    async def test_login_limit_revocation_and_session_expiration(self):
        page = await self.client.get("/login")
        token = self.csrf(page.text)
        for _ in range(5):
            res = await self.client.post(
                "/login", data={"password": "wrong", "_csrf": token}
            )
            self.assertEqual(res.status_code, 200)
        self.assertEqual((await self.client.post(
            "/login", data={"password": PASSWORD, "_csrf": token}
        )).status_code, 429)
        self.clock.advance(300)
        self.assertEqual((await self.client.post(
            "/login", data={"password": PASSWORD, "_csrf": token}
        )).status_code, 303)
        admin_csrf = self.csrf((await self.client.get("/settings")).text)
        self.assertEqual((await self.client.post(
            "/logout", data={"_csrf": admin_csrf}
        )).status_code, 303)
        self.assertEqual((await self.client.get("/settings")).status_code, 401)
        await self.sign_in()
        self.clock.advance(3600)
        self.assertEqual((await self.client.get("/rules")).status_code, 401)

    async def test_csrf_required_for_mutations_and_get_is_read_only(self):
        csrf = await self.sign_in()
        before = len(await self.db.list_keywords_by_tg_user(1001))
        self.assertEqual((await self.client.get("/rules")).status_code, 200)
        self.assertEqual((await self.client.post(
            "/rules/add", data={"keyword": "oracle"}
        )).status_code, 403)
        self.assertEqual((await self.client.post(
            "/rules/add", data={"keyword": "oracle", "_csrf": "forged"}
        )).status_code, 403)
        self.assertEqual(len(await self.db.list_keywords_by_tg_user(1001)), before)
        r = await self.client.post(
            "/rules/add", data={"keyword": "oracle", "_csrf": csrf}
        )
        self.assertEqual(r.status_code, 303)
        self.assertEqual(len(await self.db.list_keywords_by_tg_user(1001)), before + 1)

    async def test_web_changes_are_immediately_visible_in_existing_bot_db(self):
        token = await self.sign_in()
        added = await self.client.post(
            "/rules/add", data={"keyword": "甲骨文 + 补货", "_csrf": token}
        )
        self.assertEqual(added.status_code, 303)
        rules = await self.db.list_keywords_by_tg_user(1001)
        new_rule = next(k for k in rules if "甲骨文" in k.keyword)
        self.assertIn("甲骨文", new_rule.required_keywords)
        await self.db.set_keyword_enabled(1001, new_rule.id, False)  # Bot action
        page = await self.client.get("/rules")
        self.assertEqual(page.status_code, 200)
        self.assertIn("甲骨文", page.text)
        self.assertIn("已暂停", page.text)
        await self.client.post("/settings/categories", data={
            "_csrf": token, "categories": ["trade", "tech"],
        })
        stored = await self.db.get_user_settings_by_tg_user(1001)
        self.assertEqual(stored.category_slugs, "trade,tech")
        await self.client.post("/settings/state", data={
            "_csrf": token, "enabled": "0",
        })
        self.assertFalse((await self.db.get_user_settings_by_tg_user(1001)).enabled)

    async def test_cross_user_rule_and_target_never_mutate(self):
        csrf = await self.sign_in()
        x = await self.client.post(
            "/rules/" + str(self.other_rule.id) + "/state",
            data={"_csrf": csrf, "enabled": "0"},
        )
        self.assertEqual(x.status_code, 404)
        x = await self.client.post(
            "/rules/" + str(self.other_rule.id) + "/route",
            data={"_csrf": csrf, "priority": "urgent", "override": "0"},
        )
        self.assertEqual(x.status_code, 422)
        x = await self.client.post(
            "/channels/" + str(self.other_target.id) + "/bind",
            data={"_csrf": csrf, "channel": "bark", "secret_ref": "BARK_PRIMARY"},
        )
        self.assertEqual(x.status_code, 422)
        x = await self.client.post(
            "/channels/defaults",
            data={"_csrf": csrf, "override": "1", "target_ids": str(self.other_target.id)},
        )
        self.assertEqual(x.status_code, 422)
        self.assertTrue((
            await self.db.list_keywords_by_tg_user(9999)
        )[0].enabled)
        self.assertEqual((await self.routes.load_policy(self.other.id)).default_targets,
                         (self.other_target.id,))

    async def test_sources_and_channel_binding_share_exact_s3_s4_state(self):
        csrf = await self.sign_in()
        response = await self.client.post(
            "/sources/rss/state", data={"_csrf": csrf, "enabled": "0"}
        )
        self.assertEqual(response.status_code, 303)
        self.assertFalse((await self.states.status(Source.RSS)).enabled)
        self.assertFalse((await self.states.status(Source.TELEGRAM)).enabled)
        response = await self.client.post(
            "/channels/" + str(self.admin_target.id) + "/bind",
            data={"_csrf": csrf, "channel": "bark", "secret_ref": "BARK_PRIMARY"},
        )
        self.assertEqual(response.status_code, 303)
        binding = await self.routes.channel_for(self.admin.id, self.admin_target.id)
        self.assertEqual(binding.channel, Channel.BARK)
        self.assertEqual(binding.secret_ref, "BARK_PRIMARY")
        bad = await self.client.post(
            "/channels/" + str(self.admin_target.id) + "/bind",
            data={"_csrf": csrf, "channel": "ntfy",
                  "secret_ref": "ntfys://ntfy.sh/private"},
        )
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(
            (await self.routes.channel_for(self.admin.id, self.admin_target.id)).secret_ref,
            "BARK_PRIMARY",
        )
        self.assertNotIn("ntfys://", (await self.client.get("/channels")).text)

    async def test_xss_escaping_and_csp_blocks_user_controlled_html(self):
        await self.db.add_keyword(1001, "<svg/onload=alert(1)>")
        await self.db.mark_delivered(
            self.admin.id, "evil-key", title="<img src=x onerror=alert(1)>",
            link="https://example.invalid", category_slug=None,
            matched_keywords=["evil"],
        )
        await self.sign_in()
        page = await self.client.get("/rules")
        self.assertIn("&lt;svg", page.text)
        self.assertNotIn("<svg/onload", page.text)
        history = await self.client.get("/history")
        self.assertIn("&lt;img", history.text)
        self.assertNotIn("<img src=x", history.text)
        self.assertIn("frame-ancestors 'none'", history.headers["content-security-policy"])
        self.assertEqual(history.headers.get("x-frame-options"), "DENY")

    async def test_host_and_forwarded_headers_and_remote_peer_denied(self):
        self.assertEqual((await self.client.get(
            "/login", headers={"Host": "localhost.evil.invalid"}
        )).status_code, 403)
        self.assertEqual((await self.client.get(
            "/login", headers={"X-Forwarded-Host": "localhost"}
        )).status_code, 403)
        async with AsyncClient(
            transport=ASGITransport(
                app=self.app, client=("198.51.100.23", 4567),
            ),
            base_url="http://localhost",
        ) as remote:
            self.assertEqual((await remote.get("/login")).status_code, 403)

    async def test_history_and_statistics_never_leak_other_user_data(self):
        await self.core.observe(SourceObservation(
            source=Source.RSS, event_id="100-100",
            post_id=100, observed_at=STAMP, title="Admin title",
        ))
        await self.core.observe(SourceObservation(
            source=Source.RSS, event_id="200-200",
            post_id=200, observed_at=STAMP, title="Other title",
        ))
        await self.core.enqueue(
            self.admin.id, 100, [self.admin_target.id], now=1000
        )
        await self.core.enqueue(
            self.other.id, 200, [self.other_target.id], now=1000
        )
        await self.sign_in()
        dash = await self.client.get("/")
        self.assertIn("关联帖子", dash.text)
        self.assertIn("API 已接受", dash.text)
        history = await self.client.get("/history")
        self.assertIn("post-100-1", history.text)
        self.assertNotIn("post-200-1", history.text)
        self.assertEqual((await self.client.get("/fragments/summary")).status_code, 200)

    async def test_unknown_admin_profile_onboarding_never_creates_identity(self):
        other_config = AdminWebConfig(7333, HASH)
        app = create_web_app(self.path, other_config)
        auth = app  # app is isolated from the original administrator's sessions
        self.assertIsNotNone(auth)
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("127.0.0.1", 42000)),
            base_url="http://localhost",
        ) as client:
            login = await client.get("/login")
            r = await client.post(
                "/login", data={"_csrf": self.csrf(login.text), "password": PASSWORD}
            )
            self.assertEqual(r.status_code, 303)
            info = await client.get("/")
            self.assertEqual(info.status_code, 200)
            self.assertIn("请先在 Telegram Bot 中完成 /start", info.text)
            blocked = await client.get("/rules")
            self.assertEqual(blocked.status_code, 409)
        self.assertIsNone(await self.db.get_user_settings_by_tg_user(7333))

    async def test_keyword_count_limit_matches_existing_bot(self):
        csrf = await self.sign_in()
        # The admin already has one existing Bot keyword in shared SQLite.
        with patch.dict(os.environ, {"MAX_KEYWORDS_PER_USER": "1"}):
            response = await self.client.post(
                "/rules/add", data={"_csrf": csrf, "keyword": "oracle"}
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(await self.db.list_keywords_by_tg_user(1001)), 1)

    async def test_latency_is_source_to_api_not_mobile_and_scoped(self):
        from app.web_service import WebService

        await self.core.observe(SourceObservation(
            source=Source.RSS, event_id="latency-rss", post_id=888,
            observed_at=STAMP, title="Measured admin post",
        ))
        start = int(STAMP.timestamp())
        await self.core.enqueue(
            self.admin.id, 888, [self.admin_target.id], now=start + 1
        )
        task = (await self.core.claim(now=start + 2, limit=1))[0]
        self.assertTrue(await self.core.mark_sent(
            task.id, task.lease_token, now=start + 5
        ))
        metrics = await WebService(self.path, 1001).dashboard()
        self.assertEqual(metrics["latency_samples"], 1)
        self.assertEqual(metrics["source_api_p50_ms"], 5000)
        self.assertEqual(metrics["source_api_p95_ms"], 5000)
        await self.sign_in()
        html = (await self.client.get("/")).text
        self.assertIn("P50 延迟", html)
        self.assertIn("API 接受", html)
        self.assertIn("5000", html)
        self.assertIn("不能代表论坛发布时间或手机实际提醒", html)

    async def test_web_default_and_priority_update_reflect_s4_policy(self):
        csrf = await self.sign_in()
        response = await self.client.post(
            "/rules/" + str(self.rule.id) + "/route",
            data={"_csrf": csrf, "priority": "urgent", "override": "1",
                  "target_ids": str(self.admin_target.id)},
        )
        self.assertEqual(response.status_code, 303)
        policy = await self.routes.load_policy(self.admin.id)
        self.assertEqual(policy.rules[0].priority.value, 1)
        self.assertEqual(policy.rules[0].override_targets, (self.admin_target.id,))
        response = await self.client.post(
            "/channels/defaults",
            data={"_csrf": csrf, "override": "1"},
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual((await self.routes.load_policy(self.admin.id)).default_targets, ())


if __name__ == "__main__":
    unittest.main()
