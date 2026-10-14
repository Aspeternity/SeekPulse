from __future__ import annotations

import asyncio
import logging

import aiosqlite
from contextlib import suppress

from app.bot import build_application
from app.config import Settings
from app.db import Database
from app.instance_lock import database_owner_lock
from app.poller import FeedPoller


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    # Telegram requests include the bot token in the URL, so keep HTTP client logs quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def serve() -> None:
    settings = Settings.load()
    configure_logging(settings.log_level)
    # Both upgraded legacy and V1.1 use the same Linux file lock.
    with database_owner_lock(settings.database_path):
        await _serve_locked(settings)


async def _serve_locked(settings: Settings) -> None:
    # Do not run FeedPoller on a migrated V1.1 database. S2 sent tasks are
    # intentionally not mirrored to legacy delivery_history; a rollback
    # must use the verified pre-migration SQLite backup at a new path.
    async with aiosqlite.connect(settings.database_path) as connection:
        row = await (await connection.execute(
            """SELECT 1 FROM sqlite_master WHERE type='table'
               AND name='gate_b_schema_meta'"""
        )).fetchone()
        if row is not None:
            raise RuntimeError("legacy_runner_denied_on_v11_database")
    db = Database(settings.database_path)
    await db.init()

    poller = FeedPoller(settings, db)
    application = build_application(settings, db)
    await application.initialize()
    await application.start()
    poller_task = asyncio.create_task(poller.run_forever(application.bot))
    await application.updater.start_polling()

    try:
        await asyncio.Future()
    finally:
        await poller.stop()
        poller_task.cancel()
        with suppress(asyncio.CancelledError):
            await poller_task
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
