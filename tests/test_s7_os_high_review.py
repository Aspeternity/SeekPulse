"""Docker-06: local OS High report cannot conceal actual Debian CVE risk."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from scripts.v11_os_high_review import OSHighEvidenceError, review_os_high

ROOT = Path(__file__).resolve().parents[1]
ID = "sha256:" + "a" * 64
IMAGE = "seekpulse-security-local:amd64"
LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")


def os_cve(cve: str, package: str = "libmount1") -> dict[str, str]:
    return {
        "VulnerabilityID": cve,
        "PkgName": package,
        "InstalledVersion": "2.41.5-0+deb13u1",
        "FixedVersion": "",
        "Severity": "HIGH",
    }


def inputs() -> dict:
    scan = {
        "SchemaVersion": 2,
        "ArtifactType": "container_image",
        "ArtifactName": IMAGE,
        "Metadata": {"ImageID": ID, "OS": {"Family": "debian", "Name": "13"}},
        "Results": [
            {"Class": "os-pkgs", "Vulnerabilities": [
                os_cve("CVE-2026-76642"),
                os_cve("CVE-2026-78408"),
            ]},
            {"Class": "lang-pkgs", "Vulnerabilities": []},
        ],
    }
    report = {
        "evidence": "VALID_LOCAL_SCAN_NOT_PUBLISHED",
        "platform": "linux/amd64",
        "image": IMAGE,
        "scanner_db": {
            "updated_at": "2026-10-15T00:00:00+00:00",
            "downloaded_at": "2026-10-15T01:00:00+00:00",
            "next_update": "2026-10-16T00:00:00+00:00",
        },
        "findings": {
            "by_package_class": {
                "os-pkgs": {s: 2 if s == "HIGH" else 0 for s in LEVELS},
                "lang-pkgs": {s: 0 for s in LEVELS},
            },
            "by_severity": {s: 2 if s == "HIGH" else 0 for s in LEVELS},
            "high_critical_unique_ids": 2,
        },
        "vulnerability_gate": "BLOCKED_HIGH_OR_CRITICAL",
        "ghcr_image_status": "NOT_PUBLISHED",
        "remote_index_digest": None,
        "release_authorized": False,
        "release_ready": False,
    }
    return {
        "scan": scan,
        "validated_report": report,
        "platform": "linux/amd64",
        "image": IMAGE,
    }


class ReportContractTests(unittest.TestCase):
    def test_actual_os_high_is_blocking_not_remediated(self):
        out = review_os_high(**inputs())
        self.assertEqual(out["os_high_records"], 2)
        self.assertEqual(out["os_distinct_high_critical_ids"], 2)
        self.assertEqual(out["risk_gate"], "BLOCKED_HIGH_OR_CRITICAL")
        self.assertEqual(
            out["historical_high_cves"]["CVE-2026-76642"]["scan_state"],
            "HIGH_REPORTED",
        )
        self.assertEqual(
            out["historical_high_cves"]["CVE-2026-76642"]["affected_packages"],
            [{"package": "libmount1", "installed": "2.41.5-0+deb13u1",
              "fixed": None}],
        )
        self.assertIsNone(out["remote_index_digest"])
        self.assertFalse(out["release_authorized"])
        self.assertFalse(out["release_ready"])

    def test_missing_historical_cve_is_not_claimed_fixed(self):
        out = review_os_high(**inputs())
        self.assertEqual(
            out["historical_high_cves"]["CVE-2025-69720"]["scan_state"],
            "NOT_REPORTED_VERIFY_UPSTREAM",
        )
        self.assertTrue(out["missing_id_does_not_prove_fixed"])
        self.assertEqual(len(out["historical_high_cves"]), 8)

    def test_new_cves_cannot_disappear_in_known_id_allowlist(self):
        sample = inputs()
        sample["scan"]["Results"][0]["Vulnerabilities"].append(
            os_cve("CVE-2026-999999", "ncurses-bin")
        )
        sample["validated_report"]["findings"]["by_package_class"]["os-pkgs"]["HIGH"] += 1
        sample["validated_report"]["findings"]["by_severity"]["HIGH"] += 1
        sample["validated_report"]["findings"]["high_critical_unique_ids"] += 1
        out = review_os_high(**sample)
        self.assertEqual(out["other_high_critical_cve_ids"], ["CVE-2026-999999"])
        self.assertEqual(out["risk_gate"], "BLOCKED_HIGH_OR_CRITICAL")

    def test_cross_check_detects_missing_and_faked_scan_counts(self):
        for key, value in (("HIGH", 0), ("HIGH", 99)):
            v = inputs()
            v["validated_report"]["findings"]["by_package_class"]["os-pkgs"][key] = value
            with self.subTest(value=value), self.assertRaisesRegex(
                    OSHighEvidenceError, "trivy_vs_validated_summary_mismatch"):
                review_os_high(**v)

    def test_duplicate_package_cve_records_keep_exact_count(self):
        a = inputs()
        a["scan"]["Results"][0]["Vulnerabilities"].append(
            os_cve("CVE-2026-76642", "libblkid1")
        )
        a["validated_report"]["findings"]["by_package_class"]["os-pkgs"]["HIGH"] = 3
        a["validated_report"]["findings"]["by_severity"]["HIGH"] = 3
        out = review_os_high(**a)
        self.assertEqual(out["os_high_records"], 3)
        self.assertEqual(out["os_distinct_high_critical_ids"], 2)
        self.assertEqual(
            out["historical_high_cves"]["CVE-2026-76642"]["affected_package_matches"],
            2,
        )

    def test_scan_does_not_verify_safe_just_because_no_cve_reported(self):
        a = inputs()
        a["scan"]["Results"][0]["Vulnerabilities"] = []
        a["validated_report"]["findings"]["by_package_class"]["os-pkgs"]["HIGH"] = 0
        a["validated_report"]["findings"]["by_severity"]["HIGH"] = 0
        a["validated_report"]["findings"]["high_critical_unique_ids"] = 0
        a["validated_report"]["vulnerability_gate"] = "NO_KNOWN_FINDINGS_AT_SCAN_TIME"
        out = review_os_high(**a)
        self.assertEqual(out["os_high_records"], 0)
        self.assertFalse(out["release_ready"])
        self.assertFalse(out["release_authorized"])
        self.assertTrue(all(v["scan_state"] == "NOT_REPORTED_VERIFY_UPSTREAM"
                            for v in out["historical_high_cves"].values()))

    def test_language_high_must_still_block_runtime_gate(self):
        a = inputs()
        a["scan"]["Results"][1]["Vulnerabilities"] = [
            {"VulnerabilityID": "CVE-2026-00010", "Severity": "HIGH"},
        ]
        a["validated_report"]["findings"]["by_package_class"]["lang-pkgs"]["HIGH"] = 1
        a["validated_report"]["findings"]["by_severity"]["HIGH"] = 3
        a["validated_report"]["findings"]["high_critical_unique_ids"] = 3
        out = review_os_high(**a)
        self.assertEqual(out["risk_gate"], "BLOCKED_HIGH_OR_CRITICAL")

    def test_fail_closed_if_os_or_pypi_class_was_not_scanned(self):
        for cls in ("os-pkgs", "lang-pkgs"):
            a = inputs()
            a["scan"]["Results"] = [
                r for r in a["scan"]["Results"] if r["Class"] != cls
            ]
            with self.subTest(missing=cls), self.assertRaisesRegex(
                    OSHighEvidenceError, "os_or_language_scan_missing"):
                review_os_high(**a)

    def test_fail_on_mismatched_image_identity_or_os(self):
        badcases = [
            ("scan", "ArtifactName", "ghcr.io/imaginary/production:latest"),
            ("scan", "ArtifactType", "filesystem"),
            ("validated_report", "platform", "linux/arm64"),
            ("validated_report", "image", "seekpulse-security-local:arm64"),
        ]
        for obj, key, bad in badcases:
            a = inputs()
            a[obj][key] = bad
            with self.subTest(key=key), self.assertRaises(OSHighEvidenceError):
                review_os_high(**a)
        a = inputs()
        a["scan"]["Metadata"]["OS"]["Family"] = "alpine"
        with self.assertRaisesRegex(OSHighEvidenceError, "wrong_os_family"):
            review_os_high(**a)

    def test_reject_any_attempt_to_present_unauthorized_registry(self):
        for field, value in (
            ("release_ready", True), ("release_authorized", True),
            ("ghcr_image_status", "PUBLISHED"),
            ("remote_index_digest", "sha256:" + "f" * 64),
        ):
            a = inputs()
            a["validated_report"][field] = value
            with self.subTest(field=field), self.assertRaises(OSHighEvidenceError):
                review_os_high(**a)

    def test_no_high_cve_fraud_or_invalid_severity(self):
        for key, value in (
            ("PkgName", "../escape"),
            ("InstalledVersion", None),
            ("FixedVersion", "invalid/path"),
            ("VulnerabilityID", "bad  id"),
            ("Severity", "APPROVED"),
        ):
            a = inputs()
            a["scan"]["Results"][0]["Vulnerabilities"][0][key] = value
            with self.subTest(key=key), self.assertRaises(OSHighEvidenceError):
                review_os_high(**a)

    def test_unique_cve_count_and_gate_are_reconciled(self):
        for field, bad in (
            ("high_critical_unique_ids", 1),
            ("high_critical_unique_ids", 999),
        ):
            a = inputs()
            a["validated_report"]["findings"][field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(
                    OSHighEvidenceError, "unique_high_id_count_mismatch"):
                review_os_high(**a)
        a = inputs()
        a["validated_report"]["vulnerability_gate"] = "NO_KNOWN_FINDINGS_AT_SCAN_TIME"
        with self.assertRaisesRegex(OSHighEvidenceError, "existing_release_gate_inconsistent"):
            review_os_high(**a)


class SecurityIsolationContracts(unittest.TestCase):
    def test_no_runtime_changes_and_release_policy_stays_blocking(self):
        dockerfile = (ROOT / "Dockerfile.v11").read_text()
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("python:3.11-slim@sha256:", dockerfile)
        self.assertNotIn("sid", dockerfile)
        self.assertNotIn("apt-get", dockerfile)
        self.assertIn('CMD ["--run"]', dockerfile)
        compose = (ROOT / "compose.v11.yaml").read_text()
        for required in ("read_only: true", "cap_drop:", "- ALL",
                         "no-new-privileges:true", 'restart: "no"'):
            self.assertIn(required, compose)
        for unsafe in ("privileged: true", "/var/run/docker.sock", "ports:"):
            self.assertNotIn(unsafe, compose)

    def test_docker06_ci_stays_read_only_and_reports_unknown(self):
        ci = (ROOT / ".github/workflows/s7-v11-os-high-offline.yml").read_text()
        self.assertIn("contents: read", ci)
        self.assertIn("python:3.11-slim-bookworm", ci)
        self.assertIn("linux/amd64", ci)
        self.assertIn("linux/arm64", ci)
        self.assertIn("OS_HIGH_CANDIDATE_NOT_RELEASED", ci)
        for unsafe in ("packages: write", "docker/login-action", "docker push",
                       "buildx --push", "trivyignore", "--ignore-unfixed",
                       "gh release", "upload-artifact", "secrets."):
            self.assertNotIn(unsafe, ci)

    def test_existing_cve_gate_integrates_new_proof(self):
        wf = (ROOT / ".github/workflows/s7-v11-security-offline.yml").read_text()
        self.assertIn("scripts/v11_os_high_review.py", wf)
        self.assertIn("BLOCKED_HIGH_OR_CRITICAL", wf)
        self.assertIn("--pkg-types os,library", wf)
        self.assertIn('language["HIGH"] == 0', wf)


if __name__ == "__main__":
    unittest.main()
