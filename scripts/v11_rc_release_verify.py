"""One-time V1.1 RC GHCR release verification.

Unlike the existing local-only evidence reviewers, this checks actual pulled
GHCR platform bytes. It never pushes, signs, changes a tag, or approves release.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

from scripts.v11_pre_release_review import review_pre_release
from scripts.v11_release_policy import validate_revision, validate_version
from scripts.v11_security_evidence import (
    _db_freshness, verify_security_evidence,
)

IMAGE = "ghcr.io/aspeternity/seekpulse"
SOURCE = "https://github.com/Aspeternity/SeekPulse"
ARCHES = ("amd64", "arm64")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
MANIFEST_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
BLOCKED_ENV = {
    "BOT_TOKEN", "ALLOWED_USER_IDS", "GITHUB_TOKEN", "GH_TOKEN",
    "SEEKPULSE_TG_API_HASH", "SEEKPULSE_TG_SESSION",
    "SEEKPULSE_WEB_PASSWORD_HASH", "SEEKPULSE_ADMIN_TG_USER_ID",
}


class RCVerificationError(ValueError):
    """A release prerequisite cannot be verified, so publication must stop."""


def need(ok: bool, reason: str) -> None:
    if not ok:
        raise RCVerificationError(reason)


def identity(inspect: dict[str, Any], *, arch: str, revision: str,
             version: str) -> None:
    validate_revision(revision)
    validate_version(version)
    need(arch in ARCHES, "unexpected_platform")
    need(isinstance(inspect, dict), "invalid_image_inspect")
    need(inspect.get("Os") == "linux" and inspect.get("Architecture") == arch,
         "wrong_runtime_platform")
    config = inspect.get("Config")
    need(isinstance(config, dict), "missing_image_config")
    need(config.get("User") == "10001:10001"
         and config.get("Entrypoint") == ["python", "-m", "app.v11_main"]
         and config.get("Cmd") == ["--run"], "runtime_contract_changed")
    labels = config.get("Labels")
    need(isinstance(labels, dict), "missing_oci_labels")
    expected = {
        "org.opencontainers.image.title": "SeekPulse",
        "org.opencontainers.image.source": SOURCE,
        "org.opencontainers.image.revision": revision,
        "org.opencontainers.image.version": version,
        "org.opencontainers.image.licenses": "MIT",
    }
    need(all(labels.get(k) == v for k, v in expected.items()),
         "wrong_release_source_or_version_label")
    environ = config.get("Env")
    need(isinstance(environ, list) and all(isinstance(s, str) and "=" in s
                                            for s in environ), "bad_baked_env")
    keys = {s.split("=", 1)[0] for s in environ}
    need(not (keys & BLOCKED_ENV) and not any(
        key.startswith(("SEEKPULSE_PUSH_", "GHCR_")) for key in keys),
        "secret_baked_into_image")


def verify_local(*, scan: dict[str, Any], sbom: dict[str, Any],
                 db: dict[str, Any], inspect: dict[str, Any],
                 arch: str, revision: str, version: str,
                 now: datetime | None = None) -> dict[str, Any]:
    identity(inspect, arch=arch, revision=revision, version=version)
    local_name = f"seekpulse-prepublish-local:{arch}"
    actual = verify_security_evidence(
        scan=scan, sbom=sbom, db_metadata=db, image_inspect=inspect,
        platform=f"linux/{arch}", image_tag=local_name, os_family="alpine",
        now=now,
    )
    review = review_pre_release(
        scan=scan, validated=actual, revision=revision,
        platform=f"linux/{arch}", image=local_name, version=version, now=now,
    )
    need(actual["vulnerability_gate"] == "NO_KNOWN_FINDINGS_AT_SCAN_TIME",
         "local_vulnerability_findings")
    need(all(type(review["affected_package_vulnerability_records"].get(n)) is int
             and review["affected_package_vulnerability_records"][n] == 0
             for n in LEVELS), "local_nonzero_cves")
    need(review["status"] == "MANUAL_RELEASE_SECURITY_REVIEW_REQUIRED"
         and review["manual_findings"] == [], "local_security_review_failed")
    return {"arch": arch, "source_sha": revision, "version": version,
            "image_id": inspect["Id"], "counts": review["affected_package_vulnerability_records"],
            "inventory": review["package_inventory"],
            "scanner_db": review["scanner_db"], "stage": "LOCAL_SCANNED_BEFORE_PUSH"}


def verify_index(index: dict[str, Any], *, amd64_digest: str,
                 arm64_digest: str) -> dict[str, str]:
    need(isinstance(index, dict) and index.get("schemaVersion") == 2,
         "invalid_registry_index")
    need(index.get("mediaType") in INDEX_TYPES, "not_an_oci_multiarch_index")
    expected = {"linux/amd64": amd64_digest, "linux/arm64": arm64_digest}
    need(all(isinstance(x, str) and DIGEST.fullmatch(x)
             for x in expected.values()), "bad_platform_manifest_digest")
    need(amd64_digest != arm64_digest, "same_digest_both_platforms")
    manifests = index.get("manifests")
    need(isinstance(manifests, list) and len(manifests) == 2,
         "index_must_have_exactly_two_platforms")
    seen = {}
    for entry in manifests:
        need(isinstance(entry, dict)
             and entry.get("mediaType") in MANIFEST_TYPES
             and isinstance(entry.get("platform"), dict),
             "unexpected_platform_descriptor")
        plat = entry["platform"]
        platform = f"{plat.get('os')}/{plat.get('architecture')}"
        need(platform in expected and platform not in seen,
             "extra_duplicate_or_unknown_platform")
        need(entry.get("digest") == expected[platform],
             "index_manifest_does_not_match_pushed_bytes")
        need(type(entry.get("size")) is int and entry["size"] > 100,
             "missing_manifest_size")
        seen[platform] = entry["digest"]
    need(seen == expected, "missing_platform_descriptor")
    return seen


def verify_remote(*, scan: dict[str, Any], sbom: dict[str, Any],
                  db: dict[str, Any], inspect: dict[str, Any],
                  arch: str, revision: str, version: str,
                  index_digest: str, platform_digest: str,
                  now: datetime | None = None) -> dict[str, Any]:
    identity(inspect, arch=arch, revision=revision, version=version)
    need(bool(DIGEST.fullmatch(index_digest))
         and bool(DIGEST.fullmatch(platform_digest)),
         "invalid_remote_digest")
    digests = inspect.get("RepoDigests")
    need(isinstance(digests, list) and any(
        isinstance(x, str) and x.startswith(IMAGE + "@")
        and x[len(IMAGE) + 1:] in {index_digest, platform_digest}
        for x in digests), "remote_registry_digest_not_proven")
    need(isinstance(scan, dict) and scan.get("ArtifactType") == "container_image"
         and isinstance(scan.get("Metadata"), dict)
         and scan["Metadata"].get("ImageID") == inspect.get("Id")
         and isinstance(scan["Metadata"].get("OS"), dict)
         and scan["Metadata"]["OS"].get("Family") == "alpine",
         "remote_trivy_image_not_pulled_bytes")
    need(scan.get("ArtifactName") == f"seekpulse-remote-verified:{arch}",
         "wrong_remote_scan_tag")
    sections = scan.get("Results")
    need(isinstance(sections, list) and bool(sections),
         "missing_remote_scanner_results")
    covered: set[str] = set()
    for section in sections:
        need(isinstance(section, dict), "invalid_remote_scan_section")
        kind = section.get("Class")
        need(kind in {"os-pkgs", "lang-pkgs"}, "unknown_remote_scan_class")
        if kind == "os-pkgs":
            need(section.get("Type") == "alpine",
                 "wrong_remote_os_package_family")
        covered.add(kind)
        vulnerabilities = section.get("Vulnerabilities") or []
        need(isinstance(vulnerabilities, list) and not vulnerabilities,
             "remote_vulnerability_record_detected")
    need(covered == {"os-pkgs", "lang-pkgs"},
         "remote_os_or_pypi_coverage_missing")
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    freshness = _db_freshness(db, clock)
    need(isinstance(sbom, dict) and sbom.get("bomFormat") == "CycloneDX"
         and isinstance(sbom.get("specVersion"), str),
         "missing_remote_cyclonedx")
    metadata = sbom.get("metadata")
    need(isinstance(metadata, dict) and isinstance(metadata.get("timestamp"), str),
         "missing_sbom_time")
    try:
        generated = datetime.fromisoformat(
            metadata["timestamp"].replace("Z", "+00:00"))
    except ValueError:
        raise RCVerificationError("invalid_sbom_time") from None
    need(generated.tzinfo is not None
         and abs(clock - generated.astimezone(timezone.utc)) <= timedelta(hours=2),
         "remote_sbom_is_stale")
    components = sbom.get("components")
    need(isinstance(components, list), "missing_sbom_components")
    purls = [x.get("purl", "") for x in components if isinstance(x, dict)]
    need(all(isinstance(x, str) for x in purls)
         and sum(x.startswith("pkg:apk/") for x in purls) >= 10
         and sum(x.startswith("pkg:pypi/") for x in purls) >= 5
         and not any(x.startswith("pkg:deb/") for x in purls),
         "incomplete_remote_sbom_package_inventory")
    return {
        "stage": "REAL_REGISTRY_PULL_SCANNED_ZERO_CVES",
        "platform": f"linux/{arch}", "source_sha": revision, "version": version,
        "index_digest": index_digest, "platform_digest": platform_digest,
        "image_id": inspect["Id"], "scanner_db": freshness,
        "inventory": {
            "alpine": sum(x.startswith("pkg:apk/") for x in purls),
            "pypi": sum(x.startswith("pkg:pypi/") for x in purls),
        },
        "counts": {s: 0 for s in LEVELS},
    }


def load(path: str) -> dict[str, Any]:
    try:
        data = Path(path).read_bytes()
        need(bool(data) and len(data) < 64 * 1024 * 1024, "bad_evidence_size")
        value = json.loads(data)
    except (OSError, ValueError, UnicodeError) as exc:
        raise RCVerificationError("bad_evidence_json") from exc
    need(isinstance(value, dict), "evidence_not_json_object")
    return value


def main() -> int:
    p = argparse.ArgumentParser(description="Read-only fail-closed RC image evidence")
    sub = p.add_subparsers(dest="mode", required=True)
    for mode in ("local", "index", "remote"):
        q = sub.add_parser(mode)
        if mode == "index":
            q.add_argument("--index", required=True)
            q.add_argument("--amd64-digest", required=True)
            q.add_argument("--arm64-digest", required=True)
        else:
            for arg in ("scan", "sbom", "db", "inspect", "arch", "revision", "version"):
                q.add_argument("--" + arg, required=True)
            if mode == "remote":
                q.add_argument("--index-digest", required=True)
                q.add_argument("--platform-digest", required=True)
    a = vars(p.parse_args())
    mode = a.pop("mode")
    try:
        if mode == "index":
            result = verify_index(load(a.pop("index")), **a)
        else:
            args = {k: load(a.pop(k)) for k in ("scan", "sbom", "db", "inspect")}
            result = (verify_local if mode == "local" else verify_remote)(
                **args, **a)
    except (RCVerificationError, ValueError) as exc:
        p.error(str(exc))
    print("RC_EVIDENCE=" + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
