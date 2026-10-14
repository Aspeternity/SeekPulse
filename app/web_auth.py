"""S5 loopback-only administrator login, sessions and CSRF.

Passwords and tokens never go into the DB, audit logs or source. A process
restart revokes sessions. Only the configured Telegram admin can use Web.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import ipaddress
import os
import secrets
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(data: str) -> bytes:
    return base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)


def password_hash(password: str, *, salt: bytes | None = None) -> str:
    if not isinstance(password, str) or len(password) < 12 or len(password) > 512:
        raise ValueError("administrator password must be 12..512 characters")
    salt = secrets.token_bytes(16) if salt is None else salt
    if len(salt) != 16:
        raise ValueError("salt must be 16 bytes")
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + _encode(salt) + "$" + _encode(digest)


def check_password(password: str, encoded: str) -> bool:
    try:
        kind, n, r, p, salt_text, want_text = encoded.split("$")
        if (kind, n, r, p) != ("scrypt", "16384", "8", "1"):
            return False
        salt, want = _decode(salt_text), _decode(want_text)
        if len(salt) != 16 or len(want) != 32:
            return False
        if not isinstance(password, str) or len(password) > 512:
            return False
        got = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(got, want)
    except (ValueError, TypeError, UnicodeError):
        return False


@dataclass(frozen=True, slots=True)
class AdminWebConfig:
    admin_tg_user_id: int
    password_digest: str
    session_seconds: int = 3600
    secure_cookie: bool = False

    def __post_init__(self) -> None:
        if type(self.admin_tg_user_id) is not int or self.admin_tg_user_id <= 0:
            raise ValueError("S5 requires a positive administrator Telegram user ID")
        try:
            pieces = self.password_digest.split("$")
            if (pieces[:4] != ["scrypt", "16384", "8", "1"]
                    or len(pieces) != 6
                    or len(_decode(pieces[4])) != 16
                    or len(_decode(pieces[5])) != 32):
                raise ValueError("invalid password hash")
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid administrator password hash") from exc
        if type(self.session_seconds) is not int or not 300 <= self.session_seconds <= 86400:
            raise ValueError("session expiry must be between 5 minutes and 24 hours")
        if type(self.secure_cookie) is not bool:
            raise ValueError("secure_cookie must be boolean")

    @classmethod
    def from_environment(cls) -> "AdminWebConfig":
        """Fail closed; BOT_TOKEN must never double as a Web password."""
        try:
            tg_user_id = int(os.environ["SEEKPULSE_ADMIN_TG_USER_ID"])
            digest = os.environ["SEEKPULSE_WEB_PASSWORD_HASH"]
        except (KeyError, ValueError) as exc:
            raise RuntimeError("S5 Web administrator credentials are not configured") from exc
        return cls(tg_user_id, digest)


@dataclass(frozen=True, slots=True)
class Session:
    csrf: str
    expires_at: float
    authenticated: bool


class WebAuth:
    COOKIE = "seekpulse_web_session"

    def __init__(self, config: AdminWebConfig, *, clock: Callable[[], float] = time.monotonic):
        self.config = config
        self.clock = clock
        self._sessions: dict[str, Session] = {}
        self._failed_logins: dict[str, list[float]] = {}

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def new_session(self, *, authenticated: bool) -> tuple[str, Session]:
        now = self.clock()
        self._sessions = {k: v for k, v in self._sessions.items() if v.expires_at > now}
        if len(self._sessions) >= 256:
            oldest = min(self._sessions, key=lambda k: self._sessions[k].expires_at)
            del self._sessions[oldest]
        token = secrets.token_urlsafe(32)
        session = Session(secrets.token_urlsafe(32), now + self.config.session_seconds, authenticated)
        self._sessions[self._key(token)] = session
        return token, session

    def get(self, token: str | None, *, authenticated: bool | None = None) -> Session | None:
        if not token or len(token) > 200:
            return None
        key = self._key(token)
        session = self._sessions.get(key)
        if session is None:
            return None
        if session.expires_at <= self.clock():
            self._sessions.pop(key, None)
            return None
        if authenticated is not None and session.authenticated is not authenticated:
            return None
        return session

    def revoke(self, token: str | None) -> None:
        if token:
            self._sessions.pop(self._key(token), None)

    def login_allowed(self, client_id: str) -> bool:
        now = self.clock()
        attempts = [t for t in self._failed_logins.get(client_id, []) if now - t < 300]
        self._failed_logins[client_id] = attempts
        return len(attempts) < 5

    def login_failure(self, client_id: str) -> None:
        if self.login_allowed(client_id):
            self._failed_logins[client_id].append(self.clock())

    def login_success(self, client_id: str) -> None:
        self._failed_logins.pop(client_id, None)


def loopback_request(scope: dict, host: str | None, forwarded: bool = False) -> bool:
    """Reject both non-local transport and hostile Host including DNS rebinding."""
    if forwarded or not host:
        return False
    client = scope.get("client")
    if not client:
        return False
    try:
        if not ipaddress.ip_address(client[0]).is_loopback:
            return False
        url = urlsplit("http://" + host)
        if url.username or url.password or url.path or url.query or url.fragment:
            return False
        if url.hostname not in ("localhost", "127.0.0.1", "::1"):
            return False
        return url.port is None or 1 <= url.port <= 65535
    except (ValueError, TypeError):
        return False


if __name__ == "__main__":
    # Interactive only: never put a password on the command line/history.
    plain = getpass.getpass("SeekPulse Web administrator password (12+ chars): ")
    confirm = getpass.getpass("Confirm password: ")
    if not hmac.compare_digest(plain, confirm):
        raise SystemExit("Passwords do not match")
    print(password_hash(plain))
