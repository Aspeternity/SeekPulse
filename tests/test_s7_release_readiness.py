"""Docker-03 OCI and release naming tests. Stdlib-only, no external I/O."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.inspect_v11_oci import OCIValidationError, inspect_archive
from scripts.v11_release_policy import (
    IMAGE_REPOSITORY,
    draft_release_plan,
    validate_immutable_reference,
    validate_revision,
    validate_version,
)

ROOT = Path(__file__).resolve().parents[1]
REVISION = "e" * 40
VERSION = "0.0.0-ci"


def _json(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def _make_oci(
    archive: Path, *, edit_config=None, edit_index=None, corrupt_blob=False,
) -> None:
    """Create synthetic two-platform OCI with real SHA-256 descriptors."""
    blobs = {}
    layer = b"synthetic-oci-layer-with-no-user-data"

    def add(data: bytes) -> dict:
        digest = hashlib.sha256(data).hexdigest()
        blobs[digest] = data
        return {"digest": "sha256:" + digest, "size": len(data)}

    layer_desc = add(layer)
    manifests = []
    for architecture in ("amd64", "arm64"):
        config = {
            "os": "linux",
            "architecture": architecture,
            "rootfs": {"type": "layers", "diff_ids": [layer_desc["digest"]]},
            "config": {
                "User": "10001:10001",
                "Entrypoint": ["python", "-m", "app.v11_main"],
                "Cmd": ["--run"],
                "WorkingDir": "/app",
                "Env": ["PYTHONDONTWRITEBYTECODE=1"],
                "Labels": {
                    "org.opencontainers.image.title": "SeekPulse",
                    "org.opencontainers.image.source":
                        "https://github.com/Aspeternity/SeekPulse",
                    "org.opencontainers.image.version": VERSION,
                    "org.opencontainers.image.revision": REVISION,
                    "org.opencontainers.image.licenses": "MIT",
                },
            },
        }
        if edit_config is not None and architecture == "amd64":
            edit_config(config)
        config_desc = add(_json(config))
        manifest = {
            "schemaVersion": 2,
            "config": {
                **config_desc,
                "mediaType": "application/vnd.oci.image.config.v1+json",
            },
            "layers": [{
                **layer_desc,
                "mediaType": "application/vnd.oci.image.layer.v1.tar",
            }],
        }
        manifest_desc = add(_json(manifest))
        manifests.append({
            **manifest_desc,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "platform": {"os": "linux", "architecture": architecture},
        })
    index = {"schemaVersion": 2, "manifests": manifests}
    if edit_index is not None:
        edit_index(index)
    if corrupt_blob:
        digest = manifests[0]["digest"].split(":", 1)[1]
        blobs[digest] = b"X" * len(blobs[digest])
    paths = {
        "oci-layout": b'{"imageLayoutVersion":"1.0.0"}',
        "index.json": _json(index),
        **{"blobs/sha256/" + k: v for k, v in blobs.items()},
    }
    with tarfile.open(archive, "w") as output:
        for name, data in paths.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            output.addfile(member, io.BytesIO(data))


class ReleaseNamingPolicy(unittest.TestCase):
    def test_strict_full_semver_release_names(self):
        for name in ("v1.1.0", "v1.1.0-rc.1", "v2.0.0", "v0.9.12-rc.20"):
            self.assertEqual(validate_version(name), name)
        for invalid in (
            "latest", "main", "dev", "v1.1", "1.1.0", "v01.1.0",
            "v1.01.0", "v1.1.00", "v1.1.0-rc.0", "v1.1.0-beta.1",
            "v1.1.0-rc.01", "v1.1.0\n", "v1.1.0;docker push",
            "v1.1.0 ", "", "v1.1.0+build1",
        ):
            with self.subTest(name=repr(invalid)):
                with self.assertRaisesRegex(ValueError, "invalid_release_version"):
                    validate_version(invalid)

    def test_draft_cannot_be_confused_with_ghcr_publish(self):
        proposal = draft_release_plan("v1.1.0-rc.1", REVISION)
        self.assertEqual(
            proposal["proposed_tag"], IMAGE_REPOSITORY + ":v1.1.0-rc.1"
        )
        self.assertEqual(proposal["platforms"], ["linux/amd64", "linux/arm64"])
        self.assertIsNone(proposal["remote_index_digest"])
        self.assertIsNone(proposal["approved_compose_reference"])
        self.assertEqual(proposal["status"], "NOT_AUTHORIZED_NOT_PUBLISHED")
        self.assertTrue(proposal["requires_separate_user_approval"])
        self.assertTrue(proposal["requires_release_security_review"])
        self.assertFalse(proposal["floating_tags_allowed"])

    def test_revision_and_immutable_digest_reference_are_strict(self):
        self.assertEqual(validate_revision(REVISION), REVISION)
        for rev in ("e" * 7, "E" * 40, " " + REVISION):
            with self.assertRaisesRegex(ValueError, "invalid_source_revision"):
                validate_revision(rev)
        good = IMAGE_REPOSITORY + "@sha256:" + "a" * 64
        self.assertEqual(validate_immutable_reference(good), good)
        for value in (
            IMAGE_REPOSITORY + ":latest",
            IMAGE_REPOSITORY + ":v1.1.0",
            IMAGE_REPOSITORY + "@sha256:REPLACE_WITH_APPROVED_DIGEST",
            IMAGE_REPOSITORY + "@sha256:" + "a" * 63,
            "ghcr.io/another/seekpulse@sha256:" + "a" * 64,
            "https://" + good, good + "\n",
        ):
            with self.subTest(value=repr(value)):
                with self.assertRaisesRegex(
                    ValueError, "invalid_immutable_image_reference"
                ):
                    validate_immutable_reference(value)

    def test_readonly_ci_has_no_remote_publish_capability(self):
        workflow = (
            ROOT / ".github/workflows/s7-v11-release-readiness.yml"
        ).read_text(encoding="utf-8")
        active = "\n".join(
            line for line in workflow.splitlines()
            if not line.lstrip().startswith("#")
        )
        for disallowed in (
            "packages: write", "docker/login-action", "docker push",
            "gh release", "build-push-action", "--push", "type=registry",
            "cache-to: type=registry", "secrets.",
        ):
            self.assertNotIn(disallowed, active)
        self.assertIn("contents: read", active)
        self.assertIn("type=oci,dest=", active)
        self.assertIn("--platform linux/amd64,linux/arm64", active)
        self.assertIn("--network none", active)

    def test_runtime_and_compose_security_still_opt_in(self):
        dockerfile = (ROOT / "Dockerfile.v11").read_text(encoding="utf-8")
        compose = (ROOT / "compose.v11.yaml").read_text(encoding="utf-8")
        for required in (
            "ARG SEEKPULSE_BUILD_VERSION=0.0.0-ci",
            "ARG SEEKPULSE_BUILD_REVISION=unknown",
            "org.opencontainers.image.source=",
            "org.opencontainers.image.version=",
            "org.opencontainers.image.revision=",
            "org.opencontainers.image.licenses=",
            "USER 10001:10001",
            'ENTRYPOINT ["python", "-m", "app.v11_main"]',
        ):
            self.assertIn(required, dockerfile)
        self.assertIn("network_mode: host", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn('restart: "no"', compose)
        self.assertIn("SEEKPULSE_IMAGE:?", compose)
        self.assertIn("create_host_path: false", compose)
        self.assertNotIn("docker.sock", compose)
        self.assertNotRegex(compose, r"(?m)^\s*ports:")


class LocalOCIArchive(unittest.TestCase):
    def _inspect(self, *, edit_config=None, edit_index=None, corrupt=False):
        with TemporaryDirectory() as td:
            filename = Path(td) / "test.oci.tar"
            _make_oci(
                filename, edit_config=edit_config,
                edit_index=edit_index, corrupt_blob=corrupt,
            )
            return inspect_archive(
                filename, revision=REVISION, version=VERSION
            )

    def test_local_index_verifies_two_platforms_but_no_remote_digest(self):
        result = self._inspect()
        self.assertEqual(result["platforms"], ["linux/amd64", "linux/arm64"])
        self.assertEqual(result["source_revision"], REVISION)
        self.assertEqual(result["version"], VERSION)
        self.assertGreater(result["validated_blobs"], 3)
        self.assertIsNone(result["remote_ghcr_digest"])
        self.assertFalse(result["release_authorized"])

    def test_reject_missing_or_duplicate_platform(self):
        with self.assertRaisesRegex(OCIValidationError, "exactly_two"):
            self._inspect(edit_index=lambda i: i["manifests"].pop())

        def duplicate(index):
            index["manifests"][1]["platform"]["architecture"] = "amd64"

        with self.assertRaisesRegex(OCIValidationError, "duplicate_platform"):
            self._inspect(edit_index=duplicate)

    def test_reject_mismatched_revision_and_arch(self):
        def wrong_revision(config):
            config["config"]["Labels"]["org.opencontainers.image.revision"] = (
                "f" * 40
            )
        with self.assertRaisesRegex(OCIValidationError, "oci_bad_label"):
            self._inspect(edit_config=wrong_revision)
        with self.assertRaisesRegex(OCIValidationError, "oci_config_platform"):
            self._inspect(edit_config=lambda cfg: cfg.update(architecture="arm64"))

    def test_reject_root_unexpected_entrypoint_or_baked_credential(self):
        modifications = (
            (lambda c: c["config"].update(User="0:0"), "nonroot"),
            (lambda c: c["config"].update(Entrypoint=["sh"]), "entrypoint"),
            (lambda c: c["config"].update(Env=["BOT_TOKEN=private"]),
             "baked_runtime_secret"),
            (lambda c: c["config"].update(
                Env=["SEEKPULSE_PUSH_BARK_PRIMARY=private"]
            ), "baked_runtime_secret"),
        )
        for modify, marker in modifications:
            with self.subTest(marker=marker):
                with self.assertRaisesRegex(OCIValidationError, marker):
                    self._inspect(edit_config=modify)

    def test_reject_corrupted_sha256_blob(self):
        with self.assertRaisesRegex(OCIValidationError, "checksum_mismatch"):
            self._inspect(corrupt=True)

    def test_reject_short_expected_commit(self):
        with TemporaryDirectory() as td:
            f = Path(td) / "test.tar"
            _make_oci(f)
            with self.assertRaisesRegex(OCIValidationError, "expected_revision"):
                inspect_archive(f, revision="deadbeef", version=VERSION)


if __name__ == "__main__":
    unittest.main()
