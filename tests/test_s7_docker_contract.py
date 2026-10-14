"""S7 Docker packaging regression: static, credential-free, no live network.

Executable image and Compose checks live in the S7 CI workflow, not here.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class DockerPackagingContract(unittest.TestCase):
    def test_opt_in_image_contains_all_runtime_dependencies_and_web_files(self):
        dockerfile = load("Dockerfile.v11")
        self.assertIn("FROM python:3.11-slim", dockerfile)
        self.assertIn("-r requirements-s5.txt", dockerfile)
        self.assertIn("COPY app ./app", dockerfile)
        self.assertIn('ENTRYPOINT ["python", "-m", "app.v11_main"]', dockerfile)
        self.assertIn('CMD ["--run"]', dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertNotIn("COPY . .", dockerfile)
        self.assertNotIn("BOT_TOKEN=", dockerfile)

    def test_compose_never_pulls_implicit_image_or_builds_on_user_host(self):
        compose = load("compose.v11.yaml")
        active = "\n".join(
            line for line in compose.splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertIn("SEEKPULSE_IMAGE:?", active)
        self.assertIn("SEEKPULSE_DATA_DIR:?", active)
        self.assertIn("create_host_path: false", active)
        self.assertIn('command: ["--run"]', active)
        self.assertIn('SEEKPULSE_V11_ENABLE: "1"', active)
        self.assertIn('restart: "no"', active)
        self.assertNotRegex(active, r"(?m)^\s*(?:build|ports|privileged):")
        self.assertNotIn("docker.sock", active)

    def test_existing_loopback_security_is_not_bypassed_by_compose(self):
        compose = load("compose.v11.yaml")
        self.assertIn("network_mode: host", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("cap_drop:", compose)
        self.assertIn("tmpfs:", compose)
        self.assertIn("127.0.0.1", load("app/v11_main.py"))
        self.assertIn("loopback_request", load("app/web.py"))
        self.assertIn("is_loopback", load("app/web_auth.py"))

    def test_sensitive_files_are_excluded_from_build_context(self):
        ignore = set(load(".dockerignore").splitlines())
        for pattern in (
            ".env", ".env.*", "data/", "**/*.db", "**/*.db-*",
            "**/*.session", "**/*.session-*", "secrets/", "backups/",
        ):
            self.assertIn(pattern, ignore)
        self.assertIn("!.env.example", ignore)

    def test_existing_default_legacy_contract_unchanged(self):
        self.assertIn('CMD ["python", "-m", "app.main"]', load("Dockerfile"))
        self.assertIn("build: .", load("docker-compose.yml"))
        # No accidental backwards-incompatible replacement of legacy files.
        self.assertNotIn("v11_main", load("docker-compose.yml"))

    def test_demo_and_documentation_are_explicitly_not_a_release(self):
        example = load(".env.v11.example")
        guide = load("docs/deployment/V1.1-docker-offline.md")
        self.assertIn("REPLACE_WITH_APPROVED_DIGEST", example)
        self.assertIn("NOT_RELEASED", guide)
        self.assertIn("Gate D", guide)
        self.assertTrue(re.search(r"(?m)^SEEKPULSE_TG_SESSION=$", example))


if __name__ == "__main__":
    unittest.main()
