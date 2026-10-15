"""Docker-05: scoped V1.1 PyPI High fixes without legacy behavior changes.

G0 and older Docker CI run these static tests with the old S5 environment.
Real patched installs are checked by Docker-05 CI; actual images and live
Trivy CVE+CycloneDX results by Docker-04 CI on both architectures.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCHED = {
    "aiohttp": "3.14.3",
    "jaraco.context": "6.1.0",
    "wheel": "0.46.2",
    "setuptools": "84.0.0",
    "python-dotenv": "1.2.2",
}


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class NarrowSecurityOverrides(unittest.TestCase):
    def test_exactly_five_targeted_v11_version_pins(self):
        content = read("requirements-v11-security.txt")
        actual = [
            line.strip() for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(actual, [f"{name}=={version}" for name, version
                                  in PATCHED.items()])
        for line in actual:
            self.assertRegex(line, r"^[a-z][a-z.-]*==[0-9][0-9.]*$")
        for unsafe in ("--extra-index-url", "--trusted-host", "-e ", " git+"):
            self.assertNotIn(unsafe, content)

    def test_pins_impact_opt_in_dockerfile_only_and_are_one_layer(self):
        dockerfile = read("Dockerfile.v11")
        self.assertEqual(dockerfile.count("requirements-v11-security.txt"), 2)
        self.assertIn("-r requirements-s5.txt", dockerfile)
        self.assertIn("RUN apk add --no-cache --upgrade 'zlib=1.3.2-r1'", dockerfile)
        self.assertIn("apk info -v zlib | grep -Fx 'zlib-1.3.2-r1'", dockerfile)
        self.assertEqual(dockerfile.count("apk add "), 1)
        self.assertIn("RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1", dockerfile)
        self.assertIn(
            "&& python -m pip install --no-cache-dir --upgrade "
            "-r requirements-v11-security.txt", dockerfile
        )
        self.assertIn("&& python -m pip check", dockerfile)
        self.assertEqual(len(re.findall(r"(?m)^RUN python -m pip install",
                                        dockerfile)), 1)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn('ENTRYPOINT ["python", "-m", "app.v11_main"]', dockerfile)
        self.assertIn('CMD ["--run"]', dockerfile)

    def test_legacy_code_and_dependencies_are_untouched(self):
        self.assertIn("aiohttp==3.11.11", read("requirements.txt"))
        self.assertIn("python-dotenv==1.0.1", read("requirements.txt"))
        for path in (
            "requirements.txt", "requirements-s3.txt", "requirements-s4.txt",
            "requirements-s5.txt", "Dockerfile", "docker-compose.yml",
        ):
            self.assertNotIn("requirements-v11-security.txt", read(path))
        self.assertIn('CMD ["python", "-m", "app.main"]', read("Dockerfile"))

    def test_no_high_cve_suppression_or_implicit_release(self):
        workflow = read(".github/workflows/s7-v11-security-offline.yml")
        self.assertIn('--pkg-types os,library', workflow)
        self.assertIn('language["HIGH"] == 0', workflow)
        self.assertIn('language["CRITICAL"] == 0', workflow)
        self.assertIn("BLOCKED_HIGH_OR_CRITICAL", workflow)
        self.assertIn('report["release_ready"] is False', workflow)
        self.assertIn("V11_PATCHED_IMAGE_RUNTIME=PASS", workflow)
        self.assertIn('"pip": "26.2.1"', workflow)
        self.assertIn('"python-dotenv": "1.2.2"', workflow)
        self.assertIn("zlib-1.3.2-r1", workflow)
        self.assertNotIn("--ignore-unfixed", workflow)
        self.assertNotIn(".trivyignore", workflow)
        self.assertNotIn("packages: write", workflow)

    def test_new_patched_ci_checks_both_pythons_without_publication(self):
        ci = read(".github/workflows/s7-v11-cve-remediation.yml")
        self.assertIn("['3.11', '3.12']", ci)
        self.assertIn("-r requirements-s5.txt", ci)
        self.assertIn("-r requirements-v11-security.txt", ci)
        self.assertIn("python -m pip check", ci)
        self.assertIn("unittest discover -s tests -v", ci)
        self.assertIn("contents: read", ci)
        for unsafe in ("packages: write", "docker/login-action", "docker push",
                       "buildx --push", "upload-artifact", "gh release",
                       "secrets."):
            self.assertNotIn(unsafe, ci)


if __name__ == "__main__":
    unittest.main()
