"""Docker-11: stdlib-only final evidence gate and supply-chain negative tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import unittest

from scripts.v11_final_release_gate import (
    FinalReleaseGateError, evaluate_final_release_evidence,
)
from scripts.v11_pre_release_review import BASE, review_pre_release
from scripts.v11_security_evidence import (
    SecurityEvidenceError, verify_security_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
REV = "e" * 40
IMAGE_ID = "sha256:" + "a" * 64
SOURCE = "https://github.com/Aspeternity/SeekPulse"
VERSION = "v1.1.0-rc.1"


def _date(dt):
    return dt.isoformat().replace("+00:00", "Z")


def fixture(arch="amd64"):
    image = f"seekpulse-prepublish-local:{arch}"
    platform = f"linux/{arch}"
    scan = {
        "SchemaVersion": 2, "ArtifactType": "container_image",
        "ArtifactName": image,
        "Metadata": {
            "ImageID": IMAGE_ID,
            "OS": {"Family": "alpine", "Name": "3.24"},
        },
        "Results": [
            {"Class": "os-pkgs", "Type": "alpine", "Vulnerabilities": []},
            {"Class": "lang-pkgs", "Type": "python-pkg", "Vulnerabilities": []},
        ],
    }
    sbom = {
        "bomFormat": "CycloneDX", "specVersion": "1.6",
        "metadata": {"timestamp": _date(NOW)},
        "components": [
            *({"type": "library", "purl": f"pkg:apk/alpine/lib-{i}@1"}
              for i in range(12)),
            *({"type": "library", "purl": f"pkg:pypi/package-{i}@1"}
              for i in range(8)),
        ],
    }
    db = {
        "Version": 2,
        "UpdatedAt": _date(NOW - timedelta(hours=2)),
        "DownloadedAt": _date(NOW - timedelta(hours=1)),
        "NextUpdate": _date(NOW + timedelta(hours=5)),
    }
    inspect = {
        "Id": IMAGE_ID, "Architecture": arch, "Os": "linux",
        "RepoDigests": [],
        "Config": {
            "User": "10001:10001",
            "Entrypoint": ["python", "-m", "app.v11_main"],
            "Cmd": ["--run"],
            "Labels": {
                "org.opencontainers.image.title": "SeekPulse",
                "org.opencontainers.image.source": SOURCE,
                "org.opencontainers.image.revision": REV,
                "org.opencontainers.image.version": "0.0.0-ci",
                "org.opencontainers.image.licenses": "MIT",
            },
            "Env": ["HOME=/tmp", "PYTHONDONTWRITEBYTECODE=1"],
        },
    }
    verified = verify_security_evidence(
        scan=scan, sbom=sbom, db_metadata=db, image_inspect=inspect,
        platform=platform, image_tag=image, os_family="alpine", now=NOW,
    )
    reviewed = review_pre_release(
        scan=scan, validated=verified, revision=REV,
        platform=platform, image=image, version=VERSION, now=NOW,
    )
    return {
        "scan": scan, "sbom": sbom, "db_metadata": db,
        "image_inspect": inspect, "validated": verified,
        "prepublish_review": reviewed, "revision": REV, "platform": platform,
        "image": image, "version": VERSION, "now": NOW,
    }


def run_fixture(params):
    return evaluate_final_release_evidence(**params)


class FinalReleaseGateContract(unittest.TestCase):
    def test_clean_two_local_platforms_still_cannot_release(self):
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                result = run_fixture(fixture(arch))
                self.assertEqual(
                    result["status"],
                    "LOCAL_EVIDENCE_CLEAN_AWAITING_MANUAL_RELEASE_APPROVAL",
                )
                self.assertEqual(result["platform"], "linux/" + arch)
                self.assertEqual(result["reviewed_source_sha"], REV)
                self.assertEqual(result["local_image_id"], IMAGE_ID)
                self.assertEqual(result["base_image"], BASE)
                self.assertTrue(result["local_cyclonedx_sbom_validated"])
                self.assertTrue(result["local_oci_source_labels_validated"])
                self.assertEqual(result["known_vulnerability_records_at_scan_time"], 0)
                self.assertFalse(result["remote_oci_index_verified"])
                self.assertFalse(result["remote_sbom_attestation_verified"])
                self.assertFalse(result["remote_signature_verified"])
                self.assertFalse(result["manual_release_security_review_completed"])
                self.assertFalse(result["release_ready"])
                self.assertFalse(result["release_authorized"])
                self.assertEqual(result["ghcr_image_status"], "NOT_PUBLISHED")
                self.assertIsNone(result["remote_index_digest"])
                self.assertIsNone(
                    result["release_proposal"]["approved_compose_reference"]
                )

    def test_each_severity_blocks_even_with_consistent_scan(self):
        for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"):
            v = fixture()
            v["scan"]["Results"][1]["Vulnerabilities"] = [{
                "Severity": level, "VulnerabilityID": "CVE-2026-10001",
                "PkgName": "example", "InstalledVersion": "1.0",
            }]
            v["validated"] = verify_security_evidence(
                scan=v["scan"], sbom=v["sbom"],
                db_metadata=v["db_metadata"],
                image_inspect=v["image_inspect"],
                platform=v["platform"], image_tag=v["image"],
                os_family="alpine", now=NOW,
            )
            v["prepublish_review"] = review_pre_release(
                scan=v["scan"], validated=v["validated"],
                revision=REV, platform=v["platform"],
                image=v["image"], version=VERSION, now=NOW,
            )
            with self.subTest(level=level), self.assertRaisesRegex(
                FinalReleaseGateError, "nonzero_or_missing_vulnerability_findings"
            ):
                run_fixture(v)

    def test_forged_report_and_inventory_are_detected(self):
        mutations = (
            ("validated-count", lambda v: v["validated"]["findings"]
             ["by_severity"].update(HIGH=1)),
            ("review-count", lambda v: v["prepublish_review"]
             ["affected_package_vulnerability_records"].update(MEDIUM=1)),
            ("inventory", lambda v: v["validated"]["inventory"]
             .update(alpine_packages=10000)),
            ("signature", lambda v: v["prepublish_review"]
             .update(image_signed=True)),
            ("attestation", lambda v: v["prepublish_review"]
             .update(build_provenance_attested=True)),
            ("approval", lambda v: v["validated"]
             .update(release_authorized=True)),
            ("remote", lambda v: v["prepublish_review"]
             .update(remote_index_digest="sha256:" + "b" * 64)),
            ("changed-source", lambda v: v["prepublish_review"]
             .update(reviewed_source_sha="c" * 40)),
        )
        for name, mutate in mutations:
            v = fixture()
            mutate(v)
            with self.subTest(name=name), self.assertRaises(
                (FinalReleaseGateError, SecurityEvidenceError)
            ):
                run_fixture(v)

    def test_refuse_mismatched_source_identity_image_architecture(self):
        changes = (
            ("source-arg", lambda v: v.update(revision="b" * 40)),
            ("source-label", lambda v: v["image_inspect"]["Config"]
             ["Labels"].update({"org.opencontainers.image.revision": "b" * 40})),
            ("changed-image", lambda v: v["image_inspect"]
             .update(Id="sha256:" + "b" * 64)),
            ("wrong-arch", lambda v: v["image_inspect"]
             .update(Architecture="arm64")),
            ("repo-digest", lambda v: v["image_inspect"]
             .update(RepoDigests=["ghcr.io/aspeternity/seekpulse@sha256:"
                                  + "a" * 64])),
            ("runtime-root", lambda v: v["image_inspect"]["Config"]
             .update(User="0:0")),
            ("baked-secret", lambda v: v["image_inspect"]["Config"]
             ["Env"].append("BOT_TOKEN=DO_NOT_PUBLISH")),
            ("bad-version", lambda v: v.update(version="latest")),
        )
        for name, mutate in changes:
            v = fixture()
            mutate(v)
            with self.subTest(name=name), self.assertRaises(ValueError):
                run_fixture(v)

    def test_db_sbom_and_os_python_coverage_fail_closed(self):
        mutations = (
            ("stale-db", lambda v: v["db_metadata"]
             .update(UpdatedAt=_date(NOW - timedelta(days=6)))),
            ("future-db", lambda v: v["db_metadata"]
             .update(DownloadedAt=_date(NOW + timedelta(days=1)))),
            ("stale-sbom", lambda v: v["sbom"]["metadata"]
             .update(timestamp=_date(NOW - timedelta(hours=7)))),
            ("no-os", lambda v: v["scan"]["Results"].pop(0)),
            ("no-pypi", lambda v: v["sbom"].update(
                components=v["sbom"]["components"][:12])),
            ("debian-os", lambda v: v["scan"]["Metadata"]["OS"]
             .update(Family="debian")),
        )
        for name, mutate in mutations:
            v = fixture()
            mutate(v)
            with self.subTest(name=name), self.assertRaises(ValueError):
                run_fixture(v)

    def test_reject_unaware_expected_review_clock(self):
        v = fixture()
        v["now"] = datetime(2026, 10, 15, 13, 0)
        with self.assertRaisesRegex(FinalReleaseGateError, "naive_audit_clock"):
            run_fixture(v)

    def test_pinned_official_base_and_runtime_are_unchanged(self):
        dockerfile = (ROOT / "Dockerfile.v11").read_text(encoding="utf-8")
        compose = (ROOT / "compose.v11.yaml").read_text(encoding="utf-8")
        self.assertIn("FROM " + BASE, dockerfile)
        self.assertIn("zlib=1.3.2-r1", dockerfile)
        self.assertIn("pip==26.2.1", dockerfile)
        self.assertIn("python -m pip check", dockerfile)
        self.assertIn("python -m pip uninstall --yes pip", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("network_mode: host", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("create_host_path: false", compose)
        self.assertIn("restart: \"no\"", compose)
        self.assertIn("${SEEKPULSE_IMAGE:?", compose)
        self.assertNotIn("docker.sock", compose)

    def test_release_relevant_actions_are_pinned_and_readonly(self):
        for name in (
            "g0-ci.yml",
            "s7-v11-release-readiness.yml",
            "s7-v11-security-offline.yml",
            "s7-v11-prepublish-review-offline.yml",
        ):
            workflow = (ROOT / ".github/workflows" / name).read_text(
                encoding="utf-8"
            )
            active = "\n".join(
                s for s in workflow.splitlines()
                if not s.lstrip().startswith("#")
            )
            refs = re.findall(r"\buses:\s*([^\s#]+)", active)
            self.assertTrue(refs, name)
            for action in refs:
                with self.subTest(workflow=name, action=action):
                    self.assertRegex(action, r"^[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
            self.assertIn("contents: read", active)
            for forbidden in (
                "packages: write", "contents: write", "id-token: write",
                "docker/login-action", "docker push", "--push",
                "gh release", "upload-artifact", "secrets.",
                "cache-to: type=registry", "type=registry", "trivyignore",
            ):
                with self.subTest(workflow=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, active)

    def test_precise_pr_head_and_local_final_gate_workflow_present(self):
        wf = (ROOT / ".github/workflows/s7-v11-prepublish-review-offline.yml"
              ).read_text(encoding="utf-8")
        self.assertIn("github.event.pull_request.head.sha || github.sha", wf)
        self.assertIn('SOURCE_SHA', wf)
        self.assertIn("scripts.v11_final_release_gate", wf)
        self.assertIn("FINAL_GHCR_OFFLINE_PREPUBLISH_GATE=", wf)
        self.assertIn("ubuntu-24.04-arm", wf)
        self.assertIn("- arch: amd64", wf)
        self.assertIn("- arch: arm64", wf)


if __name__ == "__main__":
    unittest.main()
