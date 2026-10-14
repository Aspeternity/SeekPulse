"""S6 offline maintenance: WAL-safe snapshots, integrity verification and safe restore.

Not imported by app.main; never runs background tasks or sends notifications.
Restore creates a NEW DB path and refuses to replace any existing database.
SQLite data is sensitive: bundle directory is 0700 and contents are 0600.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

FORMAT_VERSION = 1
DATABASE_NAME = "snapshot.sqlite3"
MANIFEST_NAME = "manifest.json"
REQUIRED_TABLES = frozenset({
    "users", "user_settings", "keywords", "block_keywords",
    "targets", "delivery_history", "schema_meta",
    "canonical_posts", "source_observations", "delivery_tasks",
    "s2_schema_meta", "s3_source_status", "s3_rss_seen",
    "s4_schema_meta", "s4_target_channels", "s4_target_cooldowns",
})
SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MaintenanceError(RuntimeError):
    """Failure codes never include a path, credential, SQL or exception body."""

    def __init__(self, code: str):
        if not SAFE_CODE.fullmatch(code):
            raise ValueError("unsafe maintenance error code")
        self.code = code
        super().__init__(code)


def _map_error(exc: BaseException) -> MaintenanceError:
    if isinstance(exc, MaintenanceError):
        return exc
    if isinstance(exc, OSError):
        if exc.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
            return MaintenanceError("disk_full")
        if exc.errno == errno.EEXIST:
            return MaintenanceError("destination_exists")
        return MaintenanceError("io_failure")
    if isinstance(exc, sqlite3.OperationalError):
        name = getattr(exc, "sqlite_errorname", "")
        # SQLite reports disk exhaustion as SQLITE_FULL, not always ENOSPC.
        if name.startswith("SQLITE_FULL"):
            return MaintenanceError("disk_full")
        if name.startswith(("SQLITE_BUSY", "SQLITE_LOCKED")):
            return MaintenanceError("database_busy")
        if name.startswith("SQLITE_IOERR"):
            return MaintenanceError("io_failure")
        return MaintenanceError("database_unavailable")
    if isinstance(exc, sqlite3.DatabaseError):
        return MaintenanceError("database_corrupt")
    return MaintenanceError("invalid_backup")


def _absolute(path: str | Path) -> Path:
    if not isinstance(path, (Path, str)) or not str(path):
        raise MaintenanceError("invalid_path")
    return Path(os.path.abspath(os.fspath(path)))


def _safe_parent(path: Path) -> None:
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise MaintenanceError("invalid_parent")
    # No symlink anywhere in the parent chain, including a mount alias.
    if parent.resolve() != parent:
        raise MaintenanceError("symlink_denied")


def _regular_file(path: Path) -> None:
    _safe_parent(path)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise MaintenanceError("source_missing") from exc
    if not stat.S_ISREG(mode):
        raise MaintenanceError("invalid_file")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as inp:
        for block in iter(lambda: inp.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _sync_dir(path: Path) -> None:
    handle = os.open(path, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


@contextmanager
def _read_only(path: Path) -> Iterator[sqlite3.Connection]:
    _regular_file(path)
    # mode=ro prevents accidental DB creation / schema changes.
    connection = sqlite3.connect(
        path.as_uri() + "?mode=ro", uri=True, timeout=2.0
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=2000")
        yield connection
    finally:
        connection.close()


def _schema_and_integrity(conn: sqlite3.Connection) -> dict[str, str]:
    integrity = conn.execute("PRAGMA integrity_check").fetchall()
    if integrity != [("ok",)]:
        raise MaintenanceError("integrity_failed")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise MaintenanceError("foreign_key_violation")
    tables = {
        name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if not REQUIRED_TABLES.issubset(tables):
        raise MaintenanceError("incomplete_schema")
    metadata = {}
    for table, key, expected in (
        ("s2_schema_meta", "core_schema_version", "1"),
        ("s4_schema_meta", "routing_schema_version", "1"),
    ):
        row = conn.execute(
            f"SELECT value FROM {table} WHERE key=?", (key,)
        ).fetchone()
        if row is None or row[0] != expected:
            raise MaintenanceError("unsupported_schema")
        metadata[key] = expected
    return metadata


def _safe_code(value: str | None) -> str | None:
    return value if value is not None and SAFE_CODE.fullmatch(value) else None


def inspect_database(path: str | Path) -> dict:
    """Read-only offline health diagnostics. Never return private row values."""
    source = _absolute(path)
    try:
        with _read_only(source) as conn:
            versions = _schema_and_integrity(conn)
            queue = {
                str(status): int(count)
                for status, count in conn.execute(
                    "SELECT status, COUNT(*) FROM delivery_tasks GROUP BY status"
                )
            }
            sources = {}
            for name, enabled, cursor, failures, retry_at, error, gap in conn.execute(
                """SELECT source,enabled,cursor,failures,retry_at,
                          last_error_code,gap_code FROM s3_source_status"""
            ):
                if name not in ("rss", "telegram"):
                    raise MaintenanceError("invalid_source_state")
                sources[name] = {
                    "enabled": bool(enabled),
                    "cursor": int(cursor),
                    "failures": int(failures),
                    "retry_at": int(retry_at),
                    "error_code": _safe_code(error),
                    "gap_code": _safe_code(gap),
                }
            wal = source.with_name(source.name + "-wal")
            return {
                "ok": True,
                "schema": versions,
                "journal_mode": str(conn.execute("PRAGMA journal_mode").fetchone()[0]),
                "size_bytes": source.stat().st_size,
                "wal_size_bytes": wal.stat().st_size if wal.exists() else 0,
                "users": int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]),
                "tasks": queue,
                "sources": sources,
                "integrity": "ok",
            }
    except (OSError, sqlite3.Error, MaintenanceError) as exc:
        raise _map_error(exc) from None


def _copy_snapshot(source: Path, dest: Path) -> None:
    """SQLite's online backup API includes committed WAL transactions."""
    with _read_only(source) as from_db:
        # File was already exclusively created as 0600.
        with sqlite3.connect(dest, timeout=2.0) as to_db:
            deadline = time.monotonic() + 15

            def progress(_status: int, _remaining: int, _total: int) -> None:
                if time.monotonic() > deadline:
                    raise MaintenanceError("database_busy")

            from_db.backup(to_db, pages=128, progress=progress, sleep=0.05)
            # Bundle must be standalone even if source used WAL mode.
            mode = to_db.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if mode.lower() != "delete":
                raise MaintenanceError("snapshot_journal_error")
            to_db.commit()


def _create_exclusive(path: Path) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    os.close(descriptor)


def _write_manifest(path: Path, payload: dict) -> None:
    content = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(content) > 4096:
        raise MaintenanceError("invalid_manifest")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def create_backup(database: str | Path, bundle: str | Path) -> dict:
    """Create one atomic, private bundle at a NEW destination directory."""
    db = _absolute(database)
    dst = _absolute(bundle)
    staging: Path | None = None
    try:
        _safe_parent(dst)
        if dst.exists() or dst.is_symlink():
            raise MaintenanceError("destination_exists")
        with _read_only(db) as connection:
            versions = _schema_and_integrity(connection)
        staging = Path(tempfile.mkdtemp(prefix=".seekpulse-s6-", dir=dst.parent))
        image = staging / DATABASE_NAME
        _create_exclusive(image)
        _copy_snapshot(db, image)
        with _read_only(image) as connection:
            result = _schema_and_integrity(connection)
        if result != versions:
            raise MaintenanceError("schema_changed")
        image_hash = _hash(image)
        size = image.stat().st_size
        manifest = {
            "format": FORMAT_VERSION,
            "database_sha256": image_hash,
            "database_size": size,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema": versions,
        }
        _write_manifest(staging / MANIFEST_NAME, manifest)
        _sync_file(image)
        _sync_dir(staging)
        if dst.exists() or dst.is_symlink():
            raise MaintenanceError("destination_exists")
        os.rename(staging, dst)
        staging = None
        _sync_dir(dst.parent)
        return {
            "ok": True, "format": FORMAT_VERSION,
            "sha256": image_hash, "size_bytes": size,
        }
    except (OSError, sqlite3.Error, MaintenanceError) as exc:
        raise _map_error(exc) from None
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def verify_backup(bundle: str | Path) -> dict:
    """Verify SHA-256, schema, FK and full SQLite integrity before recovery."""
    folder = _absolute(bundle)
    try:
        _safe_parent(folder)
        if folder.is_symlink() or not folder.is_dir():
            raise MaintenanceError("invalid_bundle")
        image = folder / DATABASE_NAME
        manifest_path = folder / MANIFEST_NAME
        _regular_file(image)
        _regular_file(manifest_path)
        if manifest_path.stat().st_size > 4096:
            raise MaintenanceError("invalid_manifest")
        with manifest_path.open("rb") as source:
            data = json.loads(source.read().decode("utf-8"))
        if (not isinstance(data, dict)
                or data.get("format") != FORMAT_VERSION
                or type(data.get("database_size")) is not int
                or data["database_size"] <= 0
                or not isinstance(data.get("database_sha256"), str)
                or SHA256.fullmatch(data["database_sha256"]) is None
                or not isinstance(data.get("schema"), dict)
                or set(data["schema"]) != {"core_schema_version", "routing_schema_version"}
                or data["schema"] != {
                    "core_schema_version": "1", "routing_schema_version": "1"
                }):
            raise MaintenanceError("invalid_manifest")
        if image.stat().st_size != data["database_size"]:
            raise MaintenanceError("checksum_mismatch")
        if _hash(image) != data["database_sha256"]:
            raise MaintenanceError("checksum_mismatch")
        with _read_only(image) as connection:
            versions = _schema_and_integrity(connection)
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise MaintenanceError("snapshot_journal_error")
        if versions != data["schema"]:
            raise MaintenanceError("schema_mismatch")
        return {
            "ok": True, "format": FORMAT_VERSION,
            "sha256": data["database_sha256"],
            "size_bytes": data["database_size"],
        }
    except (OSError, sqlite3.Error, ValueError, TypeError, UnicodeError,
            json.JSONDecodeError, MaintenanceError) as exc:
        raise _map_error(exc) from None


def restore_new(bundle: str | Path, destination: str | Path) -> dict:
    """Restore to a NEW database path; never overwrite a running database.

    Restore does NOT initialize/migrate a schema, start a worker or switch
    configuration. Operator must stop all processes before a later approved
    switch of DATABASE_PATH. Existing -wal/-shm/-journal sidecars block reuse.
    """
    verified = verify_backup(bundle)
    dst = _absolute(destination)
    image = _absolute(bundle) / DATABASE_NAME
    tmp: Path | None = None
    try:
        _safe_parent(dst)
        if any(os.path.lexists(str(dst) + suffix) for suffix in (
            "", "-wal", "-shm", "-journal",
        )):
            raise MaintenanceError("destination_exists")
        fd, name = tempfile.mkstemp(prefix=".seekpulse-restore-", dir=dst.parent)
        tmp = Path(name)
        with os.fdopen(fd, "wb") as out, image.open("rb") as inp:
            shutil.copyfileobj(inp, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        if _hash(tmp) != verified["sha256"]:
            raise MaintenanceError("checksum_mismatch")
        with _read_only(tmp) as connection:
            _schema_and_integrity(connection)
        # Exclusive atomic publication, including if someone races to write
        # the destination. The original file can NEVER be overwritten.
        os.link(tmp, dst)
        _sync_dir(dst.parent)
        return {"ok": True, "restored": True, "sha256": verified["sha256"]}
    except (OSError, sqlite3.Error, MaintenanceError) as exc:
        raise _map_error(exc) from None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SeekPulse S6 offline SQLite maintenance")
    subs = parser.add_subparsers(dest="action", required=True)
    inspect_cmd = subs.add_parser("inspect", help="Read-only redacted health check")
    inspect_cmd.add_argument("--database", required=True)
    backup_cmd = subs.add_parser("backup", help="Create an atomic private backup bundle")
    backup_cmd.add_argument("--database", required=True)
    backup_cmd.add_argument("--bundle", required=True)
    verify_cmd = subs.add_parser("verify", help="Verify an existing backup bundle")
    verify_cmd.add_argument("--bundle", required=True)
    restore_cmd = subs.add_parser("restore-new", help="Restore only to an absent DB path")
    restore_cmd.add_argument("--bundle", required=True)
    restore_cmd.add_argument("--destination", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "inspect":
            result = inspect_database(args.database)
        elif args.action == "backup":
            result = create_backup(args.database, args.bundle)
        elif args.action == "verify":
            result = verify_backup(args.bundle)
        else:
            result = restore_new(args.bundle, args.destination)
    except MaintenanceError as exc:
        print(json.dumps({"ok": False, "code": exc.code}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
