"""S5 administrator credential/session/Host contracts (stdlib + existing deps)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.web_auth import (
    AdminWebConfig, WebAuth, check_password, loopback_request, password_hash,
)


class FakeClock:
    def __init__(self):
        self.time = 1000.0

    def __call__(self):
        return self.time

    def advance(self, seconds):
        self.time += seconds


class WebAuthContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded = password_hash(
            "Test password strong 2026!", salt=b"0123456789abcdef"
        )

    def config(self):
        return AdminWebConfig(1001, self.encoded)

    def test_scrypt_hash_constant_time_verification_and_salt(self):
        self.assertTrue(check_password("Test password strong 2026!", self.encoded))
        self.assertFalse(check_password("wrong password", self.encoded))
        self.assertFalse(check_password("anything", "plain-text"))
        self.assertNotIn("Test password", self.encoded)
        self.assertNotEqual(
            password_hash("Test password strong 2026!"),
            password_hash("Test password strong 2026!"),
        )

    def test_bad_password_or_hash_rejected(self):
        for value in ("short", "", "A" * 513):
            with self.subTest(value=value[:20]), self.assertRaises(ValueError):
                password_hash(value)
        for bad in ("", "sha256$123", "scrypt$2$8$1$bad$hash"):
            with self.subTest(hash=bad), self.assertRaises(ValueError):
                AdminWebConfig(1001, bad)
        with self.assertRaises(ValueError):
            AdminWebConfig(-1, self.encoded)

    def test_environment_must_not_implicitly_use_bot_token(self):
        with patch.dict(os.environ, {"BOT_TOKEN": "telegram-fake"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "credentials"):
                AdminWebConfig.from_environment()
        with patch.dict(os.environ, {
            "SEEKPULSE_ADMIN_TG_USER_ID": "1001",
            "SEEKPULSE_WEB_PASSWORD_HASH": self.encoded,
        }, clear=True):
            self.assertEqual(AdminWebConfig.from_environment().admin_tg_user_id, 1001)

    def test_session_guest_admin_separation_expiry_and_revocation(self):
        clock = FakeClock()
        auth = WebAuth(self.config(), clock=clock)
        guest_token, guest = auth.new_session(authenticated=False)
        self.assertIs(auth.get(guest_token, authenticated=False), guest)
        self.assertIsNone(auth.get(guest_token, authenticated=True))
        token, user = auth.new_session(authenticated=True)
        self.assertIs(auth.get(token, authenticated=True), user)
        self.assertNotEqual(guest.csrf, user.csrf)
        auth.revoke(guest_token)
        self.assertIsNone(auth.get(guest_token))
        clock.advance(3600)
        self.assertIsNone(auth.get(token))

    def test_rate_limit_blocks_sixth_attempt_and_expires(self):
        clock = FakeClock()
        auth = WebAuth(self.config(), clock=clock)
        for _ in range(5):
            self.assertTrue(auth.login_allowed("127.0.0.1"))
            auth.login_failure("127.0.0.1")
        self.assertFalse(auth.login_allowed("127.0.0.1"))
        clock.advance(300)
        self.assertTrue(auth.login_allowed("127.0.0.1"))

    def test_session_count_is_bounded(self):
        auth = WebAuth(self.config())
        for _ in range(280):
            auth.new_session(authenticated=False)
        self.assertLessEqual(len(auth._sessions), 256)

    def test_loopback_peer_and_dns_rebinding_blocked(self):
        local = {"client": ("127.0.0.1", 42000)}
        v6 = {"client": ("::1", 42000)}
        remote = {"client": ("203.0.113.20", 50000)}
        for host in ("localhost", "localhost:8765", "127.0.0.1:8765"):
            self.assertTrue(loopback_request(local, host), host)
        self.assertTrue(loopback_request(v6, "[::1]:8765"))
        for host in (
            "evil.invalid", "localhost.evil.invalid", "127.0.0.1.evil.invalid",
            "127.0.0.1:badport", "127.0.0.1@evil.invalid", "",
        ):
            self.assertFalse(loopback_request(local, host), host)
        self.assertFalse(loopback_request(remote, "localhost"))
        self.assertFalse(loopback_request(local, "localhost", forwarded=True))


if __name__ == "__main__":
    unittest.main()
