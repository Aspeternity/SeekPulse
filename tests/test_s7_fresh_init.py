"""Docker-02 first-install contracts: temp SQLite only, no network/credentials."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.db import Database
from app.fresh_init import (
    check_prepared_database,
    database_path_from_environment,
    initialize_empty_database,
)
from app.instance_lock import database_owner_lock
from app.maintenance import inspect_database
# G0 installs only the upstream requirements; the optional V1.1 Web
# packages are covered by S7's full-dependency workflow below.
try:
    from app.v11_main import build_components, main
except ModuleNotFoundError as exc:
    if exc.name not in {"fastapi", "uvicorn", "jinja2", "apprise", "telethon"}:
        raise
    build_components = None
    main = None

_OPTIN = {
    "SEEKPULSE_V11_ENABLE": "1",
    "SEEKPULSE_FRESH_INIT_CONFIRM": "CREATE_EMPTY_DATABASE",
}


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FreshDatabaseContracts(unittest.IsolatedAsyncioTestCase):
    async def _fresh(self, path: Path):
        with patch.dict(os.environ, _OPTIN, clear=True):
            return await initialize_empty_database(path)

    async def test_fresh_install_creates_fully_primed_empty_database(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "bot.db"
            self.assertEqual(await self._fresh(path), 0)
            self.assertEqual(check_prepared_database(path), 0)
            report = inspect_database(path)
            self.assertEqual(report["users"], 0)
            self.assertEqual(report["tasks"], {})
            self.assertEqual(report["sources"]["rss"]["enabled"], True)
            self.assertEqual(report["sources"]["telegram"]["enabled"], False)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM source_observations"
                ).fetchone()[0], 0)
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM delivery_tasks"
                ).fetchone()[0], 0)
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM targets"
                ).fetchone()[0], 0)
                self.assertEqual(db.execute(
                    "SELECT last_observation_id FROM gate_b_dispatch_state"
                ).fetchone()[0], 0)
                self.assertEqual(dict(db.execute(
                    "SELECT source, initialized FROM s3_source_status"
                ).fetchall()), {"rss": 0, "telegram": 0})
                self.assertEqual(db.execute(
                    "SELECT value FROM gate_b_schema_meta "
                    "WHERE key='target_schema_version'"
                ).fetchone()[0], "1")
                self.assertEqual(db.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall(), [])
                self.assertEqual(db.execute(
                    "PRAGMA journal_mode"
                ).fetchone()[0], "delete")
            leftovers = {p.name for p in Path(td).iterdir()}
            self.assertEqual(leftovers, {"bot.db", "bot.db.owner.lock"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    async def test_confirmation_and_v11_enable_must_both_be_explicit(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "bot.db"
            for env in (
                {},
                {"SEEKPULSE_V11_ENABLE": "1"},
                {"SEEKPULSE_FRESH_INIT_CONFIRM": "CREATE_EMPTY_DATABASE"},
            ):
                with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                    with self.assertRaises(RuntimeError):
                        await initialize_empty_database(path)
                    self.assertFalse(path.exists())
            self.assertEqual(list(Path(td).iterdir()), [])

    async def test_repeating_init_never_changes_the_database(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "bot.db"
            await self._fresh(path)
            original = checksum(path)
            with self.assertRaisesRegex(RuntimeError, "database_already_exists"):
                await self._fresh(path)
            self.assertEqual(checksum(path), original)
            self.assertEqual(check_prepared_database(path), 0)

    async def test_preexisting_old_database_and_empty_file_are_preserved(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), TemporaryDirectory() as td:
                path = Path(td) / "bot.db"
                if legacy:
                    await Database(path).init()
                else:
                    path.write_bytes(b"")
                original = checksum(path)
                with self.assertRaisesRegex(RuntimeError, "database_already_exists"):
                    await self._fresh(path)
                self.assertEqual(checksum(path), original)

    async def test_sidecar_files_are_never_replaced_or_deleted(self):
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix), TemporaryDirectory() as td:
                path = Path(td) / "bot.db"
                sidecar = Path(str(path) + suffix)
                sidecar.write_bytes(b"existing private bytes")
                with self.assertRaisesRegex(RuntimeError, "database_already_exists"):
                    await self._fresh(path)
                self.assertEqual(sidecar.read_bytes(), b"existing private bytes")
                self.assertFalse(path.exists())

    async def test_dedicated_directory_rejects_other_user_files(self):
        for name in ("old.session", ".env", "backup", "different.db"):
            with self.subTest(name=name), TemporaryDirectory() as td:
                path = Path(td) / "bot.db"
                other = Path(td) / name
                other.write_bytes(b"keep untouched")
                with self.assertRaisesRegex(RuntimeError, "directory_not_empty"):
                    await self._fresh(path)
                self.assertEqual(other.read_bytes(), b"keep untouched")
                self.assertFalse(path.exists())

    async def test_parent_symlink_rejected_without_writes(self):
        with TemporaryDirectory() as td:
            real = Path(td) / "real"
            real.mkdir()
            alias = Path(td) / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "unsafe_database_path"):
                await self._fresh(alias / "bot.db")
            self.assertEqual(list(real.iterdir()), [])

    async def test_relative_path_and_missing_directory_fail_closed(self):
        with TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, "absolute_database_path"):
                await self._fresh(Path("bot.db"))
            with self.assertRaisesRegex(RuntimeError, "unsafe_database_path"):
                await self._fresh(Path(td) / "missing" / "bot.db")

    async def test_owner_lock_contention_refuses_initialization(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "bot.db"
            with database_owner_lock(path):
                with self.assertRaisesRegex(RuntimeError, "instance_already_running"):
                    await self._fresh(path)
            self.assertFalse(path.exists())

    async def test_staging_failure_cleans_only_its_private_temporary_files(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "bot.db"
            with patch(
                "app.fresh_init.initialize_stores",
                side_effect=RuntimeError("injected_fresh_staging_failure")
            ):
                with self.assertRaisesRegex(RuntimeError, "injected_fresh_staging_failure"):
                    await self._fresh(path)
            self.assertEqual(
                {x.name for x in Path(td).iterdir()}, {"bot.db.owner.lock"}
            )
            self.assertFalse(path.exists())

    async def test_failed_checkpoint_never_publishes_database(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "bot.db"
            with patch("app.fresh_init._checkpoint_private_staging",
                       side_effect=RuntimeError("fresh_init_checkpoint_busy")):
                with self.assertRaisesRegex(RuntimeError, "checkpoint_busy"):
                    await self._fresh(path)
            self.assertEqual(
                {x.name for x in Path(td).iterdir()}, {"bot.db.owner.lock"}
            )
            self.assertFalse(path.exists())

    async def test_failed_fsync_does_not_publish_a_partial_database(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "bot.db"
            with patch("app.fresh_init._fsync", side_effect=OSError("offline fault")):
                with self.assertRaisesRegex(RuntimeError, "fresh_init_io_failure"):
                    await self._fresh(path)
            self.assertEqual(
                {x.name for x in Path(td).iterdir()}, {"bot.db.owner.lock"}
            )

    async def test_atomic_publish_race_never_overwrites_the_winner(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "bot.db"

            def competing_creator(_stage, destination, **_kwargs):
                Path(destination).write_bytes(b"someone else's data")
                raise FileExistsError()

            with patch("app.fresh_init.os.link", side_effect=competing_creator):
                with self.assertRaisesRegex(RuntimeError, "database_already_exists"):
                    await self._fresh(path)
            self.assertEqual(path.read_bytes(), b"someone else's data")
            self.assertEqual(
                {x.name for x in Path(td).iterdir()},
                {"bot.db", "bot.db.owner.lock"},
            )

    async def test_check_rejects_unprepared_database_before_writable_stores(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            await Database(path).init()
            original = checksum(path)
            with self.assertRaisesRegex(RuntimeError, "v11_database_not_prepared"):
                check_prepared_database(path)
            if build_components is not None:
                with patch("app.v11_main._stores",
                           side_effect=AssertionError("must not init or send")):
                    with self.assertRaisesRegex(RuntimeError, "v11_database_not_prepared"):
                        await build_components(SimpleNamespace(database_path=path))
            self.assertEqual(checksum(path), original)

    async def test_check_rejects_missing_file_without_creating_it(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "bot.db"
            with self.assertRaisesRegex(RuntimeError, "v11_database_not_prepared"):
                check_prepared_database(path)
            if build_components is not None:
                with patch("app.v11_main._stores",
                           side_effect=AssertionError("must not init")):
                    with self.assertRaisesRegex(RuntimeError, "v11_database_not_prepared"):
                        await build_components(SimpleNamespace(database_path=path))
            self.assertFalse(path.exists())

    @unittest.skipUnless(main is not None, "Full V1.1 dependencies needed for CLI import")
    async def test_cli_fresh_check_and_legacy_prepare_are_separate(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "bot.db"
            with patch.dict(os.environ, {
                **_OPTIN, "DATABASE_PATH": str(path),
            }, clear=True):
                with redirect_stdout(StringIO()) as out:
                    self.assertEqual(await asyncio.to_thread(main, ["--init-fresh"]), 0)
                self.assertEqual(out.getvalue().strip(), "fresh_init_ready")
                with redirect_stdout(StringIO()) as out:
                    self.assertEqual(await asyncio.to_thread(main, ["--check"]), 0)
                self.assertEqual(out.getvalue().strip(), "v11_database_ready")
            other = Path(td) / "legacy.db"
            with patch.dict(os.environ, {
                "SEEKPULSE_V11_ENABLE": "1",
                "DATABASE_PATH": str(other),
                "BOT_TOKEN": "offline_dummy_not_used",
            }, clear=True):
                with self.assertRaisesRegex(RuntimeError, "verified_backup_bundle_required"):
                    await asyncio.to_thread(main, ["--prepare"])
            self.assertFalse(other.exists())


if __name__ == "__main__":
    unittest.main()
