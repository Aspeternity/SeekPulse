"""S4 native Telegram and restricted single-target Apprise adapters.

All actual calls are opt-in; app.main never constructs or starts these adapters.
No logging of token, Telegram errors, device keys or notification URLs.
"""

from __future__ import annotations

import asyncio
import ipaddress
import math
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from telegram import LinkPreviewOptions
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from app.domain import CanonicalPost
from app.route_store import Channel, ChannelTarget
from app.utils import escape_html


@dataclass(frozen=True, slots=True)
class Notification:
    title: str
    body: str
    link: str

    @classmethod
    def from_post(cls, post: CanonicalPost) -> "Notification":
        title = (post.title or "NodeSeek 新帖")[:500]
        return cls(title=title, body=f"{title}\n{post.url}", link=post.url)


@dataclass(frozen=True, slots=True)
class SendResult:
    accepted: bool
    retryable: bool = False
    error_code: str | None = None
    retry_after_seconds: int = 0

    @classmethod
    def success(cls) -> "SendResult":
        return cls(True)

    @classmethod
    def failure(cls, code: str, *, retryable: bool,
                retry_after_seconds: int = 0) -> "SendResult":
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", code):
            raise ValueError("error code must be safe")
        if type(retryable) is not bool or type(retry_after_seconds) is not int:
            raise ValueError("invalid error result")
        if not 0 <= retry_after_seconds <= 86400:
            raise ValueError("invalid retry delay")
        return cls(False, retryable, code, retry_after_seconds)


def _retry_seconds(value: Any) -> int:
    try:
        if isinstance(value, timedelta):
            value = value.total_seconds()
        delay = math.ceil(float(value))
        return min(86400, max(0, delay))
    except (TypeError, ValueError, OverflowError):
        return 0


class TelegramNotifier:
    """Inject an authorized native python-telegram-bot Bot. No Bot login here."""

    def __init__(self, bot: Any):
        self.bot = bot

    async def send(self, target: ChannelTarget, message: Notification) -> SendResult:
        if target.channel is not Channel.TELEGRAM or type(target.chat_id) is not int:
            return SendResult.failure("invalid_telegram_target", retryable=False)
        safe_link = escape_html(message.link)
        safe_title = escape_html(message.title)
        try:
            await self.bot.send_message(
                chat_id=target.chat_id,
                text=f'<a href="{safe_link}">{safe_title}</a>',
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            return SendResult.success()
        except RetryAfter as exc:
            return SendResult.failure(
                "http_429", retryable=True,
                retry_after_seconds=_retry_seconds(exc.retry_after),
            )
        except (Forbidden, BadRequest):
            return SendResult.failure("telegram_rejected", retryable=False)
        except (TimedOut, NetworkError):
            return SendResult.failure("telegram_network", retryable=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never persist exception text or accidental request URL/token.
            return SendResult.failure("telegram_error", retryable=True)


class AppriseNotifier:
    """Strict Bark/ntfy wrapper: one service per request, official HTTPS only.

    The *secret* is a barks:// or ntfys:// HTTPS-only URL supplied by
    a protected runtime resolver. SQLite keeps only its environment-key-like reference. Allowing
    additional notification hosts requires separately reviewed config:
    arbitrary URLs, raw IPs, redirect targets and private addresses are not
    accepted by this V1.1 adapter.
    """

    OFFICIAL_HOSTS: Mapping[Channel, frozenset[str]] = {
        Channel.BARK: frozenset({"api.day.app"}),
        Channel.NTFY: frozenset({"ntfy.sh"}),
    }

    def __init__(
        self,
        resolver: Callable[[str], str | None],
        *,
        factory: Callable[[], Any] | None = None,
        timeout_seconds: int = 8,
    ):
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 20:
            raise ValueError("invalid Apprise timeout")
        self.resolver = resolver
        self.factory = factory or self._apprise
        self.timeout_seconds = timeout_seconds

    def _apprise(self):
        import apprise
        return apprise.Apprise(
            asset=apprise.AppriseAsset(service_timeout=6)
        )

    @staticmethod
    def validated_url(channel: Channel, raw: str) -> str:
        """Fail closed; do not render the sensitive raw URL in errors."""
        if channel not in (Channel.BARK, Channel.NTFY):
            raise ValueError("unsupported push provider")
        if not isinstance(raw, str) or len(raw) > 900:
            raise ValueError("invalid push configuration")
        try:
            parts = urlsplit(raw)
            host = parts.hostname
            port = parts.port
        except ValueError as exc:
            raise ValueError("invalid push configuration") from exc
        # Apprise "bark://" and "ntfy://" are plain HTTP. Require TLS.
        secure_schemes = {Channel.BARK: "barks", Channel.NTFY: "ntfys"}
        if (
            parts.scheme != secure_schemes[channel]
            or not host or host.lower() not in AppriseNotifier.OFFICIAL_HOSTS[channel]
            or port not in (None, 443)
            or parts.username is not None or parts.password is not None
            or not parts.path.startswith("/")
            or not parts.path.strip("/")
            or parts.query or parts.fragment
            or "\\" in raw or any(c.isspace() for c in raw)
            # Exactly one destination per S2 target; no second device/topic
            # or encoded slash may slip under one target's delivery status.
            or re.fullmatch(r"/[A-Za-z0-9._~-]{1,200}", parts.path) is None
        ):
            raise ValueError("push destination denied")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("literal IP is forbidden")
        if any(part in {"..", "."} for part in parts.path.split("/")):
            raise ValueError("invalid push path")
        # Disable Apprise-level retries/redirects; the durable worker owns
        # retry scheduling and the URL is restricted to a fixed official host.
        return raw + "?retry=0&cto=3&rto=5&redirect=no"

    async def send(self, target: ChannelTarget, message: Notification) -> SendResult:
        if target.channel not in (Channel.BARK, Channel.NTFY) or not target.secret_ref:
            return SendResult.failure("invalid_push_target", retryable=False)
        try:
            raw = self.resolver(target.secret_ref)
            url = self.validated_url(target.channel, raw)
            instance = self.factory()
            if not instance.add(url):
                return SendResult.failure("push_config_rejected", retryable=False)
            result = await asyncio.wait_for(
                instance.async_notify(title=message.title, body=message.body),
                timeout=self.timeout_seconds,
            )
            services = list(result) if hasattr(result, "__iter__") else []
            if bool(result) and len(services) == 1 and bool(services[0]):
                return SendResult.success()

            # Apprise 2.0.1 returns a result object, not literal True.
            # HTTP response codes are not guaranteed on every service result.
            # Only classify a permanent denial if a numeric status is actually
            # exposed, never guess 403 from an unstructured exception string.
            code = getattr(services[0], "status_code", None) if len(services) == 1 else None
            if code in (400, 401, 403, 404):
                return SendResult.failure("push_rejected", retryable=False)
            if code == 429:
                return SendResult.failure("http_429", retryable=True)
            return SendResult.failure("push_failed", retryable=True)
        except (asyncio.TimeoutError, TimeoutError):
            return SendResult.failure("push_timeout", retryable=True)
        except ValueError:
            return SendResult.failure("push_config_rejected", retryable=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            return SendResult.failure("push_error", retryable=True)
