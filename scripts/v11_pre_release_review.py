"""Docker-09: review LOCAL Trivy findings before any V1.1 GHCR release.

Requires a validated full-image scan/SBOM report from the same ephemeral run.
Reports PUBLIC CVE/package metadata only, never sends or signs anything.
NO result from this module grants release, registry publication or deployment.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

from scripts.v11_release_policy import draft_release_plan, validate_revision

CLASSES = ("os-pkgs", "lang-pkgs")
LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
BASE = (
    "python:3.11-alpine3.24@sha256:"
    "d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929"
)
PLATFORMS = {"linux/amd64", "linux/arm64"}
_CVE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{2,120}$")


class PreReleaseReviewError(ValueError):
    """Incomplete, inconsistent or unsafe public security evidence."""


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise PreReleaseReviewError(message)


def _public(value: Any, field: str, *, empty: bool = False) -> str:
    _need(isinstance(value, str) and len(value) <= 180,
          "invalid_public_" + field)
    _need(empty or bool(value), "missing_public_" + field)
    _need(not any(ord(char) < 32 or ord(char) == 127 for char in value),
          "unsafe_public_" + field)
    return value


def _fresh(validated: dict[str, Any], now: datetime) -> dict[str, str]:
    data = validated.get("scanner_db")
    _need(isinstance(data, dict), "missing_validated_scanner_db")
    for field in ("updated_at", "downloaded_at"):
        raw = _public(data.get(field), field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise PreReleaseReviewError("invalid_validated_db_time") from None
        _need(parsed.tzinfo is not None, "unaware_validated_db_time")
        age = now - parsed.astimezone(timezone.utc)
        _need(timedelta() <= age <= timedelta(hours=48), "stale_or_future_scanner_db")
    return {key: data[key] for key in ("updated_at", "downloaded_at")}


def review_pre_release(
    *, scan: dict[str, Any], validated: dict[str, Any],
    revision: str, platform: str, image: str, version: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Cross-check real scan counts with the prior fail-closed SBOM validator.

    High/Critical and UNKNOWN are BLOCKED in report and CI; Medium/Low remain
    visible for human adjudication and NEVER auto-authorize GHCR publishing.
    """
    validate_revision(revision)
    _need(platform in PLATFORMS, "invalid_expected_platform")
    image = _public(image, "image")
    _need(image == f"seekpulse-prepublish-local:{platform.split('/')[1]}",
          "unexpected_local_image_tag")
    plan = draft_release_plan(version, revision)
    _need(plan["status"] == "NOT_AUTHORIZED_NOT_PUBLISHED"
          and plan["remote_index_digest"] is None
          and plan["approved_compose_reference"] is None,
          "unapproved_release_policy")

    _need(isinstance(scan, dict), "invalid_trivy_scan")
    _need(scan.get("ArtifactType") == "container_image"
          and scan.get("ArtifactName") == image
          and type(scan.get("SchemaVersion")) is int,
          "wrong_scanner_artifact")
    metadata = scan.get("Metadata")
    _need(isinstance(metadata, dict), "scanner_missing_metadata")
    os_record = metadata.get("OS")
    _need(isinstance(os_record, dict) and os_record.get("Family") == "alpine",
          "scanner_not_alpine")
    _need(isinstance(validated, dict)
          and validated.get("evidence") == "VALID_LOCAL_SCAN_NOT_PUBLISHED"
          and validated.get("image") == image
          and validated.get("platform") == platform
          and validated.get("os_family") == "alpine",
          "security_report_identity_mismatch")
    _need(validated.get("ghcr_image_status") == "NOT_PUBLISHED"
          and validated.get("release_ready") is False
          and validated.get("release_authorized") is False
          and validated.get("remote_index_digest") is None
          and validated.get("requires_separate_user_approval") is True,
          "security_report_claims_release")
    inventory = validated.get("inventory")
    _need(isinstance(inventory, dict)
          and type(inventory.get("alpine_packages")) is int
          and inventory["alpine_packages"] >= 10
          and type(inventory.get("pypi_packages")) is int
          and inventory["pypi_packages"] >= 5,
          "incomplete_validated_inventory")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    db = _fresh(validated, current)
    findings = validated.get("findings")
    _need(isinstance(findings, dict), "missing_validated_findings")
    by_class = findings.get("by_package_class")
    by_severity = findings.get("by_severity")
    _need(isinstance(by_class, dict) and isinstance(by_severity, dict),
          "missing_validated_counts")
    sections = scan.get("Results")
    _need(isinstance(sections, list) and len(sections) > 0,
          "no_trivy_results")
    observed: dict[str, Counter[str]] = {name: Counter() for name in CLASSES}
    covered: set[str] = set()
    records: list[dict[str, str]] = []
    for section in sections:
        _need(isinstance(section, dict), "invalid_trivy_section")
        kind = section.get("Class")
        _need(kind in CLASSES, "unrecognized_trivy_class")
        if kind == "os-pkgs":
            _need(section.get("Type") == "alpine",
                  "wrong_trivy_os_package_family")
        covered.add(kind)
        vulns = section.get("Vulnerabilities")
        _need(vulns is None or isinstance(vulns, list),
              "invalid_trivy_vulnerabilities")
        for issue in vulns or []:
            _need(isinstance(issue, dict), "invalid_vulnerability_record")
            level = issue.get("Severity", "UNKNOWN")
            _need(level in LEVELS, "invalid_vulnerability_severity")
            identity = _public(issue.get("VulnerabilityID"), "cve_id")
            _need(bool(_CVE.fullmatch(identity)), "invalid_public_cve_id")
            package = _public(issue.get("PkgName"), "package")
            installed = _public(issue.get("InstalledVersion"), "installed_version")
            fixed = _public(issue.get("FixedVersion", ""), "fixed_version", empty=True)
            observed[kind][level] += 1
            records.append({
                "severity": level,
                "source": kind,
                "id": identity,
                "package": package,
                "installed": installed,
                "trivy_fixed_version": fixed or "",
                "manual_disposition": "NOT_REVIEWED",
                "patch_hint": ("FIX_VERSION_REPORTED_REVIEW_UPSTREAM"
                               if fixed else "NO_FIX_VERSION_REPORTED_REVIEW_UPSTREAM"),
            })
    _need(covered == set(CLASSES), "incomplete_os_or_python_trivy_coverage")
    for kind in CLASSES:
        expected = by_class.get(kind)
        _need(isinstance(expected, dict), "missing_validated_class")
        for level in LEVELS:
            count = observed[kind][level]
            _need(type(expected.get(level)) is int and expected[level] == count,
                  "scan_vs_validated_class_count_mismatch")
    totals = {level: sum(observed[k][level] for k in CLASSES)
              for level in LEVELS}
    for level in LEVELS:
        _need(type(by_severity.get(level)) is int
              and by_severity[level] == totals[level],
              "scan_vs_validated_total_count_mismatch")
    count_ids = len({r["id"] for r in records
                     if r["severity"] in {"HIGH", "CRITICAL"}})
    _need(findings.get("high_critical_unique_ids") == count_ids,
          "scan_vs_validated_blocker_ids_mismatch")
    gate = ("BLOCKED_HIGH_OR_CRITICAL" if totals["HIGH"] or totals["CRITICAL"]
            else "REVIEW_REQUIRED_NONBLOCKING" if sum(totals.values())
            else "NO_KNOWN_FINDINGS_AT_SCAN_TIME")
    _need(validated.get("vulnerability_gate") == gate,
          "scan_vs_validated_gate_mismatch")
    status = ("BLOCKED_HIGH_OR_CRITICAL" if totals["HIGH"] or totals["CRITICAL"]
              else "BLOCKED_UNKNOWN_SEVERITY" if totals["UNKNOWN"]
              else "MANUAL_RELEASE_SECURITY_REVIEW_REQUIRED")
    records.sort(key=lambda r: (
        LEVELS.index(r["severity"]), r["source"], r["id"], r["package"],
        r["installed"], r["trivy_fixed_version"],
    ))
    return {
        "scope": "DOCKER_09_LOCAL_PREPUBLISH_REVIEW",
        "status": status,
        "reviewed_source_sha": revision,
        "platform": platform,
        "image": image,
        "local_image_id": _public(metadata.get("ImageID"), "image_id"),
        "base_image": BASE,
        "scanner_db": db,
        "package_inventory": dict(inventory),
        "affected_package_vulnerability_records": totals,
        "unique_vulnerability_ids": len({r["id"] for r in records}),
        "manual_findings": records,
        "manual_review_completed": False,
        "sbom_locally_validated": True,
        "sbom_signed": False,
        "build_provenance_attested": False,
        "image_signed": False,
        "release_proposal": plan,
        "ghcr_image_status": "NOT_PUBLISHED",
        "remote_index_digest": None,
        "release_ready": False,
        "release_authorized": False,
        "separate_user_release_approval_required": True,
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        _need(0 < len(raw) <= 64 * 1024 * 1024, "bad_input_file_size")
        parsed = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise PreReleaseReviewError("invalid_input_json") from None
    _need(isinstance(parsed, dict), "input_must_be_object")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review local medium/low CVEs; NEVER publish/approve"
    )
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--validated-report", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = review_pre_release(
            scan=_read(args.scan), validated=_read(args.validated_report),
            revision=args.revision, platform=args.platform, image=args.image,
            version=args.version,
        )
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        # Only PUBLIC package metadata; never log raw scan or environment.
        print("PREPUBLISH_MANUAL_CVE_REVIEW=" + json.dumps({
            "platform": report["platform"],
            "status": report["status"],
            "counts": report["affected_package_vulnerability_records"],
            "findings": report["manual_findings"],
            "release_ready": False,
            "release_authorized": False,
            "ghcr": "NOT_PUBLISHED",
        }, sort_keys=True))
        if report["status"] != "MANUAL_RELEASE_SECURITY_REVIEW_REQUIRED":
            parser.error("new_high_critical_or_unknown_severity_blocks_ci")
    except (PreReleaseReviewError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
