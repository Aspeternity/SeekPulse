"""Docker-09: stdlib-only negative tests for no-publish pre-release CVE review."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from scripts.v11_pre_release_review import (
    BASE, PreReleaseReviewError, review_pre_release,
)
from scripts.v11_security_evidence import verify_security_evidence

ROOT = Path(__file__).resolve().parents[1]
REV = "e" * 40
NOW = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
IMAGE = "seekpulse-prepublish-local:amd64"
IDENTITY = "sha256:" + "a" * 64


def stamp(dt):
    return dt.isoformat().replace("+00:00", "Z")


def fixture():
    scan = {
        "SchemaVersion": 2,
        "ArtifactType": "container_image",
        "ArtifactName": IMAGE,
        "Metadata": {
            "ImageID": IDENTITY, "OS": {"Family": "alpine", "Name": "3.24"},
        },
        "Results": [
            {
                "Class": "os-pkgs", "Type": "alpine",
                "Vulnerabilities": [
                    {"Severity": "MEDIUM", "VulnerabilityID": "CVE-2026-10001",
                     "PkgName": "libexample", "InstalledVersion": "1.2",
                     "FixedVersion": "1.3"},
                ],
            },
            {
                "Class": "lang-pkgs", "Type": "python-pkg",
                "Vulnerabilities": [
                    {"Severity": "LOW", "VulnerabilityID": "GHSA-aaaa-bbbb-cccc",
                     "PkgName": "a-package", "InstalledVersion": "2.4"},
                ],
            },
        ],
    }
    db = {
        "Version": 2,
        "UpdatedAt": stamp(NOW-timedelta(hours=2)),
        "DownloadedAt": stamp(NOW-timedelta(hours=1)),
        "NextUpdate": stamp(NOW+timedelta(hours=5)),
    }
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {"timestamp": stamp(NOW)},
        "components": [
            *({"type": "library", "purl": f"pkg:apk/alpine/lib-{i}@1.0"}
              for i in range(12)),
            *({"type": "library", "purl": f"pkg:pypi/example-{i}@1.0"}
              for i in range(8)),
        ],
    }
    inspect = {
        "Id": IDENTITY, "Architecture": "amd64", "Os": "linux",
        "RepoDigests": [],
        "Config": {
            "User": "10001:10001",
            "Entrypoint": ["python", "-m", "app.v11_main"],
            "Cmd": ["--run"],
        },
    }
    validated = verify_security_evidence(
        scan=scan, sbom=sbom, db_metadata=db, image_inspect=inspect,
        platform="linux/amd64", image_tag=IMAGE, os_family="alpine", now=NOW,
    )
    return {"scan": scan, "validated": validated, "revision": REV,
            "platform": "linux/amd64", "image": IMAGE,
            "version": "v1.1.0-rc.1", "now": NOW}


class LocalPreReleaseContracts(unittest.TestCase):
    def test_good_medium_low_are_visible_but_never_approved(self):
        result = review_pre_release(**fixture())
        self.assertEqual(result["status"], "MANUAL_RELEASE_SECURITY_REVIEW_REQUIRED")
        self.assertEqual(result["affected_package_vulnerability_records"]["MEDIUM"], 1)
        self.assertEqual(result["affected_package_vulnerability_records"]["LOW"], 1)
        self.assertEqual(result["unique_vulnerability_ids"], 2)
        self.assertEqual(result["base_image"], BASE)
        self.assertEqual(result["manual_findings"][0]["package"], "libexample")
        self.assertEqual(result["manual_findings"][0]["trivy_fixed_version"], "1.3")
        self.assertEqual(
            result["manual_findings"][0]["patch_hint"],
            "FIX_VERSION_REPORTED_REVIEW_UPSTREAM",
        )
        self.assertEqual(result["manual_findings"][1]["trivy_fixed_version"], "")
        self.assertEqual(result["manual_findings"][1]["manual_disposition"], "NOT_REVIEWED")
        self.assertFalse(result["release_ready"])
        self.assertFalse(result["release_authorized"])
        self.assertFalse(result["manual_review_completed"])
        self.assertFalse(result["image_signed"])
        self.assertFalse(result["sbom_signed"])
        self.assertFalse(result["build_provenance_attested"])
        self.assertEqual(result["ghcr_image_status"], "NOT_PUBLISHED")
        self.assertIsNone(result["remote_index_digest"])
        self.assertIsNone(result["release_proposal"]["approved_compose_reference"])

    def test_new_high_is_reported_as_blocked_not_auto_accepted(self):
        v = fixture()
        v["scan"]["Results"][0]["Vulnerabilities"][0]["Severity"] = "HIGH"
        v["validated"]["findings"]["by_package_class"]["os-pkgs"]["MEDIUM"] = 0
        v["validated"]["findings"]["by_package_class"]["os-pkgs"]["HIGH"] = 1
        v["validated"]["findings"]["by_severity"]["MEDIUM"] = 0
        v["validated"]["findings"]["by_severity"]["HIGH"] = 1
        v["validated"]["findings"]["high_critical_unique_ids"] = 1
        v["validated"]["vulnerability_gate"] = "BLOCKED_HIGH_OR_CRITICAL"
        got = review_pre_release(**v)
        self.assertEqual(got["status"], "BLOCKED_HIGH_OR_CRITICAL")
        self.assertFalse(got["release_ready"])

    def test_unknown_severity_is_blocked_not_suppressed(self):
        v = fixture()
        v["scan"]["Results"][1]["Vulnerabilities"][0]["Severity"] = "UNKNOWN"
        v["validated"]["findings"]["by_package_class"]["lang-pkgs"]["LOW"] = 0
        v["validated"]["findings"]["by_package_class"]["lang-pkgs"]["UNKNOWN"] = 1
        v["validated"]["findings"]["by_severity"]["LOW"] = 0
        v["validated"]["findings"]["by_severity"]["UNKNOWN"] = 1
        got = review_pre_release(**v)
        self.assertEqual(got["status"], "BLOCKED_UNKNOWN_SEVERITY")
        self.assertFalse(got["release_ready"])

    def test_no_findings_is_still_no_release_approval(self):
        v = fixture()
        for section in v["scan"]["Results"]:
            section["Vulnerabilities"] = []
        for c in v["validated"]["findings"]["by_package_class"].values():
            for name in c:
                c[name] = 0
        for name in v["validated"]["findings"]["by_severity"]:
            v["validated"]["findings"]["by_severity"][name] = 0
        v["validated"]["vulnerability_gate"] = "NO_KNOWN_FINDINGS_AT_SCAN_TIME"
        got = review_pre_release(**v)
        self.assertEqual(got["status"], "MANUAL_RELEASE_SECURITY_REVIEW_REQUIRED")
        self.assertEqual(got["manual_findings"], [])
        self.assertFalse(got["release_authorized"])

    def test_class_totals_cannot_be_forged(self):
        for field in ("by_class", "by_severity", "ids"):
            v = fixture()
            if field == "by_class":
                v["validated"]["findings"]["by_package_class"]["os-pkgs"]["MEDIUM"] = 0
            elif field == "by_severity":
                v["validated"]["findings"]["by_severity"]["LOW"] = 0
            else:
                v["validated"]["findings"]["high_critical_unique_ids"] = 2
            with self.subTest(field=field), self.assertRaises(PreReleaseReviewError):
                review_pre_release(**v)

    def test_missing_os_python_classes_fail_closed(self):
        for klass in ("os-pkgs", "lang-pkgs"):
            v = fixture()
            v["scan"]["Results"] = [
                section for section in v["scan"]["Results"]
                if section["Class"] != klass
            ]
            with self.subTest(klass=klass), self.assertRaisesRegex(
                PreReleaseReviewError, "incomplete_os_or_python_trivy_coverage"
            ):
                review_pre_release(**v)

    def test_scanner_and_validated_identity_must_match(self):
        variants = (
            ("wrong_scan_image", lambda v: v["scan"].update(ArtifactName="other")),
            ("wrong_report_image", lambda v: v["validated"].update(image="other")),
            ("wrong_report_platform", lambda v: v["validated"].update(platform="linux/arm64")),
            ("wrong_scan_os", lambda v: v["scan"]["Metadata"]["OS"].update(Family="debian")),
            ("wrong_scan_type", lambda v: v["scan"]["Results"][0].update(Type="debian")),
            ("wrong_report_os", lambda v: v["validated"].update(os_family="debian")),
            ("invalid_local_tag", lambda v: v.update(image="ghcr.io/aspeternity/seekpulse:latest")),
        )
        for name, modify in variants:
            v = fixture()
            modify(v)
            with self.subTest(name=name), self.assertRaises(PreReleaseReviewError):
                review_pre_release(**v)

    def test_already_published_or_authorized_report_rejected(self):
        for field, value in (
            ("ghcr_image_status", "PUBLISHED"),
            ("release_ready", True),
            ("release_authorized", True),
            ("remote_index_digest", "sha256:" + "a"*64),
            ("requires_separate_user_approval", False),
        ):
            v = fixture()
            v["validated"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                PreReleaseReviewError, "security_report_claims_release"
            ):
                review_pre_release(**v)

    def test_invalid_version_revision_or_architecture_rejected(self):
        for key, value in (
            ("revision", "a"*7), ("revision", "A"*40),
            ("version", "latest"), ("version", "v1.1.0-rc.0"),
            ("platform", "linux/386"), ("platform", "linux/arm64"),
        ):
            v = fixture()
            v[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                review_pre_release(**v)

    def test_missing_public_package_info_rejected(self):
        for field, val in (
            ("PkgName", ""), ("InstalledVersion", None),
            ("FixedVersion", "\nFAKE_CI=PASS"),
            ("VulnerabilityID", "CVE-2026-1234\nTOKEN=leak"),
        ):
            v = fixture()
            v["scan"]["Results"][0]["Vulnerabilities"][0][field] = val
            with self.subTest(field=field), self.assertRaises(PreReleaseReviewError):
                review_pre_release(**v)

    def test_forged_stale_or_future_scanner_db_rejected(self):
        for field, timestamp in (
            ("updated_at", stamp(NOW - timedelta(days=4))),
            ("downloaded_at", stamp(NOW + timedelta(hours=2))),
            ("updated_at", "bad"),
        ):
            v = fixture()
            v["validated"]["scanner_db"][field] = timestamp
            with self.subTest(field=field), self.assertRaises(PreReleaseReviewError):
                review_pre_release(**v)

    def test_image_base_and_release_restrictions_unchanged(self):
        base = (ROOT / "Dockerfile.v11").read_text()
        compose = (ROOT / "compose.v11.yaml").read_text()
        self.assertIn("FROM " + BASE, base)
        self.assertIn("USER 10001:10001", base)
        self.assertIn('ENTRYPOINT ["python", "-m", "app.v11_main"]', base)
        self.assertIn("network_mode: host", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("create_host_path: false", compose)
        self.assertNotIn("docker.sock", compose)
        self.assertNotIn("build:", compose)

    def test_readonly_workflow_cannot_create_remote_release(self):
        workflow = (ROOT / ".github/workflows/s7-v11-prepublish-review-offline.yml").read_text()
        active = "\n".join(
            line for line in workflow.splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertIn("contents: read", active)
        self.assertIn("ubuntu-24.04-arm", active)
        self.assertIn("linux/amd64", active)
        self.assertIn("linux/arm64", active)
        self.assertIn("scripts/v11_security_evidence.py", active)
        self.assertIn("scripts/v11_pre_release_review.py", active)
        self.assertIn("version: v0.75.0", active)
        for forbidden in (
            "packages: write", "contents: write", "secrets.",
            "docker/login-action", "docker push", "--push", "gh release",
            "upload-artifact", "build-push-action", "cache-to: type=registry",
            "type=registry", "trivyignore", "curl ghcr.io",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, active)


if __name__ == "__main__":
    unittest.main()
