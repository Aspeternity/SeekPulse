"""Docker-04 fail-closed local CVE/SBOM evidence tests, no network or secrets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import unittest

from scripts.v11_security_evidence import (
    SecurityEvidenceError,
    verify_security_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)
IMAGE = "seekpulse-security-local:amd64"
IMAGE_ID = "sha256:" + "b" * 64
BASE_DIGEST = "d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929"


def stamp(date):
    return date.isoformat().replace("+00:00", "Z")


def fixture():
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {"timestamp": stamp(NOW)},
        "components": [
            *({"type": "library", "purl": f"pkg:deb/debian/lib{n}@1.0"}
              for n in range(12)),
            *({"type": "library", "purl": f"pkg:pypi/example-{n}@1.0"}
              for n in range(8)),
        ],
    }
    scan = {
        "SchemaVersion": 2,
        "ArtifactType": "container_image",
        "ArtifactName": IMAGE,
        "Metadata": {"ImageID": IMAGE_ID, "OS": {"Family": "debian", "Name": "13"}},
        "Results": [
            {"Class": "os-pkgs", "Type": "debian", "Vulnerabilities": []},
            {"Class": "lang-pkgs", "Type": "python-pkg", "Vulnerabilities": []},
        ],
    }
    db = {
        "Version": 2,
        "UpdatedAt": stamp(NOW - timedelta(hours=2)),
        "DownloadedAt": stamp(NOW - timedelta(hours=1)),
        "NextUpdate": stamp(NOW + timedelta(hours=4)),
    }
    image = {
        "Os": "linux",
        "Architecture": "amd64",
        "Id": IMAGE_ID,
        "RepoDigests": [],
        "Config": {
            "User": "10001:10001",
            "Entrypoint": ["python", "-m", "app.v11_main"],
            "Cmd": ["--run"],
        },
    }
    return {
        "scan": scan, "sbom": sbom, "db_metadata": db,
        "image_inspect": image, "platform": "linux/amd64",
        "image_tag": IMAGE, "now": NOW,
    }


class VulnerabilityGate(unittest.TestCase):
    def test_good_scan_is_not_production_release_approval(self):
        r = verify_security_evidence(**fixture())
        self.assertEqual(r["evidence"], "VALID_LOCAL_SCAN_NOT_PUBLISHED")
        self.assertEqual(r["inventory"], {"debian_packages": 12, "pypi_packages": 8})
        self.assertEqual(r["vulnerability_gate"], "NO_KNOWN_FINDINGS_AT_SCAN_TIME")
        self.assertIsNone(r["remote_index_digest"])
        self.assertFalse(r["release_authorized"])
        self.assertFalse(r["release_ready"])

    def test_alpine_inventory_and_cross_family_evidence_fail_closed(self):
        data = fixture()
        data["os_family"] = "alpine"
        data["scan"]["Metadata"]["OS"] = {"Family": "alpine", "Name": "3.24"}
        data["scan"]["Results"][0]["Type"] = "alpine"
        for item in data["sbom"]["components"]:
            item["purl"] = item["purl"].replace("pkg:deb/debian/", "pkg:apk/alpine/")
        report = verify_security_evidence(**data)
        self.assertEqual(report["os_family"], "alpine")
        self.assertEqual(report["inventory"], {"alpine_packages": 12, "pypi_packages": 8})
        self.assertEqual(report["vulnerability_gate"], "NO_KNOWN_FINDINGS_AT_SCAN_TIME")
        self.assertFalse(report["release_authorized"])
        self.assertFalse(report["release_ready"])

        for kind in ("scan_os", "os_type", "sbom", "expected"):
            bad = fixture()
            bad["os_family"] = "alpine"
            bad["scan"]["Metadata"]["OS"] = {"Family": "alpine", "Name": "3.24"}
            bad["scan"]["Results"][0]["Type"] = "alpine"
            for item in bad["sbom"]["components"]:
                item["purl"] = item["purl"].replace("pkg:deb/debian/", "pkg:apk/alpine/")
            if kind == "scan_os":
                bad["scan"]["Metadata"]["OS"]["Family"] = "debian"
            elif kind == "os_type":
                bad["scan"]["Results"][0]["Type"] = "debian"
            elif kind == "sbom":
                bad["sbom"]["components"] = [
                    c for c in bad["sbom"]["components"]
                    if not c["purl"].startswith("pkg:apk/")
                ]
            else:
                bad["os_family"] = "unknown"
            with self.subTest(mismatch=kind), self.assertRaises(SecurityEvidenceError):
                verify_security_evidence(**bad)

    def test_alpine_new_high_must_still_block(self):
        data = fixture()
        data["os_family"] = "alpine"
        data["scan"]["Metadata"]["OS"] = {"Family": "alpine", "Name": "3.24"}
        data["scan"]["Results"][0]["Type"] = "alpine"
        for item in data["sbom"]["components"]:
            item["purl"] = item["purl"].replace("pkg:deb/debian/", "pkg:apk/alpine/")
        data["scan"]["Results"][0]["Vulnerabilities"] = [
            {"VulnerabilityID": "CVE-2026-SIMULATED", "Severity": "HIGH",
             "PkgName": "libssl3", "InstalledVersion": "3.24.0"}
        ]
        report = verify_security_evidence(**data)
        self.assertEqual(report["vulnerability_gate"], "BLOCKED_HIGH_OR_CRITICAL")
        self.assertFalse(report["release_ready"])

    def test_high_critical_block_even_if_unfixed_and_ci_scan_succeeds(self):
        data = fixture()
        data["scan"]["Results"][0]["Vulnerabilities"] = [
            {
                "VulnerabilityID": "CVE-2026-1234", "Severity": "CRITICAL",
                "FixedVersion": "", "PkgName": "openssl",
            },
            {
                "VulnerabilityID": "CVE-2026-5678", "Severity": "HIGH",
                "FixedVersion": "1.2.3", "PkgName": "libexample",
            },
        ]
        verdict = verify_security_evidence(**data)
        self.assertEqual(verdict["vulnerability_gate"], "BLOCKED_HIGH_OR_CRITICAL")
        self.assertEqual(verdict["findings"]["high_critical_unique_ids"], 2)
        self.assertEqual(
            verdict["findings"]["high_critical_with_fixed_version_unique_ids"], 1
        )
        self.assertFalse(verdict["release_ready"])
        self.assertEqual(verdict["findings"]["high_critical_affected_package_matches"], 2)
        sample = verdict["findings"]["high_critical_package_sample"]
        self.assertEqual({entry["package"] for entry in sample}, {"openssl", "libexample"})
        self.assertEqual(verdict["findings"]["by_package_class"]["os-pkgs"]["HIGH"], 1)

    def test_medium_and_low_require_review_not_clearance(self):
        data = fixture()
        data["scan"]["Results"][1]["Vulnerabilities"] = [
            {"VulnerabilityID": "GHSA-example", "Severity": "MEDIUM"},
            {"VulnerabilityID": "CVE-2026-0001", "Severity": "LOW"},
        ]
        r = verify_security_evidence(**data)
        self.assertEqual(r["vulnerability_gate"], "REVIEW_REQUIRED_NONBLOCKING")
        self.assertFalse(r["release_ready"])

    def test_stale_and_missing_db_fail_closed(self):
        for field, bad in (
            ("UpdatedAt", stamp(NOW - timedelta(days=6))),
            ("DownloadedAt", stamp(NOW - timedelta(days=3))),
            ("NextUpdate", stamp(NOW - timedelta(days=4))),
            ("UpdatedAt", "0001-01-01T00:00:00Z"),
            ("DownloadedAt", None),
            ("Version", None),
        ):
            with self.subTest(field=field, bad=bad):
                inputs = fixture()
                inputs["db_metadata"][field] = bad
                with self.assertRaises(SecurityEvidenceError):
                    verify_security_evidence(**inputs)

    def test_future_db_or_sbom_is_not_accepted(self):
        case = fixture()
        case["db_metadata"]["UpdatedAt"] = stamp(NOW + timedelta(hours=4))
        with self.assertRaisesRegex(SecurityEvidenceError, "db_clock_in_future"):
            verify_security_evidence(**case)
        case = fixture()
        case["sbom"]["metadata"]["timestamp"] = stamp(NOW - timedelta(days=5))
        with self.assertRaisesRegex(SecurityEvidenceError, "stale_sbom"):
            verify_security_evidence(**case)

    def test_missing_os_or_python_inventory_is_not_a_pass(self):
        for prefix in ("pkg:deb/", "pkg:pypi/"):
            data = fixture()
            data["sbom"]["components"] = [
                c for c in data["sbom"]["components"]
                if not c["purl"].startswith(prefix)
            ]
            with self.subTest(prefix=prefix), self.assertRaises(SecurityEvidenceError):
                verify_security_evidence(**data)

    def test_scanner_must_cover_os_and_language_targets(self):
        for classification in ("os-pkgs", "lang-pkgs"):
            data = fixture()
            data["scan"]["Results"] = [
                result for result in data["scan"]["Results"]
                if result["Class"] != classification
            ]
            with self.subTest(classification=classification):
                with self.assertRaisesRegex(SecurityEvidenceError, "scan_missing"):
                    verify_security_evidence(**data)

    def test_empty_or_wrong_image_evidence_fails(self):
        for key, bad in (
            ("ArtifactType", "filesystem"),
            ("ArtifactName", "different_image"),
        ):
            data = fixture()
            data["scan"][key] = bad
            with self.subTest(key=key), self.assertRaises(SecurityEvidenceError):
                verify_security_evidence(**data)
        data = fixture()
        data["scan"]["Results"] = []
        with self.assertRaisesRegex(SecurityEvidenceError, "missing_vulnerability"):
            verify_security_evidence(**data)

    def test_image_config_architecture_and_identity_must_match(self):
        for field, bad in (
            ("Architecture", "arm64"), ("Os", "windows"),
            ("RepoDigests", ["ghcr.io/aspeternity/seekpulse@sha256:fake"]),
            ("Id", "sha256:" + "a" * 64),
        ):
            data = fixture()
            data["image_inspect"][field] = bad
            with self.subTest(field=field), self.assertRaises(SecurityEvidenceError):
                verify_security_evidence(**data)
        for field, bad in (
            ("User", "root"),
            ("Entrypoint", ["sh"]),
            ("Cmd", ["--init-fresh"]),
        ):
            data = fixture()
            data["image_inspect"]["Config"][field] = bad
            with self.subTest(field=field), self.assertRaises(SecurityEvidenceError):
                verify_security_evidence(**data)

    def test_image_id_and_vulnerability_levels_cannot_be_faked(self):
        data = fixture()
        data["scan"]["Metadata"]["ImageID"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(SecurityEvidenceError, "local_image_id_mismatch"):
            verify_security_evidence(**data)
        data = fixture()
        data["scan"]["Results"][0]["Vulnerabilities"] = [
            {"VulnerabilityID": "CVE-fake", "Severity": "BLESSED"}
        ]
        with self.assertRaisesRegex(SecurityEvidenceError, "unknown_vulnerability"):
            verify_security_evidence(**data)


class SupplyChainContracts(unittest.TestCase):
    def test_python_base_is_true_pinned_official_multiarch_index(self):
        dockerfile = (ROOT / "Dockerfile.v11").read_text(encoding="utf-8")
        self.assertRegex(
            dockerfile,
            rf"(?m)^FROM python:3\.11-alpine3\.24@sha256:{BASE_DIGEST}$",
        )
        self.assertEqual(len(re.findall(r"(?m)^FROM ", dockerfile)), 1)
        self.assertNotIn("ARG PYTHON_BASE_IMAGE", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn('ENTRYPOINT ["python", "-m", "app.v11_main"]', dockerfile)
        self.assertIn('CMD ["--run"]', dockerfile)

    def test_ci_is_read_only_and_scanner_version_is_pinned(self):
        workflow = (
            ROOT / ".github/workflows/s7-v11-security-offline.yml"
        ).read_text(encoding="utf-8")
        active = "\n".join(
            line for line in workflow.splitlines()
            if not line.strip().startswith("#")
        )
        for forbidden in (
            "packages: write", "contents: write", "docker/login-action",
            "docker push", "buildx --push", "gh release create",
            "cache-to: type=registry", "secrets.", "upload-artifact",
        ):
            self.assertNotIn(forbidden, active)
        self.assertIn("contents: read", active)
        self.assertIn("version: v0.75.0", active)
        self.assertIn("aquasecurity/setup-trivy@e07451d2e059ed86c2870430ea286b3a9e0bf241", active)
        self.assertIn("linux/amd64", active)
        self.assertIn("linux/arm64", active)
        self.assertIn("scripts/v11_security_evidence.py", active)


if __name__ == "__main__":
    unittest.main()
