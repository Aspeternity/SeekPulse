"""S1 dependency compatibility lock audit; runs offline on CI's installed packages."""

from __future__ import annotations

from importlib import metadata
import os
from pathlib import Path
import unittest


REQUIRED_DISTRIBUTIONS = {
    "python-telegram-bot": "21.10",
    "aiosqlite": "0.20.0",
    "aiohttp": "3.11.11",
    "feedparser": "6.0.11",
    "python-dotenv": "1.0.1",
}

ROOT = Path(__file__).resolve().parents[1]


class PinnedDependencyContract(unittest.TestCase):
    def test_upstream_dependency_manifest_remains_pinned(self):
        manifest = ROOT / "requirements.txt"
        found = {}
        for line in manifest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self.assertEqual(line.count("=="), 1, "Unpinned or non-exact upstream dependency")
            name, version = line.split("==", 1)
            self.assertNotIn(name, found, "Duplicate upstream dependency")
            found[name] = version
        self.assertEqual(found, REQUIRED_DISTRIBUTIONS)

    def test_ci_imports_exact_upstream_installed_versions(self):
        # Baseline CI remains strictly pinned. Docker-05's explicitly
        # named opt-in V1.1 security job alone checks the patched aiohttp.
        mode = os.environ.get("SEEKPULSE_S7_V11_SECURITY_TEST")
        self.assertIn(mode, (None, "1"), "unsupported_dependency_test_mode")
        expected_versions = dict(REQUIRED_DISTRIBUTIONS)
        if mode == "1":
            expected_versions["aiohttp"] = "3.14.3"
        for name, expected in expected_versions.items():
            with self.subTest(distribution=name):
                self.assertEqual(metadata.version(name), expected)


if __name__ == "__main__":
    unittest.main()
