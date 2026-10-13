#!/usr/bin/env python3
"""S0-02 only: read-only, same-host MTProto event vs public RSS first observation.

Not a bot, production service, crawler, or forum publication latency meter.
Uses S0-01's existing Telegram Session, lock and strict NodeSeek link parser.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

try:
    from scripts.s0_mtproto_probe import (
        CHANNEL, DEFAULT_STATE, credential_pair, post_id_from_message,
        private_state_dir, single_probe, utc_now,
    )
    from scripts.s0_public_probe import MAX_BYTES, RSS_URL, rss_ids
except ModuleNotFoundError:
    from s0_mtproto_probe import (
        CHANNEL, DEFAULT_STATE, credential_pair, post_id_from_message,
        private_state_dir, single_probe, utc_now,
    )
    from s0_public_probe import MAX_BYTES, RSS_URL, rss_ids

RSS_USER_AGENT = "SeekPulse-S0-02-ReadOnlyResearch/0.1"
TG_BACKFILL_LIMIT = 500


def fetch_rss(timeout: float = 12.0) -> dict:
    """Fetch only the fixed, public RSS URL; never keep text or exceptions."""
    began = time.monotonic()
    result = {"status": "error", "ids": set(), "error_type": None, "http_status": None}
    try:
        request = Request(RSS_URL, headers={"User-Agent": RSS_USER_AGENT})
        with urlopen(request, timeout=timeout) as response:
            result["http_status"] = response.status
            payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError("oversize")
        ids = set(rss_ids(payload)["unique_post_ids"])
        if not ids:
            raise ValueError("no recognized entries")
        result.update(status="ok", ids=ids)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError, ElementTree.ParseError) as exc:
        result["error_type"] = type(exc).__name__
        if isinstance(exc, HTTPError):
            result["http_status"] = exc.code
    result["observed_utc"] = utc_now()
    result["duration_ms"] = round((time.monotonic() - began) * 1000)
    return result


def seconds_between(later: str, earlier: str) -> float:
    return (datetime.fromisoformat(later) - datetime.fromisoformat(earlier)).total_seconds()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = (len(values) - 1) * fraction
    low = int(idx)
    if low == len(values) - 1:
        return round(values[low], 3)
    weight = idx - low
    return round(values[low] * (1 - weight) + values[low + 1] * weight, 3)


class ComparisonStore:
    """One SQLite writer, with short synchronous transactions in the event loop."""

    def __init__(self, path: Path) -> None:
        self.conn = sqlite3.connect(path, timeout=15)
        with self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_seen (
                    source TEXT NOT NULL, post_id TEXT NOT NULL,
                    first_seen_utc TEXT NOT NULL, method TEXT NOT NULL,
                    PRIMARY KEY(source, post_id)
                );
                CREATE TABLE IF NOT EXISTS tg_messages (
                    message_id INTEGER PRIMARY KEY,
                    post_id TEXT, first_seen_utc TEXT NOT NULL, method TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rss_samples (
                    id INTEGER PRIMARY KEY, observed_utc TEXT NOT NULL,
                    status TEXT NOT NULL, entry_count INTEGER,
                    duration_ms INTEGER NOT NULL, http_status INTEGER,
                    error_type TEXT, overlap_previous INTEGER
                );
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY, observed_utc TEXT NOT NULL,
                    category TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY, started_utc TEXT NOT NULL,
                    finished_utc TEXT, duration_seconds REAL,
                    rss_interval_seconds INTEGER NOT NULL,
                    planned_seconds REAL NOT NULL, completed INTEGER NOT NULL DEFAULT 0
                );
            """)

    def close(self) -> None:
        self.conn.close()

    def get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
        )

    def set(self, key: str, value: str) -> None:
        with self.conn:
            self._set(key, value)

    def warn(self, category: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO warnings(observed_utc,category) VALUES (?,?)",
                (utc_now(), category),
            )

    def observe_tg(self, message, method: str, when: str | None = None) -> bool:
        """Return True for a newly persisted Telegram message_id."""
        when = when or utc_now()
        pid = post_id_from_message(message)
        with self.conn:
            inserted = self.conn.execute(
                "INSERT OR IGNORE INTO tg_messages "
                "(message_id,post_id,first_seen_utc,method) VALUES (?,?,?,?)",
                (int(message.id), pid, when, method),
            ).rowcount == 1
            if inserted and pid:
                self.conn.execute(
                    "INSERT OR IGNORE INTO source_seen "
                    "(source,post_id,first_seen_utc,method) VALUES ('tg',?,?,?)",
                    (pid, when, method),
                )
        return inserted

    def observe_rss(self, response: dict, *, baseline: bool = False,
                    resumed: bool = False) -> dict:
        """Record one complete sample; never infer absence after HTTP failure."""
        when = response["observed_utc"]
        if response["status"] != "ok":
            with self.conn:
                self.conn.execute(
                    "INSERT INTO rss_samples "
                    "(observed_utc,status,entry_count,duration_ms,http_status,error_type,overlap_previous) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (when, "error", None, response["duration_ms"],
                     response.get("http_status"), response.get("error_type"), None),
                )
            return {"status": "error", "error_type": response.get("error_type"),
                    "http_status": response.get("http_status")}
        ids = set(response["ids"])
        previous_raw = self.get("rss_last_ids")
        previous = set(json.loads(previous_raw)) if previous_raw is not None else None
        overlap = len(ids & previous) if previous else None
        method = "rss_baseline" if baseline else ("rss_resume" if resumed else "rss_poll")
        added = 0
        with self.conn:
            for pid in sorted(ids):
                added += self.conn.execute(
                    "INSERT OR IGNORE INTO source_seen "
                    "(source,post_id,first_seen_utc,method) VALUES ('rss',?,?,?)",
                    (pid, when, method),
                ).rowcount
            self.conn.execute(
                "INSERT INTO rss_samples "
                "(observed_utc,status,entry_count,duration_ms,http_status,error_type,overlap_previous) "
                "VALUES (?,?,?,?,?,?,?)",
                (when, "ok", len(ids), response["duration_ms"],
                 response.get("http_status"), None, overlap),
            )
            if previous is not None and overlap == 0:
                self.conn.execute(
                    "INSERT INTO warnings(observed_utc,category) VALUES (?,?)",
                    (when, "RSS_WINDOW_NO_OVERLAP"),
                )
            self._set("rss_last_ids", json.dumps(sorted(ids)))
            if baseline:
                self._set("rss_initialized", "1")
        return {"status": "ok", "entries": len(ids), "new_ids": added,
                "overlap": overlap, "method": method}

    def begin_run(self, interval: int, planned_seconds: float) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO runs(started_utc,rss_interval_seconds,planned_seconds) "
                "VALUES (?,?,?)",
                (utc_now(), interval, planned_seconds),
            )
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, duration: float, completed: bool) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET finished_utc=?,duration_seconds=?,completed=? WHERE id=?",
                (utc_now(), max(0.0, duration), int(completed), run_id),
            )

    def report(self) -> dict:
        seen = dict(self.conn.execute(
            "SELECT source,COUNT(*) FROM source_seen "
            "WHERE method != 'rss_baseline' GROUP BY source"
        ).fetchall())
        matched = self.conn.execute("""
            SELECT tg.post_id, tg.first_seen_utc, rss.first_seen_utc,
                   tg.method, rss.method
            FROM source_seen AS tg
            JOIN source_seen AS rss USING(post_id)
            WHERE tg.source='tg' AND rss.source='rss'
                  AND rss.method != 'rss_baseline'
        """).fetchall()
        clean = [
            seconds_between(rss_ts, tg_ts)
            for _, tg_ts, rss_ts, tg_method, rss_method in matched
            if tg_method == "tg_live" and rss_method == "rss_poll"
        ]
        # Exclude RSS's initial pre-existing feed IDs from source-only comparison.
        valid_tg = set(r[0] for r in self.conn.execute("""
            SELECT post_id FROM source_seen
            WHERE source='tg' AND post_id NOT IN (
                SELECT post_id FROM source_seen
                WHERE source='rss' AND method='rss_baseline'
            )
        """))
        valid_rss = set(r[0] for r in self.conn.execute("""
            SELECT post_id FROM source_seen
            WHERE source='rss' AND method!='rss_baseline'
        """))
        poll_counts = dict(self.conn.execute(
            "SELECT status,COUNT(*) FROM rss_samples GROUP BY status"
        ).fetchall())
        gap_count = self.conn.execute(
            "SELECT COUNT(*) FROM warnings WHERE category='RSS_WINDOW_NO_OVERLAP'"
        ).fetchone()[0]
        warning_counts = dict(self.conn.execute(
            "SELECT category,COUNT(*) FROM warnings GROUP BY category"
        ).fetchall())
        run_rows = self.conn.execute(
            "SELECT duration_seconds,finished_utc,completed,rss_interval_seconds FROM runs"
        ).fetchall()
        completed_seconds = [
            duration for duration, end, ok, _ in run_rows
            if end is not None and ok and duration is not None
        ]
        interval_values = sorted(set(row[3] for row in run_rows))
        uninterrupted = max(completed_seconds, default=0)
        unrecognized_tg = self.conn.execute(
            "SELECT COUNT(*) FROM tg_messages WHERE post_id IS NULL"
        ).fetchone()[0]
        tg_methods = dict(self.conn.execute(
            "SELECT method,COUNT(*) FROM tg_messages GROUP BY method"
        ).fetchall())
        return {
            "schema_version": 1,
            "status": "S0_ONLY_SAME_HOST_FIRST_OBSERVATION",
            "generated_utc": utc_now(),
            "sources": ["telegram_mtproto", "rss"],
            "configured_rss_intervals_seconds": interval_values,
            "telegram_observed_messages": sum(tg_methods.values()),
            "telegram_message_methods": tg_methods,
            "telegram_unrecognized_message_count": unrecognized_tg,
            "eligible_first_seen_by_source": seen,
            "matched_nonbaseline_post_ids": len(matched),
            "matched_live_tg_and_normal_rss_poll": len(clean),
            "clean_observed_rss_minus_tg_seconds": {
                "p50": percentile(clean, .5),
                "p95": percentile(clean, .95),
                "tg_seen_before_rss": sum(x > 0 for x in clean),
                "rss_seen_before_tg": sum(x < 0 for x in clean),
                "within_one_second": sum(abs(x) < 1 for x in clean),
            },
            "provisional_source_only_post_ids": {
                "tg_only": len(valid_tg - valid_rss),
                "rss_only": len(valid_rss - valid_tg),
            },
            "rss_poll_results": poll_counts,
            "rss_window_no_overlap_count": gap_count,
            "warnings": warning_counts,
            "completed_runs": len(completed_seconds),
            "interrupted_runs_or_in_progress": len(run_rows) - len(completed_seconds),
            "longest_completed_continuous_hours": round(uninterrupted / 3600, 3),
            "continuous_24h_observed": uninterrupted >= 24 * 3600,
            "interpretation": (
                "First observed on one machine, NOT original NodeSeek publish time; "
                "RSS event time is bounded by polling and network latency. "
                "Backfilled, resumed and RSS-baseline posts are excluded from "
                "clean time comparisons. Source-only counts are provisional; "
                "recent posts, feed rollover, outages, and deletion censor coverage."
            ),
        }


async def reconcile_tg(client, channel, store: ComparisonStore,
                       limit: int = TG_BACKFILL_LIMIT) -> dict:
    start_raw = store.get("tg_cursor")
    if start_raw is None:
        raise RuntimeError("TG_BASELINE_NOT_INITIALIZED")
    start = int(start_raw)
    batch = []
    async for message in client.iter_messages(
        channel, min_id=start, reverse=True, limit=limit + 1
    ):
        batch.append(message)
    if len(batch) > limit:
        store.warn("TG_BACKFILL_LIMIT_EXCEEDED")
        return {"status": "overflow", "retrieved": len(batch), "cursor": start}
    new = sum(store.observe_tg(message, "tg_history") for message in batch)
    if batch:
        store.set("tg_cursor", str(max(start, *(int(m.id) for m in batch))))
    return {"status": "ok", "retrieved": len(batch),
            "new_message_ids": new, "cursor": int(store.get("tg_cursor"))}


async def run_probe(folder: Path, minutes: int, rss_interval: int, timeout: float) -> None:
    from telethon import TelegramClient, events

    api_id, api_hash = credential_pair()
    store = ComparisonStore(folder / "s0_02_comparison.sqlite3")
    client = TelegramClient(str(folder / "s0_user"), api_id, api_hash, auto_reconnect=True)
    run_id = None
    started = None
    finished_ok = False
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("S0-01_AUTH_REQUIRED")
        channel = await client.get_input_entity(CHANNEL)
        seeded_rss = store.get("rss_initialized") == "1"
        if not seeded_rss:
            baseline = await asyncio.to_thread(fetch_rss, timeout)
            details = store.observe_rss(baseline, baseline=True)
            if details["status"] != "ok":
                raise RuntimeError("RSS_INITIAL_BASELINE_FAILED")
            print("[BASELINE] rss_entries=" + str(details["entries"]) +
                  " pre-existing RSS IDs excluded from comparison", flush=True)
        if store.get("tg_cursor") is None:
            latest = await client.get_messages(channel, limit=1)
            store.set("tg_cursor", str(int(latest[0].id) if latest else 0))
            print("[BASELINE] tg_cursor=" + str(store.get("tg_cursor")) +
                  " historical TG messages skipped", flush=True)
        resumed = bool(store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        cutoff = datetime.now(timezone.utc)
        startup = {"catching_up": True}

        @client.on(events.NewMessage(chats=channel))
        async def on_tg_message(event) -> None:
            when = utc_now()
            method = "tg_catchup" if startup["catching_up"] else "tg_live"
            posted = getattr(event.message, "date", None)
            if method == "tg_live" and isinstance(posted, datetime):
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
                if posted < cutoff:
                    method = "tg_catchup"
            fresh = store.observe_tg(event.message, method, when)
            if fresh:
                pid = post_id_from_message(event.message) or "UNRECOGNIZED"
                print(f"[TG_{'LIVE' if method == 'tg_live' else 'CATCHUP'}] "
                      f"message_id={int(event.message.id)} post_id={pid} "
                      f"observed_utc={when}", flush=True)

        await client.catch_up()
        startup["catching_up"] = False
        first = await reconcile_tg(client, channel, store)
        print("[TG_STARTUP_CHECK]", json.dumps(first, sort_keys=True), flush=True)
        if first["status"] != "ok":
            raise RuntimeError("TG_BACKFILL_LIMIT_EXCEEDED")

        run_id = store.begin_run(rss_interval, minutes * 60)
        started = time.monotonic()
        deadline = started + minutes * 60

        async def tg_loop() -> None:
            while time.monotonic() < deadline:
                await asyncio.sleep(min(60.0, max(0.0, deadline - time.monotonic())))
                if time.monotonic() >= deadline:
                    break
                try:
                    result = await reconcile_tg(client, channel, store)
                    print("[TG_CHECK]", json.dumps(result, sort_keys=True), flush=True)
                    if result["status"] != "ok":
                        raise RuntimeError("TG_BACKFILL_LIMIT_EXCEEDED")
                except RuntimeError:
                    raise
                except Exception as exc:
                    store.warn("TG_RECONCILE_" + type(exc).__name__)
                    print("[TG_CHECK_ERROR]", type(exc).__name__, flush=True)

        async def rss_loop() -> None:
            first_poll = True
            next_wait = rss_interval
            while time.monotonic() < deadline:
                # After an initial baseline wait for the normal poll interval.
                wait = next_wait if not (first_poll and seeded_rss) else 0
                first_resume_poll = first_poll and resumed
                first_poll = False
                await asyncio.sleep(min(wait, max(0.0, deadline - time.monotonic())))
                if time.monotonic() >= deadline:
                    break
                sample = await asyncio.to_thread(fetch_rss, timeout)
                details = store.observe_rss(sample, resumed=first_resume_poll)
                next_wait = (min(600, max(rss_interval, next_wait * 2))
                             if details["status"] != "ok" else rss_interval)
                print("[RSS]", json.dumps(details, sort_keys=True), flush=True)

        await asyncio.gather(tg_loop(), rss_loop())
        finished_ok = True
    finally:
        if run_id is not None and started is not None:
            store.finish_run(run_id, time.monotonic() - started, finished_ok)
            print("S0_02_REPORT:", json.dumps(store.report(), sort_keys=True), flush=True)
        await client.disconnect()
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["listen", "report"])
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument("--minutes", type=int)
    duration.add_argument("--hours", type=int)
    parser.add_argument("--rss-interval", type=int, default=60)
    parser.add_argument("--rss-timeout", type=float, default=12.0)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args(argv)
    if args.minutes is not None and not 1 <= args.minutes <= 180:
        parser.error("--minutes must be 1..180")
    if args.hours is not None and not 1 <= args.hours <= 72:
        parser.error("--hours must be 1..72")
    if not 60 <= args.rss_interval <= 600:
        parser.error("--rss-interval must be 60..600 seconds")
    if not 2 <= args.rss_timeout <= 30:
        parser.error("--rss-timeout must be 2..30 seconds")
    minutes = args.minutes if args.minutes is not None else (args.hours or 24) * 60
    try:
        folder = private_state_dir(args.state_dir)
        if args.command == "report":
            path = folder / "s0_02_comparison.sqlite3"
            if not path.is_file():
                print("NO_S0_02_OBSERVATIONS")
                return 2
            store = ComparisonStore(path)
            try:
                print(json.dumps(store.report(), ensure_ascii=False, indent=2))
                return 0
            finally:
                store.close()
        with single_probe(folder):
            asyncio.run(run_probe(folder, minutes, args.rss_interval, args.rss_timeout))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print("S0_02_STOPPED:", type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
