"""Negative tests for source/registry/platform RC publishing gates (no IO)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import copy
import unittest

from scripts.v11_rc_release_verify import (
    RCVerificationError, verify_index, verify_local, verify_remote,
)

BASE = Path(__file__).resolve().parents[1]
REVISION = "a" * 40
VERSION = "v1.1.0-rc.1"
DAMD = "sha256:" + "1" * 64
DARM = "sha256:" + "2" * 64
INDEX = "sha256:" + "3" * 64
IMAGE = "ghcr.io/aspeternity/seekpulse"
IMAGE_ID = "sha256:" + "4" * 64


def sample(arch="amd64", published=True):
    now = datetime.now(timezone.utc)
    def iso(d):
        return d.isoformat().replace("+00:00", "Z")
    inspect = {
        "Id": IMAGE_ID, "Os": "linux", "Architecture": arch,
        "RepoDigests": [f"{IMAGE}@{INDEX}"] if published else [],
        "Config": {
            "User": "10001:10001",
            "Entrypoint": ["python", "-m", "app.v11_main"],
            "Cmd": ["--run"], "Env": ["HOME=/tmp", "PYTHONDONTWRITEBYTECODE=1"],
            "Labels": {
                "org.opencontainers.image.title": "SeekPulse",
                "org.opencontainers.image.source": "https://github.com/Aspeternity/SeekPulse",
                "org.opencontainers.image.version": VERSION,
                "org.opencontainers.image.revision": REVISION,
                "org.opencontainers.image.licenses": "MIT",
            },
        },
    }
    name = f"seekpulse-{'remote-verified' if published else 'prepublish-local'}:{arch}"
    scan = {
        "SchemaVersion": 2, "ArtifactType": "container_image",
        "ArtifactName": name,
        "Metadata": {
            "ImageID": IMAGE_ID, "OS": {"Family": "alpine", "Name": "3.24"},
        },
        "Results": [
            {"Class": "os-pkgs", "Type": "alpine", "Vulnerabilities": []},
            {"Class": "lang-pkgs", "Type": "python-pkg", "Vulnerabilities": []},
        ],
    }
    sbom = {
        "bomFormat": "CycloneDX", "specVersion": "1.6",
        "metadata": {"timestamp": iso(now)},
        "components": [
            *({"type": "library", "purl": f"pkg:apk/alpine/lib-{i}@1"}
              for i in range(12)),
            *({"type": "library", "purl": f"pkg:pypi/pkg-{i}@1"}
              for i in range(8)),
        ],
    }
    db = {"Version": 2, "UpdatedAt": iso(now - timedelta(hours=2)),
          "DownloadedAt": iso(now - timedelta(hours=1)),
          "NextUpdate": iso(now + timedelta(hours=5))}
    return dict(scan=scan, sbom=sbom, db=db, inspect=inspect, arch=arch,
                revision=REVISION, version=VERSION)


def index():
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {"mediaType": "application/vnd.oci.image.manifest.v1+json",
             "digest": DAMD, "size": 1500,
             "platform": {"os": "linux", "architecture": "amd64"}},
            {"mediaType": "application/vnd.oci.image.manifest.v1+json",
             "digest": DARM, "size": 1500,
             "platform": {"os": "linux", "architecture": "arm64"}},
        ],
    }


class ReleaseGates(unittest.TestCase):
    def test_index_exact_two_distinct_platforms(self):
        self.assertEqual(verify_index(index(), amd64_digest=DAMD,
                                      arm64_digest=DARM)["linux/arm64"], DARM)

    def test_index_negative_variants(self):
        for mode in ("extra", "duplicate", "changed_digest",
                     "same_digest", "wrong_media", "wrong_size"):
            with self.subTest(mode=mode):
                obj = index()
                amd = DAMD
                arm = DARM
                if mode == "extra":
                    obj["manifests"].append(copy.deepcopy(obj["manifests"][0]))
                elif mode == "duplicate":
                    obj["manifests"][1]["platform"]["architecture"] = "amd64"
                elif mode == "changed_digest":
                    obj["manifests"][1]["digest"] = "sha256:" + "f" * 64
                elif mode == "same_digest":
                    arm = amd
                elif mode == "wrong_media":
                    obj["manifests"][0]["mediaType"] = "text/plain"
                elif mode == "wrong_size":
                    obj["manifests"][0]["size"] = 0
                with self.assertRaises(RCVerificationError):
                    verify_index(obj, amd64_digest=amd, arm64_digest=arm)

    def test_remote_scanned_platform(self):
        x = sample()
        x["index_digest"] = INDEX
        x["platform_digest"] = DAMD
        value = verify_remote(**x)
        self.assertEqual(value["stage"], "REAL_REGISTRY_PULL_SCANNED_ZERO_CVES")
        self.assertTrue(all(n == 0 for n in value["counts"].values()))

    def test_remote_negative_identity_inventory_and_cves(self):
        checks = [
            ("wrong_arch", lambda x: x["inspect"].update(Architecture="arm64")),
            ("wrong_label", lambda x: x["inspect"]["Config"]["Labels"].update(
                {"org.opencontainers.image.revision": "b" * 40})),
            ("user_root", lambda x: x["inspect"]["Config"].update(User="0:0")),
            ("baked_secret", lambda x: x["inspect"]["Config"]["Env"].append("BOT_TOKEN=bad")),
            ("no_registry_ref", lambda x: x["inspect"].update(RepoDigests=[])),
            ("wrong_image_id", lambda x: x["scan"]["Metadata"].update(
                ImageID="sha256:" + "f" * 64)),
            ("cve", lambda x: x["scan"]["Results"][0].update(
                Vulnerabilities=[{"Severity": "HIGH"}])),
            ("missing_class", lambda x: x["scan"]["Results"].pop()),
            ("wrong_sbom", lambda x: x["sbom"].update(components=[])),
            ("stale_db", lambda x: x["db"].update(
                UpdatedAt=(datetime.now(timezone.utc)-timedelta(days=10)).isoformat())),
        ]
        for name, change in checks:
            with self.subTest(name=name):
                x = sample()
                x["index_digest"] = INDEX
                x["platform_digest"] = DAMD
                change(x)
                with self.assertRaises((RCVerificationError, ValueError)):
                    verify_remote(**x)

    def test_local_release_label_rejected(self):
        x = sample(published=False)
        x["inspect"]["Config"]["Labels"]["org.opencontainers.image.version"] = "0.0.0-ci"
        with self.assertRaises(RCVerificationError):
            verify_local(**x)

    def test_workflow_has_single_publish_event_and_no_pr_write(self):
        src = (BASE / ".github/workflows/v11-ghcr-rc-publish.yml").read_text()
        self.assertIn("release/v11-rc1-ghcr-publish", src)
        self.assertIn("pull_request:", src)
        self.assertIn("push:", src)
        self.assertIn("github.event_name == 'push'", src)
        self.assertIn("refs/heads/main", src)
        self.assertIn("packages: write", src)
        self.assertIn("attestations: write", src)
        self.assertIn("id-token: write", src)
        self.assertIn("gh release create", src)
        self.assertIn("scripts.v11_rc_release_verify", src)
        self.assertNotIn("ghcr.io/aspeternity/seekpulse:latest", src)
        self.assertIn("--source-digest", src)


if __name__ == "__main__":
    unittest.main()
