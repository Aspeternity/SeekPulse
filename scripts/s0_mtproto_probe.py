#!/usr/bin/env python3
"""S0-only, read-only Telethon feasibility probe. Never sends messages.

Runs ONLY in an operator-controlled test environment, never GitHub Actions.
Stores no message text, username, credentials or auth codes in observations.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any

try:
    from scripts.s0_public_probe import post_id_from_url
except ModuleNotFoundError:
    from s0_public_probe import post_id_from_url

CHANNEL = "nodeseekc"
DEFAULT_STATE = Path.home() / ".local" / "share" / "seekpulse-s0"
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
RECONCILE_LIMIT = 500


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def post_id_from_message(msg: Any) -> str | None:
    """Treat raw text and hidden text_url entities equally; reject other hosts."""
    candidates: list[str] = []
    for entity in getattr(msg, "entities", None) or []:
        url = getattr(entity, "url", None)
        if isinstance(url, str):
            candidates.append(url)
    candidates.extend(URL_PATTERN.findall(getattr(msg, "raw_text", None) or ""))
    for candidate in candidates:
        pid = post_id_from_url(candidate.rstrip("),.;!?]}\u3002\uff01\uff1f"))
        if pid is not None:
            return pid
    return None


def message_time_utc(msg: Any) -> str | None:
    t = getattr(msg, "date", None)
    if not isinstance(t, datetime):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def private_state_dir(raw: Path) -> Path:
    folder = raw.expanduser().resolve()
    repository = Path(__file__).resolve().parents[1]
    if folder == repository or repository in folder.parents:
        raise ValueError("Test session and records must be OUTSIDE the Git repository")
    if raw.expanduser().is_symlink():
        raise ValueError("State directory symlink is not allowed")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(folder, 0o700)
    return folder


@contextmanager
def single_probe(folder: Path):
    """Fail closed on concurrent use of the same Telethon .session."""
    lock = folder / "probe.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Test probe already running or stale lock; inspect processes first") from exc
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


class ObservationStore:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path, timeout=10)
        with self.conn:
            self.conn.execute("""CREATE TABLE IF NOT EXISTS seen (
                message_id INTEGER PRIMARY KEY,
                post_id TEXT,
                message_utc TEXT,
                first_seen_utc TEXT NOT NULL,
                observed_via TEXT NOT NULL
            )""")
            self.conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self.conn.execute("""CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY,
                observed_utc TEXT NOT NULL,
                category TEXT NOT NULL
            )""")

    def close(self) -> None:
        self.conn.close()

    def cursor(self) -> int | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key='last_scanned_id'").fetchone()
        return int(row[0]) if row else None

    def set_cursor(self, value: int) -> None:
        with self.conn:
            self.conn.execute("""INSERT INTO meta (key,value) VALUES ('last_scanned_id',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (str(value),))

    def insert(self, msg: Any, via: str) -> bool:
        pid = post_id_from_message(msg)
        with self.conn:
            result = self.conn.execute("""INSERT OR IGNORE INTO seen
                (message_id, post_id, message_utc, first_seen_utc, observed_via)
                VALUES (?,?,?,?,?)""",
                (int(msg.id), pid, message_time_utc(msg), utc_now(), via),
            )
        return result.rowcount == 1

    def warn(self, category: str) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO warnings (observed_utc, category) VALUES (?,?)", (utc_now(), category))

    def report(self) -> dict[str, Any]:
        counts = self.conn.execute("SELECT observed_via, COUNT(*) FROM seen GROUP BY observed_via").fetchall()
        post_count = self.conn.execute("SELECT COUNT(*) FROM seen WHERE post_id IS NOT NULL").fetchone()[0]
        seen_count = self.conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
        last_id = self.conn.execute("SELECT MAX(message_id) FROM seen").fetchone()[0]
        warns = self.conn.execute("SELECT category, COUNT(*) FROM warnings GROUP BY category").fetchall()
        return {"schema_version": 1, "status": "S0_TEST_OBSERVATIONS_ONLY",
                "generated_utc": utc_now(), "channel": "@nodeseekc",
                "last_scanned_message_id": self.cursor(), "largest_observed_message_id": last_id,
                "total_message_ids": seen_count, "recognized_post_ids": post_count,
                "first_observed_via": dict(counts), "warnings": dict(warns),
                "real_time_latency_verified": False,
                "note": "Message timestamps are Telegram timestamps, not NodeSeek forum publish times."}


async def initialize_baseline(client: Any, channel: Any, store: ObservationStore) -> bool:
    """On first use, skip pre-existing history. Later runs always reconcile."""
    if store.cursor() is not None:
        return False
    latest = await client.get_messages(channel, limit=1)
    baseline = int(latest[0].id) if latest else 0
    store.set_cursor(baseline)
    return True


async def reconcile(client: Any, channel: Any, store: ObservationStore,
                    limit: int = RECONCILE_LIMIT) -> dict[str, Any]:
    """Read history after prior completed scan; never advance on overflow/error."""
    start = store.cursor()
    if start is None:
        raise ValueError("Need initial baseline before reconciliation")
    batch = []
    async for msg in client.iter_messages(channel, min_id=start, reverse=True, limit=limit + 1):
        batch.append(msg)
    if len(batch) > limit:
        store.warn("BACKFILL_LIMIT_EXCEEDED")
        return {"status": "INCOMPLETE_CURSOR_UNCHANGED", "retrieved": len(batch), "cursor": start}
    new = sum(store.insert(msg, "history") for msg in batch)
    if batch:
        store.set_cursor(max(start, *(int(m.id) for m in batch)))
    return {"status": "ok", "retrieved": len(batch), "new": new,
            "cursor": store.cursor()}


def credential_pair() -> tuple[int, str]:
    raw_id = os.environ.get("SEEKPULSE_TG_API_ID") or input("Telegram API ID: ").strip()
    api_hash = os.environ.get("SEEKPULSE_TG_API_HASH") or getpass.getpass("API Hash (hidden): ").strip()
    if not raw_id.isdigit() or not api_hash:
        raise ValueError("Missing valid API ID or API Hash")
    return int(raw_id), api_hash


async def run_client(command: str, folder: Path, minutes: int) -> int:
    # Lazy import: offline tests and local report require no Telethon install.
    from telethon import TelegramClient, events

    api_id, api_hash = credential_pair()
    client = TelegramClient(str(folder / "s0_user"), api_id, api_hash, auto_reconnect=True)
    store = ObservationStore(folder / "observations.sqlite3")
    try:
        await client.connect()
        if command == "auth":
            await client.start(
                phone=lambda: input("Test account phone (entered locally): ").strip(),
                code_callback=lambda: getpass.getpass("Telegram login code (hidden): ").strip(),
                password=lambda: getpass.getpass("2FA password (hidden): "),
            )
            if not await client.is_user_authorized():
                raise RuntimeError("Auth not confirmed")
            print("AUTH_READY: Session saved privately. Join @nodeseekc in Telegram app if not already joined.")
            return 0
        if not await client.is_user_authorized():
            raise RuntimeError("Please run 'auth' first using a dedicated test account")
        channel = await client.get_input_entity(CHANNEL)
        first = await initialize_baseline(client, channel, store)
        if first:
            print("NEW_BASELINE: existing channel history skipped (no historical notification).")

        startup = {"catching_up": True}

        @client.on(events.NewMessage(chats=channel))
        async def on_message(event: Any) -> None:
            # Conservative label: catch_up callbacks are not proven live events.
            kind = "catchup_callback" if startup["catching_up"] else "event_callback"
            store.insert(event.message, kind)

        # catch_up only after registering handler; audit history too because
        # updates can be unavailable after long offline windows.
        await client.catch_up()
        startup["catching_up"] = False
        first_pass = await reconcile(client, channel, store)
        print("INITIAL_RECONCILE:", json.dumps(first_pass, sort_keys=True))
        deadline = time.monotonic() + minutes * 60
        while time.monotonic() < deadline:
            await asyncio.sleep(min(60.0, max(0.0, deadline - time.monotonic())))
            try:
                state = await reconcile(client, channel, store)
                print("RECONCILE:", json.dumps(state, sort_keys=True))
            except Exception as exc:
                store.warn("RECONCILE_" + type(exc).__name__)
                print("RECONCILE_FAILED:", type(exc).__name__)
        print("LOCAL_TEST_REPORT:", json.dumps(store.report(), sort_keys=True))
        return 0
    finally:
        await client.disconnect()
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("auth", "listen", "report"))
    parser.add_argument("--minutes", type=int, default=15, help="Listen duration (1..180); never permanent")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args(argv)
    if not 1 <= args.minutes <= 180:
        parser.error("--minutes must be 1..180")
    os.umask(0o077)
    try:
        folder = private_state_dir(args.state_dir)
        if args.command == "report":
            path = folder / "observations.sqlite3"
            if not path.is_file():
                print("NO_OBSERVATIONS: Run auth/listen in your test environment first.")
                return 2
            store = ObservationStore(path)
            try:
                print(json.dumps(store.report(), ensure_ascii=False, indent=2))
                return 0
            finally:
                store.close()
        with single_probe(folder):
            return asyncio.run(run_client(args.command, folder, args.minutes))
    except (Exception, KeyboardInterrupt) as exc:
        print("S0_PROBE_STOPPED:", type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
