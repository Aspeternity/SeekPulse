"""S6 WAL-consistent private snapshot and fail-closed offline recovery tests.

Uses temporary SQLite and local file systems only; never a live service, network,
production DB, Telegram Session, or credentials.
"""

from __future__ import annotations

import errno
import hashlib
import json
import sqlite3
import stat
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.db import Database
from app.delivery import CoreStore
from app.domain import Source, SourceObservation
from app.maintenance import (
    DATABASE_NAME, MANIFEST_NAME, MaintenanceError, create_backup,
    inspect_database, main, restore_new, verify_backup,
)
from app.route_store import Channel, RouteStore
from app.source_state import SourceStore


class SnapshotContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory(prefix="seekpulse-s6-")
        self.addAsyncCleanup(self._cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "primary.db"
        self.bundle = self.root / "private-snapshot"
        self.db = Database(self.path)
        await self.db.init()
        self.core = CoreStore(self.path)
        await self.core.init()
        self.sources = SourceStore(self.path)
        await self.sources.init()
        self.routes = RouteStore(self.path)
        await self.routes.init()
        self.owner = await self.db.ensure_user_profile(
            101, 1101, None, "STORED_PRIVATE_NAME", None, "private",
        )
        self.target = (await self.db.list_targets_by_tg_user(101))[0]
        _, self.keyword = await self.db.add_keyword(101, "DMIT")
        await self.core.observe(SourceObservation(
            Source.RSS, "rss-one", 100,
            datetime(2026, 10, 14, tzinfo=timezone.utc),
            title="DMIT", summary="补货", category="交易",
        ))
        await self.core.enqueue(
            self.owner.id, 100, [self.target.id], now=1000
        )
        await self.sources.bootstrap_telegram(42)
        await self.sources.mark_gap(Source.TELEGRAM, "backfill_limit")
        await self.routes.bind_channel(
            self.owner.id, self.target.id, Channel.BARK, "BARK_SECURE_REFERENCE",
        )

    async def _cleanup(self):
        self.directory.cleanup()

    def assert_error(self, code, fn, *args):
        with self.assertRaises(MaintenanceError) as caught:
            fn(*args)
        self.assertEqual(caught.exception.code, code)

    def test_online_wal_backup_is_self_contained_and_verified(self):
        # Force an uncheckpointed committed WAL record; file-only copying the
        # main DB would lose it, while SQLite online backup must include it.
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            db.execute("PRAGMA wal_autocheckpoint=0")
            db.execute("UPDATE users SET first_name=? WHERE id=?",
                       ("WAL_RECENT_SECRET", self.owner.id))
            db.commit()
            self.assertTrue((self.root / "primary.db-wal").exists())
            done = create_backup(self.path, self.bundle)
            self.assertTrue(done["ok"])
            self.assertEqual(verify_backup(self.bundle)["sha256"], done["sha256"])
            with sqlite3.connect(
                self.bundle / DATABASE_NAME
            ) as backed:
                self.assertEqual(backed.execute(
                    "SELECT first_name FROM users WHERE id=?",
                    (self.owner.id,),
                ).fetchone()[0], "WAL_RECENT_SECRET")
                self.assertEqual(backed.execute(
                    "PRAGMA journal_mode"
                ).fetchone()[0], "delete")

    def test_backup_restores_all_stages_state_to_new_path(self):
        create_backup(self.path, self.bundle)
        restored = self.root / "recovered.db"
        result = restore_new(self.bundle, restored)
        self.assertTrue(result["restored"])
        self.assertTrue(restored.is_file())
        with sqlite3.connect(restored) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute(
                "SELECT cursor FROM s3_source_status WHERE source='telegram'"
            ).fetchone()[0], 42)
            self.assertEqual(db.execute(
                "SELECT gap_code FROM s3_source_status WHERE source='telegram'"
            ).fetchone()[0], "backfill_limit")
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM delivery_tasks WHERE status='pending'"
            ).fetchone()[0], 1)
            self.assertEqual(db.execute(
                "SELECT channel FROM s4_target_channels"
            ).fetchone()[0], "bark")
        self.assertEqual(verify_backup(self.bundle)["sha256"], result["sha256"])
        self.assertTrue(self.path.exists())
        self.assert_error("destination_exists", restore_new, self.bundle, restored)

    def test_private_file_and_bundle_permissions(self):
        create_backup(self.path, self.bundle)
        self.assertEqual(stat.S_IMODE(self.bundle.stat().st_mode) & 0o077, 0)
        for name in (DATABASE_NAME, MANIFEST_NAME):
            self.assertEqual(
                stat.S_IMODE((self.bundle / name).stat().st_mode) & 0o077,
                0,
            )
        restore = self.root / "new.db"
        restore_new(self.bundle, restore)
        self.assertEqual(stat.S_IMODE(restore.stat().st_mode) & 0o077, 0)

    def test_backup_is_non_overwriting_and_manifest_excludes_private_data(self):
        result = create_backup(self.path, self.bundle)
        manifest = (self.bundle / MANIFEST_NAME).read_text()
        self.assertNotIn("STORED_PRIVATE_NAME", manifest)
        self.assertNotIn("BARK_SECURE_REFERENCE", manifest)
        self.assertNotIn(str(self.path), manifest)
        self.assertNotIn("password", manifest)
        self.assertEqual(json.loads(manifest)["format"], 1)
        self.assert_error("destination_exists", create_backup, self.path, self.bundle)
        self.assertEqual(result["sha256"], verify_backup(self.bundle)["sha256"])

    def test_modified_or_truncated_snapshot_never_restores(self):
        create_backup(self.path, self.bundle)
        dest = self.root / "should-not-exist.db"
        with (self.bundle / DATABASE_NAME).open("ab") as out:
            out.write(b"silent-corruption")
        self.assert_error("checksum_mismatch", verify_backup, self.bundle)
        self.assert_error("checksum_mismatch", restore_new, self.bundle, dest)
        self.assertFalse(dest.exists())

    def test_tampered_manifest_rejected_and_no_restoration(self):
        create_backup(self.path, self.bundle)
        manifest = self.bundle / MANIFEST_NAME
        original = json.loads(manifest.read_text())
        original["database_sha256"] = "0" * 64
        manifest.write_text(json.dumps(original))
        self.assert_error("checksum_mismatch", verify_backup, self.bundle)
        self.assertFalse((self.root / "attacker.db").exists())

    def test_unsupported_schema_requires_explicit_migration(self):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE s4_schema_meta SET value='999' WHERE key='routing_schema_version'"
            )
            db.commit()
        self.assert_error("unsupported_schema", inspect_database, self.path)
        self.assert_error("unsupported_schema", create_backup, self.path, self.bundle)
        self.assertFalse(self.bundle.exists())

    def test_foreign_key_violation_is_not_accepted_as_good_backup(self):
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute(
                "INSERT INTO targets(user_id,chat_id,created_at,updated_at) "
                "VALUES (999999,999999,'now','now')"
            )
            db.commit()
        self.assert_error("foreign_key_violation", create_backup, self.path, self.bundle)
        self.assertFalse(self.bundle.exists())

    def test_disk_full_during_backup_cleans_staging_and_preserves_source(self):
        before = self.path.read_bytes()
        with patch("app.maintenance._copy_snapshot",
                   side_effect=OSError(errno.ENOSPC, "fake disk full")):
            self.assert_error("disk_full", create_backup, self.path, self.bundle)
        self.assertFalse(self.bundle.exists())
        self.assertFalse(list(self.root.glob(".seekpulse-s6-*")))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(inspect_database(self.path)["ok"])

    def test_disk_full_during_restore_removes_stage_and_preserves_bundle(self):
        create_backup(self.path, self.bundle)
        destination = self.root / "never-created.db"
        original = verify_backup(self.bundle)["sha256"]
        with patch("app.maintenance.shutil.copyfileobj",
                   side_effect=OSError(errno.ENOSPC, "fake disk full")):
            self.assert_error("disk_full", restore_new, self.bundle, destination)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.root.glob(".seekpulse-restore-*")))
        self.assertEqual(verify_backup(self.bundle)["sha256"], original)

    def test_missing_source_must_not_create_empty_sqlite(self):
        db = self.root / "missing.db"
        self.assert_error("source_missing", inspect_database, db)
        self.assert_error("source_missing", create_backup, db, self.bundle)
        self.assertFalse(db.exists())
        self.assertFalse(self.bundle.exists())

    def test_existing_target_and_wal_sidecar_refuse_restore(self):
        create_backup(self.path, self.bundle)
        original = self.path.read_bytes()
        self.assert_error("destination_exists", restore_new, self.bundle, self.path)
        self.assertEqual(self.path.read_bytes(), original)
        dest = self.root / "stale.db"
        (self.root / "stale.db-wal").write_text("from previous crash")
        self.assert_error("destination_exists", restore_new, self.bundle, dest)
        self.assertFalse(dest.exists())

    def test_symlink_db_and_bundle_denied(self):
        create_backup(self.path, self.bundle)
        link = self.root / "alias.db"
        link.symlink_to(self.path)
        self.assert_error("invalid_file", inspect_database, link)
        link_dir = self.root / "alias-bundle"
        link_dir.symlink_to(self.bundle, target_is_directory=True)
        self.assert_error("invalid_bundle", verify_backup, link_dir)
        self.assert_error("destination_exists", restore_new, self.bundle, link)

    def test_redacted_inspection_counts_and_gap_only(self):
        health = inspect_database(self.path)
        self.assertTrue(health["ok"])
        self.assertEqual(health["users"], 1)
        self.assertEqual(health["tasks"], {"pending": 1})
        self.assertEqual(health["sources"]["telegram"]["cursor"], 42)
        self.assertEqual(health["sources"]["telegram"]["gap_code"], "backfill_limit")
        self.assertNotIn("STORED_PRIVATE_NAME", json.dumps(health))
        self.assertNotIn("BARK_SECURE_REFERENCE", json.dumps(health))

    def test_restore_file_is_exact_and_no_implicit_schema_migration(self):
        create_backup(self.path, self.bundle)
        original = verify_backup(self.bundle)["sha256"]
        path = self.root / "fresh.db"
        restore_new(self.bundle, path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(digest, original)
        self.assertNotIn("migration", json.dumps(inspect_database(path)).lower())


if __name__ == "__main__":
    unittest.main()
