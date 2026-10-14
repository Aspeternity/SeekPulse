"""Read-only OCI archive integrity/config checker for Docker-03.

No docker registry, network requests, publishable digests or execution.
The checks validate CI-generated artifacts, not real device compatibility
and not a vulnerability-database or malware scan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path
from typing import Any, BinaryIO

SOURCE = "https://github.com/Aspeternity/SeekPulse"
PLATFORMS = frozenset({"linux/amd64", "linux/arm64"})
_SHA = re.compile(r"^sha256:([0-9a-f]{64})$")
_REV = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
_IMAGE_MANIFEST_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
_IMAGE_CONFIG_TYPES = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}
_LAYER_TYPES = {
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.oci.image.layer.v1.tar+zstd",
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
}
_FORBIDDEN_ENV = {
    "BOT_TOKEN", "SEEKPULSE_TG_API_HASH", "SEEKPULSE_TG_API_ID",
    "SEEKPULSE_TG_SESSION", "SEEKPULSE_WEB_PASSWORD_HASH",
    "SEEKPULSE_ADMIN_TG_USER_ID", "ALLOWED_USER_IDS",
    "SEEKPULSE_FRESH_INIT_CONFIRM",
}


class OCIValidationError(ValueError):
    """A malformed or unsafe local image archive."""


def _need(ok: bool, error: str) -> None:
    if not ok:
        raise OCIValidationError(error)


def _read_json(stream: BinaryIO, *, limit: int = 4 * 1024 * 1024) -> dict[str, Any]:
    raw = stream.read(limit + 1)
    _need(len(raw) <= limit, "oci_json_too_large")
    try:
        obj = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OCIValidationError("oci_invalid_json") from exc
    _need(isinstance(obj, dict), "oci_json_not_object")
    return obj


def _blob(
    archive: tarfile.TarFile,
    descriptor: dict[str, Any],
    *,
    maximum: int | None = None,
    read_bytes: bool = True,
) -> bytes:
    digest = descriptor.get("digest")
    _need(isinstance(digest, str), "oci_invalid_blob_digest")
    match = _SHA.fullmatch(digest)
    _need(match is not None, "oci_invalid_blob_digest")
    size = descriptor.get("size")
    _need(type(size) is int and size > 0, "oci_invalid_blob_size")
    if maximum is not None:
        _need(size <= maximum, "oci_blob_too_large")
    name = f"blobs/sha256/{match.group(1)}"
    try:
        info = archive.getmember(name)
        _need(info.isfile() and info.size == size, "oci_blob_size_mismatch")
        reader = archive.extractfile(info)
        _need(reader is not None, "oci_blob_missing")
        with reader:
            check = hashlib.sha256()
            output = bytearray() if read_bytes else None
            count = 0
            while True:
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                check.update(chunk)
                if output is not None:
                    output.extend(chunk)
    except (KeyError, OSError, tarfile.TarError) as exc:
        raise OCIValidationError("oci_blob_missing") from exc
    _need(count == size, "oci_blob_size_mismatch")
    _need(check.hexdigest() == match.group(1), "oci_blob_checksum_mismatch")
    return bytes(output) if output is not None else b""


def _json_blob(
    archive: tarfile.TarFile, descriptor: dict[str, Any]
) -> dict[str, Any]:
    raw = _blob(archive, descriptor, maximum=4 * 1024 * 1024)
    try:
        obj = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OCIValidationError("oci_invalid_json_blob") from exc
    _need(isinstance(obj, dict), "oci_json_not_object")
    return obj


def _check_config(
    config: dict[str, Any], platform: str, revision: str, version: str
) -> None:
    os_name, architecture = platform.split("/")
    _need(
        config.get("os") == os_name
        and config.get("architecture") == architecture,
        "oci_config_platform_mismatch",
    )
    runtime = config.get("config")
    _need(isinstance(runtime, dict), "oci_missing_runtime_config")
    _need(runtime.get("User") == "10001:10001", "oci_must_run_nonroot")
    _need(
        runtime.get("Entrypoint") == ["python", "-m", "app.v11_main"],
        "oci_unexpected_entrypoint",
    )
    _need(runtime.get("Cmd") == ["--run"], "oci_unexpected_command")
    _need(runtime.get("WorkingDir") == "/app", "oci_unexpected_workdir")
    env = runtime.get("Env", [])
    _need(
        isinstance(env, list) and all(isinstance(x, str) and "=" in x for x in env),
        "oci_invalid_env",
    )
    for entry in env:
        key = entry.split("=", 1)[0]
        _need(
            key not in _FORBIDDEN_ENV and not key.startswith("SEEKPULSE_PUSH_"),
            "oci_baked_runtime_secret",
        )
    labels = runtime.get("Labels")
    _need(isinstance(labels, dict), "oci_missing_labels")
    required = {
        "org.opencontainers.image.title": "SeekPulse",
        "org.opencontainers.image.source": SOURCE,
        "org.opencontainers.image.revision": revision,
        "org.opencontainers.image.version": version,
        "org.opencontainers.image.licenses": "MIT",
    }
    for key, expected in required.items():
        _need(labels.get(key) == expected, "oci_bad_label:" + key)
    rootfs = config.get("rootfs")
    _need(
        isinstance(rootfs, dict) and rootfs.get("type") == "layers"
        and isinstance(rootfs.get("diff_ids"), list)
        and len(rootfs["diff_ids"]) > 0,
        "oci_missing_rootfs",
    )
    for diff in rootfs["diff_ids"]:
        _need(isinstance(diff, str) and _SHA.fullmatch(diff) is not None,
              "oci_invalid_rootfs_digest")


def inspect_archive(
    path: str | Path, *, revision: str, version: str
) -> dict[str, Any]:
    """Validate TWO distinct platform manifests; never expose a remote digest."""
    _need(bool(_REV.fullmatch(revision)), "oci_invalid_expected_revision")
    _need(bool(re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}", version)),
          "oci_invalid_expected_version")
    platform_set: set[str] = set()
    with tarfile.open(path, "r:*") as archive:
        try:
            index_file = archive.extractfile("index.json")
        except (KeyError, tarfile.TarError) as exc:
            raise OCIValidationError("oci_missing_index") from exc
        _need(index_file is not None, "oci_missing_index")
        with index_file:
            index = _read_json(index_file)
        _need(index.get("schemaVersion") == 2, "oci_invalid_index_version")
        manifests = index.get("manifests")
        _need(isinstance(manifests, list), "oci_invalid_layout_index")
        # The OCI exporter may add one outer image-layout index descriptor
        # pointing to the actual multi-platform image index (rather than
        # listing platform manifests directly). Follow exactly one signed
        # descriptor, verify its SHA and then enforce the SAME 2-platform rule.
        verified_blobs: set[str] = set()
        if (len(manifests) == 1 and isinstance(manifests[0], dict)
                and manifests[0].get("mediaType") in _IMAGE_INDEX_TYPES):
            wrapper = manifests[0]
            embedded = _json_blob(archive, wrapper)
            verified_blobs.add(wrapper["digest"])
            _need(embedded.get("schemaVersion") == 2,
                  "oci_invalid_nested_index_version")
            manifests = embedded.get("manifests")
        _need(isinstance(manifests, list) and len(manifests) == 2,
              "oci_expected_exactly_two_platforms")

        for item in manifests:
            _need(isinstance(item, dict), "oci_invalid_manifest_descriptor")
            _need(item.get("mediaType") in _IMAGE_MANIFEST_TYPES,
                  "oci_wrong_manifest_media_type")
            plat = item.get("platform", {})
            _need(isinstance(plat, dict), "oci_invalid_platform")
            platform = f"{plat.get('os')}/{plat.get('architecture')}"
            _need(platform in PLATFORMS and platform not in platform_set,
                  "oci_wrong_or_duplicate_platform")
            platform_set.add(platform)
            manifest = _json_blob(archive, item)
            verified_blobs.add(item["digest"])
            _need(manifest.get("schemaVersion") == 2, "oci_invalid_manifest")
            descriptor = manifest.get("config")
            _need(isinstance(descriptor, dict) and
                  descriptor.get("mediaType") in _IMAGE_CONFIG_TYPES,
                  "oci_invalid_config_descriptor")
            config = _json_blob(archive, descriptor)
            verified_blobs.add(descriptor["digest"])
            _check_config(config, platform, revision, version)
            layers = manifest.get("layers")
            _need(isinstance(layers, list) and len(layers) > 0,
                  "oci_missing_layers")
            for layer in layers:
                _need(isinstance(layer, dict) and
                      layer.get("mediaType") in _LAYER_TYPES,
                      "oci_invalid_layer")
                if layer["digest"] not in verified_blobs:
                    _blob(archive, layer, read_bytes=False)
                    verified_blobs.add(layer["digest"])
    _need(platform_set == PLATFORMS, "oci_missing_platform")
    return {
        "status": "LOCAL_OCI_VERIFIED_NOT_PUBLISHED",
        "version": version,
        "source_revision": revision,
        "platforms": sorted(platform_set),
        "validated_blobs": len(verified_blobs),
        "remote_ghcr_digest": None,
        "release_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect local two-architecture OCI archive; never publish"
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    try:
        report = inspect_archive(
            args.archive, revision=args.revision, version=args.version
        )
    except (OCIValidationError, OSError, tarfile.TarError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
