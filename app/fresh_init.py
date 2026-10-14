"""Docker-02: explicitly create ONLY a new, empty V1.1 SQLite database.

A fresh install is NOT an upgrade or recovery tool. Preparation never reads
Bot/Telegram credentials, starts a network client, or sends notifications.
Existing databases MUST keep Gate B's independently verified S6 backup path.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing, suppress
from pathlib import Path

from app.instance_lock import database_owner_lock
from app.maintenance import inspect_database
from app.v11_stores import initialize_stores

_CONFIRM = "CREATE_EMPTY_DATABASE"
_SIDECARS = ("", "-wal", "-shm", "-journal")


def database_path_from_environment() -> Path:
    """Fresh/check are operable without any Bot credentials or implicit mkdir."""
    raw = os.getenv("DATABASE_PATH", "")
    if not raw:
        raise RuntimeError("fresh_init_absolute_database_path_required")
    path = Path(raw)
    _validate_path(path)
    return path


def _validate_path(path: Path) -> None:
    if (not isinstance(path, Path) or not path.is_absolute()
            or ".." in path.parts or not path.name):
        raise RuntimeError("fresh_init_absolute_database_path_required")
    try:
        parent = path.parent
        if (not parent.is_dir() or parent.is_symlink()
                or parent.resolve() != parent or path.is_symlink()):
            raise RuntimeError("fresh_init_unsafe_database_path")
    except (OSError, ValueError):
        raise RuntimeError("fresh_init_unsafe_database_path") from None


def _require_empty_directory(path: Path, *, staged: Path | None = None) -> None:
    """Never initialize in place of an existing DB, orphaned WAL or user file."""
    if any(os.path.lexists(str(path) + suffix) for suffix in _SIDECARS):
        raise RuntimeError("fresh_init_database_already_exists")
    allowed = {path.name + ".owner.lock"}
    if staged is not None:
        allowed.add(staged.name)
    try:
        others = set(os.listdir(path.parent)) - allowed
    except OSError:
        raise RuntimeError("fresh_init_directory_unavailable") from None
    if others:
        raise RuntimeError("fresh_init_directory_not_empty")


def check_prepared_database(path: Path) -> int:
    """Read-only V1.1 schema + Prime gate, before any stores/clients can start.

    Do not trust an existing file solely because sqlite3.connect can open it.
    It may be a legacy, empty, damaged, or partially initialized database.
    """
    try:
        path = Path(path)
        _validate_path(path)
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("v11_database_not_prepared")
        with closing(sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=2.0
        )) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                "SELECT value FROM gate_b_schema_meta "
                "WHERE key='target_schema_version'"
            ).fetchone()
            if row != ("1",):
                raise RuntimeError("v11_database_not_prepared")
            columns = db.execute("PRAGMA table_info(targets)").fetchall()
            chat = next((col for col in columns if col[1] == "chat_id"), None)
            if chat is None or chat[3] != 0:
                raise RuntimeError("v11_database_not_prepared")
            for table, key in (
                ("s2_schema_meta", "core_schema_version"),
                ("s4_schema_meta", "routing_schema_version"),
            ):
                version = db.execute(
                    f"SELECT value FROM {table} WHERE key=?", (key,)
                ).fetchone()
                if version != ("1",):
                    raise RuntimeError("v11_database_not_prepared")
            row = db.execute(
                "SELECT last_observation_id FROM gate_b_dispatch_state "
                "WHERE singleton=1"
            ).fetchone()
            if row is None or type(row[0]) is not int or row[0] < 0:
                raise RuntimeError("v11_database_not_prepared")
            return row[0]
    except (sqlite3.Error, OSError, ValueError):
        raise RuntimeError("v11_database_not_prepared") from None


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _checkpoint_private_staging(path: Path) -> None:
    """Materialize a standalone DB; NEVER copy/link a live WAL-backed file.

    This file is a unique new 0600 staging database, not an existing user DB.
    We may change *its* journal mode only after all async store writers close.
    """
    with closing(sqlite3.connect(path, timeout=5.0)) as db:
        checkpoint = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is None or checkpoint[0] != 0:
            raise RuntimeError("fresh_init_checkpoint_busy")
        mode = db.execute("PRAGMA journal_mode=DELETE").fetchone()
        if mode is None or str(mode[0]).lower() != "delete":
            raise RuntimeError("fresh_init_checkpoint_failed")


async def initialize_empty_database(path: Path) -> int:
    """Stage, validate and atomically publish a fully primed NEW database.

    Never overwrite or delete an existing database or sidecar. A separate
    --init-fresh invocation is required before Compose's --run will work.
    """
    if os.getenv("SEEKPULSE_V11_ENABLE") != "1":
        raise RuntimeError("v11_not_explicitly_enabled")
    if os.getenv("SEEKPULSE_FRESH_INIT_CONFIRM") != _CONFIRM:
        raise RuntimeError("fresh_init_explicit_confirmation_required")
    path = Path(path)
    _validate_path(path)
    _require_empty_directory(path)
    with database_owner_lock(path):
        _require_empty_directory(path)
        stage: Path | None = None
        try:
            fd, name = tempfile.mkstemp(
                prefix=f".{path.name}.fresh-", suffix=".db", dir=path.parent
            )
            os.close(fd)  # mkstemp created an exclusive private 0600 file.
            stage = Path(name)
            _, _, _, _, registry, dispatcher = await initialize_stores(stage)
            await registry.init()
            await registry.assert_live_safe()
            watermark = await dispatcher.prime()
            if watermark != 0:
                raise RuntimeError("fresh_init_nonempty_watermark")
            # Commit any WAL pages back into the main private staging file
            # and leave DELETE journal mode before atomic hardlink publish.
            _checkpoint_private_staging(stage)
            check_prepared_database(stage)
            report = inspect_database(stage)
            # S6's deliberately redacted report omits the initialized bit.
            # Check only our fresh staging file, not any existing user DB.
            with closing(sqlite3.connect(
                stage.as_uri() + "?mode=ro", uri=True
            )) as db:
                initial_states = dict(db.execute(
                    "SELECT source, initialized FROM s3_source_status"
                ).fetchall())
                observations = db.execute(
                    "SELECT COUNT(*) FROM source_observations"
                ).fetchone()[0]
                targets = db.execute(
                    "SELECT COUNT(*) FROM targets"
                ).fetchone()[0]
            if (report["users"] != 0 or any(report["tasks"].values())
                    or initial_states != {"rss": 0, "telegram": 0}
                    or observations != 0 or targets != 0):
                raise RuntimeError("fresh_init_nonempty_staging_database")
            if any(os.path.lexists(str(stage) + s) for s in _SIDECARS[1:]):
                raise RuntimeError("fresh_init_uncheckpointed_staging_database")
            _require_empty_directory(path, staged=stage)
            _fsync(stage)
            try:
                # Atomic no-clobber publication on the same mounted filesystem.
                os.link(stage, path, follow_symlinks=False)
            except FileExistsError:
                raise RuntimeError("fresh_init_database_already_exists") from None
            _fsync(path.parent)
            return watermark
        except OSError:
            raise RuntimeError("fresh_init_io_failure") from None
        finally:
            if stage is not None:
                # Only our random staging files, never the configured DB path.
                for suffix in _SIDECARS:
                    with suppress(FileNotFoundError):
                        os.unlink(str(stage) + suffix)
