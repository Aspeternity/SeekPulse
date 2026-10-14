"""S3 official RSS and Telegram source adapters into the S2 canonical store.

Read-only ingestion only: no delivery task creation, user routing, notifications,
Bot token access, Telegram login prompts, or changes to the legacy FeedPoller.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from app.delivery import CoreStore
from app.domain import (
    Source, SourceObservation, canonical_post_url, post_id_from_url,
)
from app.rss import FeedClient, FeedEntry
from app.source_state import SourceStore

_URL = re.compile(r"""https?://[^\s<>"']+""", re.IGNORECASE)
_TRAILING = "),.;!?]}\u3002\uff01\uff1f"
_CHANNEL = "nodeseekc"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(clock: Callable[[], datetime]) -> tuple[datetime, int]:
    dt = clock()
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("source clock must be timezone aware")
    dt = dt.astimezone(timezone.utc)
    return dt, int(dt.timestamp())


@dataclass(frozen=True, slots=True)
class PollReport:
    source: Source
    outcome: str
    fetched: int = 0
    observed: int = 0
    skipped: int = 0


def _rss_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != "rss.nodeseek.com"
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443)
                or parts.path not in ("", "/") or parts.query or parts.fragment):
            raise ValueError("RSS must be the official HTTPS endpoint")
    except (AttributeError, ValueError) as error:
        raise ValueError("RSS must be the official HTTPS endpoint") from error
    return "https://rss.nodeseek.com/"


def rss_observation(entry: FeedEntry, observed_at: datetime) -> SourceObservation | None:
    """Prefer the official link; a canonical GUID can be used if link is absent.

    FeedEntry.summary_known distinguishes a feed with no summary element from a
    known empty summary. Unknown information must not accidentally match rules.
    """
    post_id = post_id_from_url(entry.link) or post_id_from_url(entry.item_key)
    if post_id is None:
        return None
    return SourceObservation(
        source=Source.RSS, event_id=str(post_id), post_id=post_id,
        observed_at=observed_at,
        title=entry.title or None,
        summary=entry.summary if getattr(entry, "summary_known", False) else None,
        category=entry.category_slug,
        link=canonical_post_url(post_id),
    )


def telegram_observation(message: Any, observed_at: datetime) -> SourceObservation | None:
    """Extract only one unambiguous official post ID from public channel text.

    Recognize both text links and Telethon hidden text_url entities. Unrelated
    URLs, oversized IDs and messages linking multiple posts are skipped. Never
    infer identity from fuzzy titles or store the entire raw Telegram message.
    """
    message_id = getattr(message, "id", None)
    if type(message_id) is not int or message_id <= 0:
        return None
    raw = getattr(message, "raw_text", "") or ""
    if not isinstance(raw, str):
        return None
    urls = [
        getattr(entity, "url", None)
        for entity in (getattr(message, "entities", None) or ())
    ]
    urls.extend(_URL.findall(raw))
    ids = {
        post_id for link in urls if isinstance(link, str)
        if (post_id := post_id_from_url(link.rstrip(_TRAILING))) is not None
    }
    if len(ids) != 1:
        return None
    post_id = ids.pop()

    # The first line is an observed public headline only if it is not a URL.
    # No guessed category or full-body summary is manufactured from Telegram.
    first_line = raw.splitlines()[0].strip() if raw.splitlines() else ""
    title = None
    if first_line and "://" not in first_line and len(first_line) <= 280:
        title = first_line
    return SourceObservation(
        source=Source.TELEGRAM, event_id=str(message_id), post_id=post_id,
        observed_at=observed_at, title=title, summary=None, category=None,
        link=canonical_post_url(post_id),
    )


def _error_code(error: Exception) -> tuple[str, int]:
    status = getattr(error, "status", None)
    if status == 403:
        return "http_403", 3600
    if status == 429:
        headers = getattr(error, "headers", None) or {}
        value = headers.get("Retry-After", "")
        try:
            delay = max(0, min(int(value), 86400))
        except (TypeError, ValueError):
            delay = 0
        return "http_429", delay
    if type(status) is int and 400 <= status <= 599:
        return "http_error", 0
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return "timeout", 0
    return "source_error", 0


class RSSSource:
    def __init__(
        self, feed: FeedClient, core: CoreStore, state: SourceStore, *,
        url: str = "https://rss.nodeseek.com/",
        clock: Callable[[], datetime] = utc_now,
    ):
        self.url = _rss_url(url)
        self.feed = feed
        self.core = core
        self.state = state
        self.clock = clock
        self._poll_lock = asyncio.Lock()

    async def poll_once(self) -> PollReport:
        async with self._poll_lock:
            observed_at, now = _timestamp(self.clock)
            status = await self.state.status(Source.RSS)
            if not status.enabled:
                return PollReport(Source.RSS, "disabled")
            if now < status.retry_at:
                return PollReport(Source.RSS, "backoff")

            try:
                feed = await self.feed.fetch(self.url)
                entries = list(feed.entries)
                valid: list[SourceObservation] = []
                skipped = 0
                for entry in entries:
                    item = rss_observation(entry, observed_at)
                    if item is None:
                        skipped += 1
                    else:
                        valid.append(item)

                if not status.initialized:
                    # Initial RSS feed window is a baseline, never a backlog.
                    if await self.state.bootstrap_rss(
                        [item.post_id for item in valid], now=now
                    ):
                        return PollReport(Source.RSS, "baseline", len(entries), 0, skipped)

                already_seen = 0
                ingested = 0
                for item in reversed(valid):
                    if await self.state.rss_seen(item.post_id):
                        already_seen += 1
                        continue
                    # Checkpoint strictly follows CoreStore's durable observe.
                    # If remembering the ID fails, replay is idempotent.
                    await self.core.observe(item)
                    await self.state.remember_rss(item.post_id, now=now)
                    ingested += 1

                limit = getattr(self.feed, "max_entries_per_feed", None)
                if (type(limit) is int and limit > 0 and len(entries) >= limit
                        and valid and already_seen == 0):
                    # Feed rollover can hide posts; do not claim zero losses.
                    await self.state.mark_gap(Source.RSS, "rss_window_no_overlap")
                await self.state.mark_success(Source.RSS, now=now)
                return PollReport(Source.RSS, "ok", len(entries), ingested, skipped)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                code, retry_after = _error_code(error)
                await self.state.mark_failure(
                    Source.RSS, code, now=now, retry_after_seconds=retry_after
                )
                return PollReport(Source.RSS, "error")


class TelegramSource:
    """An authorized, preconfigured Telethon-compatible channel reader.

    This adapter never starts interactive login. Attach NewMessage events only
    after initial baseline; history replay is the safety net for the race.
    A live callback never advances the historical cursor: jumping to message
    105 must not hide missed messages 101..104.
    """

    def __init__(
        self, client: Any, core: CoreStore, state: SourceStore, *,
        channel: str = _CHANNEL, backfill_limit: int = 500,
        clock: Callable[[], datetime] = utc_now,
    ):
        if channel != _CHANNEL:
            raise ValueError("only official @nodeseekc is supported")
        if type(backfill_limit) is not int or not 1 <= backfill_limit <= 5000:
            raise ValueError("invalid backfill limit")
        self.client, self.core, self.state = client, core, state
        self.channel, self.limit, self.clock = channel, backfill_limit, clock
        self._sync_lock = asyncio.Lock()
        self._handler: Any = None
        self._event_builder: Any = None

    async def sync_once(self) -> PollReport:
        async with self._sync_lock:
            observed_at, now = _timestamp(self.clock)
            status = await self.state.status(Source.TELEGRAM)
            if not status.enabled:
                return PollReport(Source.TELEGRAM, "disabled")
            if now < status.retry_at:
                return PollReport(Source.TELEGRAM, "backoff")

            try:
                if hasattr(self.client, "is_user_authorized"):
                    if not await self.client.is_user_authorized():
                        await self.state.mark_failure(
                            Source.TELEGRAM, "auth_required", now=now
                        )
                        return PollReport(Source.TELEGRAM, "auth_required")
                if not status.initialized:
                    latest = await self.client.get_messages(self.channel, limit=1)
                    last_id = max((int(m.id) for m in latest), default=0)
                    if await self.state.bootstrap_telegram(last_id):
                        await self.state.mark_success(Source.TELEGRAM, now=now)
                        return PollReport(Source.TELEGRAM, "baseline", len(latest))

                # Query oldest first and require the entire bounded window.
                # Never move the cursor when the result overflows or fails.
                status = await self.state.status(Source.TELEGRAM)
                messages = []
                async for msg in self.client.iter_messages(
                    self.channel, min_id=status.cursor,
                    reverse=True, limit=self.limit + 1,
                ):
                    messages.append(msg)
                    if len(messages) > self.limit:
                        break
                if len(messages) > self.limit:
                    await self.state.mark_gap(Source.TELEGRAM, "backfill_limit")
                    await self.state.mark_failure(
                        Source.TELEGRAM, "backfill_limit", now=now
                    )
                    return PollReport(Source.TELEGRAM, "gap", len(messages))

                ordered = sorted(messages, key=lambda m: int(m.id))
                ingested = 0
                skipped = 0
                for msg in ordered:
                    item = telegram_observation(msg, observed_at)
                    if item is None:
                        skipped += 1
                        continue
                    await self.core.observe(item)
                    ingested += 1
                if ordered:
                    await self.state.advance_telegram(int(ordered[-1].id))
                await self.state.mark_success(Source.TELEGRAM, now=now)
                return PollReport(Source.TELEGRAM, "ok", len(ordered), ingested, skipped)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                code, _ = _error_code(error)
                if type(error).__name__ in {
                    "AuthKeyUnregisteredError", "SessionRevokedError",
                    "UnauthorizedError", "AuthKeyInvalidError",
                }:
                    code = "auth_required"
                await self.state.mark_failure(Source.TELEGRAM, code, now=now)
                return PollReport(Source.TELEGRAM, "error")

    async def on_new_message(self, message: Any) -> bool:
        """Persist live observation without changing the history cursor."""
        observed_at, now = _timestamp(self.clock)
        status = await self.state.status(Source.TELEGRAM)
        if not status.enabled or not status.initialized:
            return False
        try:
            item = telegram_observation(message, observed_at)
            if item is None:
                return False
            await self.core.observe(item)
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.state.mark_failure(
                Source.TELEGRAM, "ingest_failed", now=now
            )
            return False

    async def attach_telethon(self) -> None:
        """Wire a filtered NewMessage handler; client must already be authorized.

        A source runner must invoke sync_once() for the initial baseline,
        then attach and reconcile again. Credentials/session are kept entirely
        outside this module and never appear in exception logs.
        """
        if self._handler is not None:
            return
        from telethon import events

        entity = await self.client.get_input_entity(self.channel)

        async def handler(event: Any) -> None:
            await self.on_new_message(event.message)

        builder = events.NewMessage(chats=entity)
        self.client.add_event_handler(handler, builder)
        self._handler = handler
        self._event_builder = builder

    def detach_telethon(self) -> None:
        if self._handler is not None:
            self.client.remove_event_handler(self._handler, self._event_builder)
            self._handler = None
            self._event_builder = None


class SourceSupervisor:
    """Run independent source lifecycles; a source failure never stops another.

    This class is opt-in and is intentionally NOT called by app.main yet:
    switching legacy notifications to S2 tasks requires S4/cutover approval.
    """

    def __init__(
        self, rss: RSSSource, telegram: TelegramSource | None = None, *,
        rss_interval: int = 30, telegram_interval: int = 60,
    ):
        if min(rss_interval, telegram_interval) < 10:
            raise ValueError("source intervals must be >=10 seconds")
        self.rss, self.telegram = rss, telegram
        self.rss_interval, self.telegram_interval = rss_interval, telegram_interval

    @staticmethod
    async def _wait(stop: asyncio.Event, seconds: int) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def run_forever(self, stop: asyncio.Event) -> None:
        async def loop(source: RSSSource | TelegramSource, interval: int) -> None:
            while not stop.is_set():
                try:
                    await (source.poll_once() if isinstance(source, RSSSource)
                           else source.sync_once())
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Preserve the sibling source even if state/storage fails.
                    # Caller can inspect health; no exception text is logged.
                    pass
                await self._wait(stop, interval)

        tasks = [asyncio.create_task(loop(self.rss, self.rss_interval))]
        if self.telegram is not None:
            async def telegram_loop() -> None:
                tg = self.telegram
                connected = False
                attached = False
                try:
                    while not stop.is_set():
                        try:
                            status = await tg.state.status(Source.TELEGRAM)
                            if not status.enabled:
                                if attached:
                                    tg.detach_telethon()
                                    attached = False
                                if connected:
                                    await tg.client.disconnect()
                                    connected = False
                            else:
                                if not connected and hasattr(tg.client, "connect"):
                                    await tg.client.connect()
                                    connected = True
                                await tg.sync_once()
                                status = await tg.state.status(Source.TELEGRAM)
                                if (status.initialized and not attached
                                        and hasattr(tg.client, "add_event_handler")):
                                    # Attach after the baseline; reconcile again
                                    # to recover updates arriving in the gap.
                                    await tg.attach_telethon()
                                    attached = True
                                    await tg.sync_once()
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            # Never expose Session/credential text. Independently
                            # back off the TG reader while RSS keeps operating.
                            _, now = _timestamp(tg.clock)
                            await tg.state.mark_failure(
                                Source.TELEGRAM, "source_error", now=now
                            )
                        await self._wait(stop, self.telegram_interval)
                finally:
                    if attached:
                        tg.detach_telethon()
                    if connected:
                        await tg.client.disconnect()

            tasks.append(asyncio.create_task(telegram_loop()))
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
