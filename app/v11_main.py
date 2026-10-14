"""Gate B opt-in V1.1 single-process entrypoint.

NOT referenced by the legacy Dockerfile or compose. Never starts unless an
operator explicitly supplies --run + SEEKPULSE_V11_ENABLE=1; production
credentials, migration, VPS and live notifications remain separately gated.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.bot import build_application
from app.config import Settings
from app.db import Database
from app.delivery import CoreStore
from app.gate_b_dispatch import ObservationDispatcher
from app.gate_b_targets import GateBTargetStore
from app.instance_lock import database_owner_lock
from app.main import configure_logging
from app.maintenance import verify_backup
from app.notifiers import AppriseNotifier, TelegramNotifier
from app.route_store import RouteStore
from app.rss import FeedClient
from app.source_adapters import RSSSource, SourceSupervisor, TelegramSource
from app.source_state import SourceStore
from app.web import create_web_app
from app.web_auth import AdminWebConfig
from app.worker import DeliveryWorker

_REF = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def push_secret(reference: str) -> str | None:
    if not isinstance(reference, str) or not _REF.fullmatch(reference):
        return None
    return os.getenv("SEEKPULSE_PUSH_" + reference)


def _telegram_session_lock_path() -> Path | None:
    """Lock the actual Telethon SQLite file, even across different DB paths."""
    raw = os.getenv("SEEKPULSE_TG_SESSION")
    if not raw:
        return None
    # Telethon appends .session when omitted. Require the explicit real name
    # so alternate spellings cannot acquire distinct lock-file identities.
    path = Path(raw)
    if (not raw.endswith(".session") or path.is_symlink()
            or not path.is_file()):
        raise RuntimeError("telegram_session_file_invalid")
    return path


@dataclass(frozen=True, slots=True)
class GateBComponents:
    application: Any
    sources: Any
    dispatcher: Any
    worker: Any
    web_server: Any


async def supervise(components: GateBComponents, stop: asyncio.Event) -> None:
    """Keep Bot/source/queue/Web in ONE loop; fail closed on component exit."""
    bot = components.application
    initialized = started = polling = False
    tasks: list[asyncio.Task] = []
    stop_task: asyncio.Task | None = None
    try:
        await bot.initialize()
        initialized = True
        await bot.start()
        started = True
        if bot.updater is None:
            raise RuntimeError("bot_updater_missing")
        await bot.updater.start_polling()
        polling = True
        tasks = [
            asyncio.create_task(components.sources.run_forever(stop)),
            asyncio.create_task(components.dispatcher.run_forever(stop)),
            asyncio.create_task(components.worker.run_forever(stop)),
            asyncio.create_task(components.web_server.serve()),
        ]
        stop_task = asyncio.create_task(stop.wait())
        finished, _ = await asyncio.wait(
            [*tasks, stop_task], return_when=asyncio.FIRST_COMPLETED
        )
        if stop_task not in finished and not stop.is_set():
            # No background loop may vanish while the others keep sending.
            for task in finished:
                if not task.cancelled():
                    with suppress(Exception):
                        task.result()
            raise RuntimeError("gate_b_component_stopped")
    finally:
        stop.set()
        if hasattr(components.web_server, "should_exit"):
            components.web_server.should_exit = True
        if stop_task is not None:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=8)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if polling:
            await bot.updater.stop()
        if started:
            await bot.stop()
        if initialized:
            await bot.shutdown()


async def _stores(path: Path):
    db = Database(path)
    core = CoreStore(path)
    sources = SourceStore(path)
    routes = RouteStore(path)
    registry = GateBTargetStore(path)
    dispatcher = ObservationDispatcher(path, core, routes)
    # No migration in --run; a separate, approved --prepare is mandatory.
    await db.init()
    await core.init()
    await sources.init()
    await routes.init()
    await dispatcher.init()
    return db, core, sources, routes, registry, dispatcher


async def prepare_cutover(settings: Settings, backup: Path) -> int:
    """Offline-only explicit schema+cursor preparation, with verified snapshot."""
    if not backup or not backup.is_dir():
        raise RuntimeError("verified_backup_bundle_required")
    verify_backup(backup)
    async with asyncio.timeout(20):
        with database_owner_lock(settings.database_path):
            db, core, sources, routes, registry, dispatcher = await _stores(
                settings.database_path
            )
            await registry.init()
            await registry.assert_live_safe()
            return await dispatcher.prime()


async def build_components(settings: Settings) -> GateBComponents:
    db, core, sources, routes, registry, dispatcher = await _stores(
        settings.database_path
    )
    await registry.assert_live_safe()
    await dispatcher.cursor()  # NO auto Prime / historical replay.
    await core.recover(now=int(time.time()))
    config = AdminWebConfig.from_environment()

    from app.domain import Source

    tg_reader = None
    api_id = os.getenv("SEEKPULSE_TG_API_ID")
    api_hash = os.getenv("SEEKPULSE_TG_API_HASH")
    session = os.getenv("SEEKPULSE_TG_SESSION")
    if any((api_id, api_hash, session)):
        if (not all((api_id, api_hash, session))
                or not api_id.isascii() or not api_id.isdecimal()
                or _telegram_session_lock_path() is None):
            raise RuntimeError("telegram_session_configuration_incomplete")
        from telethon import TelegramClient

        tg_reader = TelegramSource(
            TelegramClient(session, int(api_id), api_hash),
            core, sources, max_message_age_seconds=1800,
        )
    elif (await sources.status(Source.TELEGRAM)).enabled:
        raise RuntimeError("telegram_enabled_but_not_configured")

    # The user must explicitly approve real credentials/running this entrypoint.
    bot = build_application(settings, db)
    apprise = AppriseNotifier(push_secret)
    # Fail BEFORE starting any send loop if an ENABLED push target lacks
    # protected environment configuration or official HTTPS endpoint.
    await registry.assert_live_safe(resolver=push_secret)
    worker = DeliveryWorker(core, routes, TelegramNotifier(bot.bot), apprise)
    rss = RSSSource(
        FeedClient(settings.http_timeout_seconds, settings.max_entries_per_feed),
        core, sources, url=settings.rss_url, max_entry_age_seconds=1800,
    )
    supervisor = SourceSupervisor(rss, tg_reader)
    web = create_web_app(settings.database_path, config)
    import uvicorn

    port_text = os.getenv("SEEKPULSE_WEB_PORT", "8765")
    if not port_text.isascii() or not port_text.isdecimal():
        raise RuntimeError("invalid_web_port")
    port = int(port_text)
    if not 1024 <= port <= 65535:
        raise RuntimeError("invalid_web_port")
    server = uvicorn.Server(uvicorn.Config(
        web, host="127.0.0.1", port=port, loop="asyncio", lifespan="on",
        workers=1, proxy_headers=False, access_log=False,
        log_level="warning",
    ))
    return GateBComponents(bot, supervisor, dispatcher, worker, server)


async def _run_live(settings: Settings) -> None:
    with ExitStack() as locks:
        locks.enter_context(database_owner_lock(settings.database_path))
        session = _telegram_session_lock_path()
        if session is not None:
            locks.enter_context(database_owner_lock(session))
        components = await build_components(settings)
        await supervise(components, asyncio.Event())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SeekPulse V1.1 opt-in runner")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--prepare", action="store_true", help="Versioned offline schema+cursor prime")
    g.add_argument("--run", action="store_true", help="Explicitly start V1.1 single process")
    args = parser.parse_args(argv)
    if os.getenv("SEEKPULSE_V11_ENABLE") != "1":
        raise RuntimeError("v11_not_explicitly_enabled")
    settings = Settings.load()
    configure_logging(settings.log_level)
    if args.prepare:
        backup = os.getenv("SEEKPULSE_VERIFIED_BACKUP_BUNDLE")
        if not backup:
            raise RuntimeError("verified_backup_bundle_required")
        asyncio.run(prepare_cutover(settings, Path(backup)))
        return 0
    asyncio.run(_run_live(settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
