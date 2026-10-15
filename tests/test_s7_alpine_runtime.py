"""Docker-08 offline V1.1 Alpine runtime contracts.

These tests use only temporary files, built-in TLS trust and a disabled runner;
no user DB/session/token or live remote notification calls.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sqlite3
import ssl
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ALPINE_DIGEST = "d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929"


class AlpineRuntimeContract(unittest.TestCase):
    def test_immutable_official_base_and_nonroot_runtime(self):
        dockerfile = (ROOT / "Dockerfile.v11").read_text(encoding="utf-8")
        self.assertRegex(
            dockerfile,
            rf"(?m)^FROM python:3\.11-alpine3\.24@sha256:{ALPINE_DIGEST}$",
        )
        self.assertEqual(len(re.findall(r"(?m)^FROM ", dockerfile)), 1)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("HOME=/tmp", dockerfile)
        self.assertIn("&& chmod 0700 /app/data", dockerfile)
        self.assertIn('ENTRYPOINT ["python", "-m", "app.v11_main"]', dockerfile)
        self.assertIn('CMD ["--run"]', dockerfile)
        for forbidden in ("apt-get", "apk add", "COPY . .", "RUN chmod -R 777"):
            self.assertNotIn(forbidden, dockerfile)

    def test_sqlite_wal_foreign_keys_integrity_and_hardlink_on_temp_volume(self):
        with TemporaryDirectory() as temp:
            db = Path(temp) / "probe.db"
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
                conn.execute("CREATE TABLE child (ref INTEGER REFERENCES parent(id))")
                conn.execute("INSERT INTO parent VALUES (1, 'offline')")
                conn.execute("INSERT INTO child VALUES (1)")
                conn.commit()
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertFalse(conn.execute("PRAGMA foreign_key_check").fetchall())
            with sqlite3.connect(db) as conn:
                self.assertEqual(
                    conn.execute("SELECT note FROM parent WHERE id=1").fetchone()[0],
                    "offline",
                )
            # Same-filesystem tmpfs only; NAS SMB/NFS hardlink semantics
            # still require a separate, explicitly approved host test.
            linked = Path(temp) / "linked.db"
            os.link(db, linked)
            self.assertEqual(linked.stat().st_ino, db.stat().st_ino)

    def test_tls_default_context_requires_verified_system_ca(self):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreater(context.cert_store_stats()["x509_ca"], 0)
        # This deliberately does not contact any real HTTPS service.

    def test_v11_runner_disabled_before_accessing_live_stores(self):
        from app import v11_main

        with patch.dict(os.environ, {"SEEKPULSE_V11_ENABLE": "0"}):
            with self.assertRaisesRegex(RuntimeError, "v11_not_explicitly_enabled"):
                v11_main.main(["--run"])

    def test_compose_preserves_private_local_host_network_contract(self):
        raw = (ROOT / "compose.v11.yaml").read_text(encoding="utf-8")
        active = "\n".join(
            line for line in raw.splitlines()
            if not line.lstrip().startswith("#")
        )
        for required in (
            "network_mode: host", "read_only: true", "cap_drop:", "- ALL",
            "no-new-privileges:true", "create_host_path: false",
            'restart: "no"', "SEEKPULSE_IMAGE:?",
        ):
            self.assertIn(required, active)
        for forbidden in (
            "privileged: true", "docker.sock", "ports:", "build:",
        ):
            self.assertNotIn(forbidden, active)


if __name__ == "__main__":
    unittest.main()
