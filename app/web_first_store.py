"""Web-first B private SQLite control plane. NOT the legacy Bot database.

A B data directory must be new and dedicated. Never silently migrate, wipe,
repair, or reinterpret existing RC1 data, journals, or symlinks.
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import stat
import tempfile
import time
from contextlib import closing, suppress
from pathlib import Path

from app.web_auth import check_password, password_hash

SCHEMA_VERSION = 1
USERNAME = re.compile(r"[A-Za-z0-9_.-]{3,32}\Z")
PREFERENCES = {
    "theme": {"light", "dark"},
    "home": {"overview", "rules"},
    "log_level": {"INFO", "WARNING", "DEBUG"},
}


class UnsafeWebFirstData(RuntimeError):
    """Mounted data is unsuitable; never attempt automatic recovery."""


class WebFirstStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.path = self.directory / "web-first.sqlite"

    def _check_directory(self) -> None:
        p = self.directory
        if not p.is_absolute() or ".." in p.parts:
            raise UnsafeWebFirstData("web_first_absolute_volume_required")
        if p.is_symlink() or not p.is_dir() or p.resolve() != p:
            raise UnsafeWebFirstData("web_first_unsafe_volume")
        info = p.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise UnsafeWebFirstData("web_first_private_volume_required")

    def _check_regular_private(self, path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise UnsafeWebFirstData("web_first_invalid_private_file")
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise UnsafeWebFirstData("web_first_invalid_private_file")

    def _read_only_check(self) -> None:
        self._check_regular_private(self.path)
        try:
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=3)) as conn:
                conn.execute("PRAGMA query_only=ON")
                if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise UnsafeWebFirstData("web_first_corrupt_database")
                if conn.execute("PRAGMA user_version").fetchone() != (SCHEMA_VERSION,):
                    raise UnsafeWebFirstData("web_first_unknown_schema")
                tables = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                if not {"web_admin", "web_preferences"}.issubset(tables):
                    raise UnsafeWebFirstData("web_first_missing_schema")
                count = conn.execute("SELECT COUNT(*) FROM web_admin").fetchone()[0]
                if count not in (0, 1):
                    raise UnsafeWebFirstData("web_first_invalid_administrator")
                if count and conn.execute(
                    "SELECT 1 FROM web_admin WHERE id=1"
                ).fetchone() != (1,):
                    raise UnsafeWebFirstData("web_first_invalid_administrator")
        except sqlite3.DatabaseError:
            raise UnsafeWebFirstData("web_first_invalid_database") from None

    def _initialize_new_locked(self) -> None:
        # Called only while a Linux owner lock on self.path is held.
        allowed = {self.path.name + ".owner.lock"}
        if set(os.listdir(self.directory)) - allowed:
            raise UnsafeWebFirstData("web_first_volume_not_empty")
        stage: Path | None = None
        try:
            fd, name = tempfile.mkstemp(prefix=".web-first-staging-", dir=self.directory)
            stage = Path(name)
            os.fchmod(fd, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(stage, timeout=3)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "CREATE TABLE web_admin (id INTEGER PRIMARY KEY CHECK(id=1), "
                    "username TEXT NOT NULL UNIQUE, password_digest TEXT NOT NULL, "
                    "created_at INTEGER NOT NULL)"
                )
                conn.execute(
                    "CREATE TABLE web_preferences (name TEXT PRIMARY KEY, "
                    "value TEXT NOT NULL)"
                )
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                conn.commit()
                if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise UnsafeWebFirstData("web_first_staging_corrupt")
            if set(os.listdir(self.directory)) - (allowed | {stage.name}):
                raise UnsafeWebFirstData("web_first_volume_changed")
            if any(os.path.lexists(str(stage) + ext) for ext in ("-wal", "-shm", "-journal")):
                raise UnsafeWebFirstData("web_first_staging_sidecar")
            with stage.open("rb") as f:
                os.fsync(f.fileno())
            # Atomic, no overwrite even if an unexpected actor created the file.
            os.link(stage, self.path, follow_symlinks=False)
            self._fsync_directory()
        except FileExistsError:
            raise UnsafeWebFirstData("web_first_database_already_exists") from None
        except OSError as exc:
            raise UnsafeWebFirstData("web_first_initialization_io_error") from exc
        finally:
            if stage is not None:
                with suppress(FileNotFoundError):
                    stage.unlink()

    def _fsync_directory(self) -> None:
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def prepare_locked(self) -> None:
        """Initialize only a genuinely new volume; otherwise validate existing data.

        First-time visitors register their own username/password on the Web.
        Never generate an initial account, a password, or an out-of-band code.
        This method is called while the process holds the database owner lock.
        """
        self._check_directory()
        if os.path.lexists(self.path):
            self._read_only_check()
        else:
            self._initialize_new_locked()
            self._read_only_check()

    def _connect(self) -> sqlite3.Connection:
        # Never allow sqlite3.connect() to silently create a missing database.
        self._read_only_check()
        conn = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=3)
        conn.execute("PRAGMA busy_timeout=3000")
        return conn

    def admin_exists(self) -> bool:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT 1 FROM web_admin WHERE id=1").fetchone() is not None

    def create_admin(self, username: str, password: str) -> bool:
        """Atomic first-user signup; a second administrator cannot be registered."""
        if (not isinstance(username, str) or not USERNAME.fullmatch(username)
                or not isinstance(password, str) or not 12 <= len(password) <= 512):
            return False
        digest = password_hash(password)
        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("SELECT 1 FROM web_admin WHERE id=1").fetchone():
                    conn.rollback()
                    return False
                conn.execute(
                    "INSERT INTO web_admin (id,username,password_digest,created_at) "
                    "VALUES(1,?,?,?)", (username, digest, int(time.time()))
                )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                return False
        return True

    def check_login(self, username: str, password: str) -> bool:
        if not isinstance(username, str) or not isinstance(password, str):
            return False
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT username,password_digest FROM web_admin WHERE id=1"
            ).fetchone()
        return bool(row and secrets.compare_digest(username, row[0])
                    and check_password(password, row[1]))

    def admin_name(self) -> str | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT username FROM web_admin WHERE id=1").fetchone()
            return row[0] if row else None

    def change_password(self, old_password: str, new_password: str) -> bool:
        if not isinstance(new_password, str) or not 12 <= len(new_password) <= 512:
            return False
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT password_digest FROM web_admin WHERE id=1"
            ).fetchone()
            if not row or not check_password(old_password, row[0]):
                conn.rollback()
                return False
            conn.execute(
                "UPDATE web_admin SET password_digest=? WHERE id=1",
                (password_hash(new_password),)
            )
            conn.commit()
            return True

    def preferences(self) -> dict[str, str]:
        result = {"theme": "light", "home": "overview", "log_level": "INFO"}
        with closing(self._connect()) as conn:
            for key, value in conn.execute("SELECT name,value FROM web_preferences"):
                if key in PREFERENCES and value in PREFERENCES[key]:
                    result[key] = value
        return result

    def save_preferences(self, updates: dict[str, str]) -> None:
        if not updates or any(
            key not in PREFERENCES or value not in PREFERENCES[key]
            for key, value in updates.items()
        ):
            raise ValueError("invalid_web_preference")
        with closing(self._connect()) as conn:
            with conn:
                for key, value in updates.items():
                    conn.execute(
                        "INSERT INTO web_preferences(name,value) VALUES(?,?) "
                        "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                        (key, value),
                    )
