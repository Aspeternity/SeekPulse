"""Docker-06: reconcile Debian OS High CVEs with an ACTUAL local Trivy scan.

The output is an evidence-only risk inventory, never a vulnerability waiver,
an exploitability claim, or permission to publish a registry image.  This
module does not fetch external hosts, require secrets, or touch user systems.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any


class OSHighEvidenceError(ValueError):
    """Missing, inconsistent or forged local OS vulnerability evidence."""


_HISTORICAL_OS_CVES = {
    "CVE-2025-69720": "ncurses",
    "CVE-2026-16742": "systemd",
    "CVE-2026-54369": "acl",
    "CVE-2026-76642": "util-linux",
    "CVE-2026-78408": "util-linux",
    "CVE-2026-78409": "util-linux",
    "CVE-2026-78410": "util-linux",
    "CVE-2026-9538": "perl",
}
_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
_VALID_PLATFORMS = {"linux/amd64", "linux/arm64"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,119}$")
_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+:~@_-]{0,149}$")


def _need(valid: bool, message: str) -> None:
    if not valid:
        raise OSHighEvidenceError(message)


def _pkg_info(v: dict[str, Any]) -> tuple[str, str, str]:
    name = v.get("PkgName")
    installed = v.get("InstalledVersion")
    fixed = v.get("FixedVersion") or ""
    _need(isinstance(name, str) and _TEXT.fullmatch(name) is not None,
          "invalid_os_package_name")
    _need(isinstance(installed, str) and _TEXT.fullmatch(installed) is not None,
          "invalid_os_installed_version")
    _need(isinstance(fixed, str) and
          (not fixed or _TEXT.fullmatch(fixed) is not None),
          "invalid_os_fixed_version")
    return name, installed, fixed


def review_os_high(
    *,
    scan: dict[str, Any],
    validated_report: dict[str, Any],
    platform: str,
    image: str,
) -> dict[str, Any]:
    """Check scan identity + both package classes + exact high counts.

    This function is only for the V1.1 full-runtime Trivy evidence previously
    validated by scripts/v11_security_evidence.py (fresh DB, SBOM, image ID).
    An absent historical CVE is NOT automatically considered fixed.
    """
    _need(platform in _VALID_PLATFORMS, "invalid_expected_platform")
    _need(isinstance(image, str) and image == f"seekpulse-security-local:{platform.split('/')[1]}",
          "invalid_expected_local_image")

    _need(isinstance(validated_report, dict), "missing_validated_report")
    _need(validated_report.get("evidence") == "VALID_LOCAL_SCAN_NOT_PUBLISHED",
          "not_validated_local_scan")
    _need(validated_report.get("platform") == platform, "report_platform_mismatch")
    _need(validated_report.get("image") == image, "report_image_mismatch")
    _need(validated_report.get("release_authorized") is False and
          validated_report.get("release_ready") is False,
          "invalid_release_authorization")
    _need(validated_report.get("ghcr_image_status") == "NOT_PUBLISHED" and
          validated_report.get("remote_index_digest") is None,
          "unexpected_registry_publication")
    db = validated_report.get("scanner_db")
    _need(isinstance(db, dict) and
          all(isinstance(db.get(k), str) and db[k] for k in
              ("updated_at", "downloaded_at", "next_update")),
          "missing_validated_scanner_db")

    _need(isinstance(scan, dict) and type(scan.get("SchemaVersion")) is int,
          "invalid_trivy_schema")
    _need(scan.get("ArtifactType") == "container_image" and
          scan.get("ArtifactName") == image,
          "mismatched_scanned_image")
    meta = scan.get("Metadata")
    _need(isinstance(meta, dict), "missing_image_metadata")
    os_meta = meta.get("OS")
    _need(isinstance(os_meta, dict) and os_meta.get("Family") == "debian",
          "wrong_os_family")
    img_id = meta.get("ImageID")
    _need(isinstance(img_id, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", img_id)
          is not None, "invalid_local_image_id")
    results = scan.get("Results")
    _need(isinstance(results, list) and results, "no_trivy_results")

    counts: dict[str, Counter[str]] = {
        "os-pkgs": Counter(), "lang-pkgs": Counter()
    }
    affected: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    seen: set[str] = set()
    all_high_ids: set[str] = set()
    for section in results:
        _need(isinstance(section, dict), "invalid_scan_section")
        kind = section.get("Class")
        _need(kind in counts, "unknown_scan_class")
        seen.add(kind)
        items = section.get("Vulnerabilities")
        _need(items is None or isinstance(items, list), "invalid_vulnerabilities")
        for vuln in items or []:
            _need(isinstance(vuln, dict), "invalid_vulnerability_entry")
            severity = vuln.get("Severity", "UNKNOWN")
            _need(severity in _SEVERITIES, "unknown_severity")
            vid = vuln.get("VulnerabilityID")
            _need(isinstance(vid, str) and _ID.fullmatch(vid) is not None,
                  "invalid_vulnerability_id")
            counts[kind][severity] += 1
            if severity in ("HIGH", "CRITICAL"):
                all_high_ids.add(vid)
                if kind == "os-pkgs":
                    affected[vid].add(_pkg_info(vuln))
    _need(seen == set(counts), "os_or_language_scan_missing")
    findings = validated_report.get("findings")
    _need(isinstance(findings, dict), "missing_validated_findings")
    by_class = findings.get("by_package_class")
    _need(isinstance(by_class, dict), "missing_validated_class_counts")
    for cls, severities in counts.items():
        declared = by_class.get(cls)
        _need(isinstance(declared, dict), "missing_class_summary")
        for level in _SEVERITIES:
            _need(type(declared.get(level)) is int and
                  declared[level] == severities[level],
                  "trivy_vs_validated_summary_mismatch")
    declared_total = findings.get("by_severity")
    _need(isinstance(declared_total, dict), "missing_total_severity_summary")
    for level in _SEVERITIES:
        _need(type(declared_total.get(level)) is int and
              declared_total[level] == sum(c[level] for c in counts.values()),
              "total_severity_mismatch")
    _need(findings.get("high_critical_unique_ids") == len(all_high_ids),
          "unique_high_id_count_mismatch")

    has_blockers = bool(all_high_ids)
    existing_gate = validated_report.get("vulnerability_gate")
    _need(existing_gate == (
        "BLOCKED_HIGH_OR_CRITICAL" if has_blockers
        else ("REVIEW_REQUIRED_NONBLOCKING"
              if sum(declared_total.values()) else "NO_KNOWN_FINDINGS_AT_SCAN_TIME")
    ), "existing_release_gate_inconsistent")
    historical = {}
    for cve, source_package in sorted(_HISTORICAL_OS_CVES.items()):
        packages = sorted(affected.get(cve, ()))
        historical[cve] = {
            "source_package": source_package,
            "scan_state": ("HIGH_REPORTED" if packages else
                           "NOT_REPORTED_VERIFY_UPSTREAM"),
            "affected_package_matches": len(packages),
            "affected_packages": [
                {"package": n, "installed": version,
                 "fixed": fix or None}
                for n, version, fix in packages
            ],
        }
    additional = sorted(set(affected).difference(_HISTORICAL_OS_CVES))

    return {
        "scope": "LOCAL_RUNTIME_DEBIAN_OS_HIGH_REVIEW",
        "platform": platform,
        "local_image": image,
        "scanner_db": dict(db),
        "os_high_records": counts["os-pkgs"]["HIGH"],
        "os_critical_records": counts["os-pkgs"]["CRITICAL"],
        "os_distinct_high_critical_ids": len(affected),
        "historical_high_cves": historical,
        "other_high_critical_cve_ids": additional,
        "source_status_snapshot": "DEBIAN_TRACKER_2026-10-15_RECHECK_REQUIRED",
        "risk_gate": existing_gate,
        "release_authorized": False,
        "release_ready": False,
        "ghcr_image_status": "NOT_PUBLISHED",
        "remote_index_digest": None,
        "missing_id_does_not_prove_fixed": True,
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        _need(0 < len(raw) < 64 * 1024 * 1024, "bad_evidence_file_size")
        value = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise OSHighEvidenceError("invalid_os_high_evidence_json") from None
    _need(isinstance(value, dict), "evidence_is_not_object")
    return value


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Review local Debian OS High; never release")
    p.add_argument("--scan", type=Path, required=True)
    p.add_argument("--validated-report", type=Path, required=True)
    p.add_argument("--platform", choices=sorted(_VALID_PLATFORMS), required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        evidence = review_os_high(
            scan=_read(args.scan), validated_report=_read(args.validated_report),
            platform=args.platform, image=args.image
        )
    except OSHighEvidenceError as exc:
        p.error(str(exc))
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "OS_HIGH_REVIEW=VALID "
        f"platform={args.platform} "
        f"os_high_records={evidence['os_high_records']} "
        f"distinct_os_high_ids={evidence['os_distinct_high_critical_ids']} "
        f"release_gate={evidence['risk_gate']} "
        "GHCR_STATUS=NOT_PUBLISHED RELEASE_AUTHORIZED=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
