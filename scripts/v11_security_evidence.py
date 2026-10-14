"""Docker-04: validate public Trivy CVE + CycloneDX evidence, never publish.

A valid scan proves only that a scanner executed against a local image and a
recent public vulnerability DB. It NEVER grants a release or registry digest.
No network operations, credential handling, or production actions.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

_PLATFORMS = {"linux/amd64", "linux/arm64"}
_SEVERITIES = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
_MAX_DB_AGE = timedelta(hours=48)
_MAX_DB_DEADLINE_SLACK = timedelta(hours=24)
_MAX_CLOCK_SKEW = timedelta(minutes=15)


class SecurityEvidenceError(ValueError):
    """Invalid, stale, missing or mismatched local evidence."""


def _require(test: bool, reason: str) -> None:
    if not test:
        raise SecurityEvidenceError(reason)


def _timestamp(value: Any, *, field: str) -> datetime:
    _require(isinstance(value, str) and value, "invalid_time:" + field)
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SecurityEvidenceError("invalid_time:" + field) from None
    _require(date.tzinfo is not None, "naive_time:" + field)
    return date.astimezone(timezone.utc)


def _db_freshness(metadata: dict[str, Any], now: datetime) -> dict[str, str]:
    _require(isinstance(metadata, dict), "missing_vulnerability_db_metadata")
    _require(type(metadata.get("Version")) is int, "invalid_vulnerability_db_version")
    updated = _timestamp(metadata.get("UpdatedAt"), field="db_updated")
    downloaded = _timestamp(metadata.get("DownloadedAt"), field="db_downloaded")
    next_update = _timestamp(metadata.get("NextUpdate"), field="db_next_update")
    for date in (updated, downloaded, next_update):
        _require(date <= now + _MAX_CLOCK_SKEW, "db_clock_in_future")
    _require(
        now - updated <= _MAX_DB_AGE and now - downloaded <= _MAX_DB_AGE,
        "vulnerability_db_outdated",
    )
    _require(next_update + _MAX_DB_DEADLINE_SLACK >= now,
             "vulnerability_db_past_update_deadline")
    _require(downloaded >= updated - timedelta(days=1),
             "vulnerability_db_inconsistent_timestamps")
    return {
        "updated_at": updated.isoformat(),
        "downloaded_at": downloaded.isoformat(),
        "next_update": next_update.isoformat(),
    }


def verify_security_evidence(
    *,
    scan: dict[str, Any],
    sbom: dict[str, Any],
    db_metadata: dict[str, Any],
    image_inspect: dict[str, Any],
    platform: str,
    image_tag: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail closed on missing evidence; return release BLOCKED on real CVEs.

    Scanner execution succeeding and publication being approved are distinct.
    Never use a local OCI digest as an official GHCR remote registry digest.
    """
    _require(platform in _PLATFORMS, "unexpected_image_platform")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    freshness = _db_freshness(db_metadata, current)

    _require(isinstance(image_inspect, dict), "missing_local_image_inspect")
    arch = platform.split("/")[1]
    _require(
        image_inspect.get("Os") == "linux"
        and image_inspect.get("Architecture") == arch,
        "local_image_architecture_mismatch",
    )
    image_id = image_inspect.get("Id")
    _require(isinstance(image_id, str) and image_id.startswith("sha256:"),
             "invalid_local_image_id")
    runtime = image_inspect.get("Config")
    _require(isinstance(runtime, dict), "missing_local_image_config")
    _require(runtime.get("User") == "10001:10001", "runtime_not_nonroot")
    _require(runtime.get("Entrypoint") == ["python", "-m", "app.v11_main"],
             "runtime_unexpected_entrypoint")
    _require(runtime.get("Cmd") == ["--run"], "runtime_unexpected_command")
    _require(image_inspect.get("RepoDigests") in ([], None),
             "unexpected_published_image_digest")

    _require(isinstance(sbom, dict) and sbom.get("bomFormat") == "CycloneDX",
             "invalid_cyclonedx_bom")
    _require(isinstance(sbom.get("specVersion"), str), "missing_bom_spec_version")
    meta = sbom.get("metadata")
    _require(isinstance(meta, dict), "missing_bom_metadata")
    generated = _timestamp(meta.get("timestamp"), field="sbom_generated")
    _require(abs(current - generated) <= timedelta(hours=2), "stale_sbom")
    components = sbom.get("components")
    _require(isinstance(components, list) and len(components) > 0,
             "missing_bom_components")
    os_packages = 0
    python_packages = 0
    for item in components:
        _require(isinstance(item, dict), "invalid_bom_component")
        purl = item.get("purl", "")
        _require(isinstance(purl, str), "invalid_bom_purl")
        if purl.startswith("pkg:deb/"):
            os_packages += 1
        if purl.startswith("pkg:pypi/"):
            python_packages += 1
    _require(os_packages >= 10, "missing_debian_os_inventory")
    _require(python_packages >= 5, "missing_python_dependency_inventory")

    _require(isinstance(scan, dict), "missing_trivy_json_scan")
    _require(type(scan.get("SchemaVersion")) is int, "invalid_trivy_scan_schema")
    _require(scan.get("ArtifactType") == "container_image",
             "scanner_not_container_image")
    _require(scan.get("ArtifactName") == image_tag, "scanner_wrong_local_image")
    metadata = scan.get("Metadata")
    _require(isinstance(metadata, dict), "scanner_missing_image_metadata")
    os_record = metadata.get("OS")
    _require(isinstance(os_record, dict) and os_record.get("Family") == "debian",
             "scanner_missing_debian_os")
    report_image_id = metadata.get("ImageID")
    _require(isinstance(report_image_id, str) and report_image_id == image_id,
             "scanner_local_image_id_mismatch")
    results = scan.get("Results")
    _require(isinstance(results, list) and len(results) > 0,
             "missing_vulnerability_scan_targets")
    classes: set[str] = set()
    severity_counts: Counter[str] = Counter()
    blocker_ids: set[str] = set()
    fixed_blocker_ids: set[str] = set()
    for result in results:
        _require(isinstance(result, dict), "invalid_scan_result")
        classification = result.get("Class")
        _require(classification in {"os-pkgs", "lang-pkgs"},
                 "unsupported_scan_result_class")
        classes.add(classification)
        issues = result.get("Vulnerabilities") or []
        _require(isinstance(issues, list), "invalid_vulnerability_list")
        for vuln in issues:
            _require(isinstance(vuln, dict), "invalid_vulnerability_entry")
            level = vuln.get("Severity", "UNKNOWN")
            _require(level in _SEVERITIES, "unknown_vulnerability_severity")
            vid = vuln.get("VulnerabilityID")
            _require(isinstance(vid, str) and vid, "invalid_vulnerability_identifier")
            severity_counts[level] += 1
            if level in {"HIGH", "CRITICAL"}:
                blocker_ids.add(vid)
                if vuln.get("FixedVersion"):
                    fixed_blocker_ids.add(vid)
    _require(classes == {"os-pkgs", "lang-pkgs"},
             "os_or_python_vulnerability_scan_missing")
    gate = (
        "BLOCKED_HIGH_OR_CRITICAL"
        if blocker_ids else
        "REVIEW_REQUIRED_NONBLOCKING" if sum(severity_counts.values()) else
        "NO_KNOWN_FINDINGS_AT_SCAN_TIME"
    )
    return {
        "evidence": "VALID_LOCAL_SCAN_NOT_PUBLISHED",
        "platform": platform,
        "image": image_tag,
        "scanner_db": freshness,
        "inventory": {"debian_packages": os_packages, "pypi_packages": python_packages},
        "findings": {
            "by_severity": {name: severity_counts[name]
                            for name in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")},
            "high_critical_unique_ids": len(blocker_ids),
            "high_critical_with_fixed_version_unique_ids": len(fixed_blocker_ids),
            "high_critical_sample_ids": sorted(blocker_ids)[:20],
        },
        "vulnerability_gate": gate,
        "ghcr_image_status": "NOT_PUBLISHED",
        "remote_index_digest": None,
        "release_authorized": False,
        "release_ready": False,
        "requires_separate_user_approval": True,
    }


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        if not raw or len(raw) > 64 * 1024 * 1024:
            raise SecurityEvidenceError("invalid_scan_evidence_size")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        raise SecurityEvidenceError("invalid_scan_evidence_json") from None
    _require(isinstance(parsed, dict), "scan_evidence_not_object")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate LOCAL scan / SBOM; no GHCR access")
    parser.add_argument("--scan", required=True, type=Path)
    parser.add_argument("--sbom", required=True, type=Path)
    parser.add_argument("--db-metadata", required=True, type=Path)
    parser.add_argument("--inspect", required=True, type=Path)
    parser.add_argument("--platform", required=True, choices=sorted(_PLATFORMS))
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        verdict = verify_security_evidence(
            scan=_load(args.scan),
            sbom=_load(args.sbom),
            db_metadata=_load(args.db_metadata),
            image_inspect=_load(args.inspect),
            platform=args.platform,
            image_tag=args.image,
        )
    except SecurityEvidenceError as exc:
        parser.error(str(exc))
    args.output.write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"LOCAL_SECURITY_EVIDENCE=VALID platform={args.platform} "
        f"vulnerability_gate={verdict['vulnerability_gate']} "
        "GHCR_STATUS=NOT_PUBLISHED RELEASE_AUTHORIZED=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
