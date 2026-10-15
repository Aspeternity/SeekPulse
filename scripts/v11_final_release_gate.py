"""Docker-11: fail-closed FINAL LOCAL release evidence review. NEVER publish.

Re-validate the raw current-image Trivy/CycloneDX/DB/inspect inputs with the
existing Docker-04 and Docker-09 security auditors before issuing an explicitly
UNAUTHORIZED readiness *evidence* report. 0 findings is NOT release consent.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from scripts.v11_pre_release_review import (
    BASE, LEVELS, PLATFORMS, PreReleaseReviewError, review_pre_release,
)
from scripts.v11_release_policy import draft_release_plan, validate_revision
from scripts.v11_security_evidence import (
    SecurityEvidenceError, verify_security_evidence,
)

_HEX_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE = "https://github.com/Aspeternity/SeekPulse"
_BUILD_VERSION = "0.0.0-ci"


class FinalReleaseGateError(ValueError):
    """Local evidence is missing, inconsistent, stale or still vulnerable."""


def _need(value: bool, error: str) -> None:
    if not value:
        raise FinalReleaseGateError(error)


def evaluate_final_release_evidence(
    *,
    scan: dict[str, Any],
    sbom: dict[str, Any],
    db_metadata: dict[str, Any],
    image_inspect: dict[str, Any],
    validated: dict[str, Any],
    prepublish_review: dict[str, Any],
    revision: str,
    platform: str,
    image: str,
    version: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Check each locally built platform, never infer a remote multiarch digest.

    A separate same-HEAD Docker-03 OCI check and **future** actual GHCR
    manifest/digest verification are indispensable; neither is supplied here.
    """
    validate_revision(revision)
    _need(platform in PLATFORMS, "unsupported_release_platform")
    _need(isinstance(scan, dict) and isinstance(sbom, dict)
          and isinstance(db_metadata, dict) and isinstance(image_inspect, dict)
          and isinstance(validated, dict) and isinstance(prepublish_review, dict),
          "missing_or_invalid_security_evidence")
    current = now if now is not None else datetime.now(timezone.utc)
    _need(current.tzinfo is not None, "naive_audit_clock")
    current = current.astimezone(timezone.utc)
    expected_plan = draft_release_plan(version, revision)

    # Do not trust a pre-computed report alone. Re-run BOTH validators against
    # the actual raw inputs that CI just obtained from this exact local image.
    actual = verify_security_evidence(
        scan=scan, sbom=sbom, db_metadata=db_metadata,
        image_inspect=image_inspect, platform=platform,
        image_tag=image, os_family="alpine", now=current,
    )
    _need(validated == actual, "validated_report_does_not_match_raw_inputs")
    expected_review = review_pre_release(
        scan=scan, validated=actual, revision=revision,
        platform=platform, image=image, version=version, now=current,
    )
    _need(prepublish_review == expected_review,
          "prepublish_review_does_not_match_raw_inputs")

    _need(expected_review["manual_review_completed"] is False
          and expected_review["sbom_locally_validated"] is True
          and expected_review["sbom_signed"] is False
          and expected_review["image_signed"] is False
          and expected_review["build_provenance_attested"] is False,
          "falsely_claimed_supply_chain_attestations")
    _need(expected_review["base_image"] == BASE
          and expected_review["release_proposal"] == expected_plan,
          "base_or_release_proposal_identity_mismatch")

    totals = expected_review["affected_package_vulnerability_records"]
    _need(all(type(totals.get(level)) is int and totals[level] == 0
              for level in LEVELS),
          "nonzero_or_missing_vulnerability_findings")
    _need(expected_review["status"] == "MANUAL_RELEASE_SECURITY_REVIEW_REQUIRED",
          "security_evidence_not_manual_review_status")
    _need(expected_review["manual_findings"] == []
          and expected_review["unique_vulnerability_ids"] == 0,
          "nonzero_or_hidden_vulnerability_details")
    _need(actual["vulnerability_gate"] == "NO_KNOWN_FINDINGS_AT_SCAN_TIME",
          "vulnerability_gate_not_clean")

    _need(image_inspect.get("Os") == "linux"
          and image_inspect.get("Architecture") == platform.split("/")[1],
          "runtime_platform_mismatch")
    image_id = image_inspect.get("Id")
    _need(isinstance(image_id, str)
          and _HEX_DIGEST.fullmatch(image_id) is not None
          and expected_review["local_image_id"] == image_id,
          "local_image_sha_mismatch")
    config = image_inspect.get("Config")
    _need(isinstance(config, dict), "missing_docker_runtime_config")
    labels = config.get("Labels")
    _need(isinstance(labels, dict), "missing_oci_source_labels")
    required_labels = {
        "org.opencontainers.image.title": "SeekPulse",
        "org.opencontainers.image.source": _SOURCE,
        "org.opencontainers.image.revision": revision,
        "org.opencontainers.image.version": _BUILD_VERSION,
        "org.opencontainers.image.licenses": "MIT",
    }
    for name, value in required_labels.items():
        _need(labels.get(name) == value, "mismatched_oci_label:" + name)
    _need(config.get("User") == "10001:10001"
          and config.get("Entrypoint") == ["python", "-m", "app.v11_main"]
          and config.get("Cmd") == ["--run"],
          "unexpected_runtime_security_contract")
    _need(image_inspect.get("RepoDigests") in ([], None),
          "false_published_registry_digest")
    baked_env = config.get("Env")
    _need(isinstance(baked_env, list)
          and all(isinstance(v, str) and "=" in v for v in baked_env),
          "invalid_runtime_environment_inventory")
    keys = {entry.split("=", 1)[0] for entry in baked_env}
    disallowed = {
        "BOT_TOKEN", "ALLOWED_USER_IDS", "GITHUB_TOKEN", "GH_TOKEN",
        "SEEKPULSE_TG_API_HASH", "SEEKPULSE_TG_SESSION",
        "SEEKPULSE_WEB_PASSWORD_HASH", "SEEKPULSE_ADMIN_TG_USER_ID",
    }
    _need(not (keys & disallowed)
          and not any(key.startswith(("SEEKPULSE_PUSH_", "GHCR_"))
                      for key in keys),
          "secret_baked_into_local_image")

    _need(actual["release_ready"] is False
          and actual["release_authorized"] is False
          and actual["ghcr_image_status"] == "NOT_PUBLISHED"
          and actual["remote_index_digest"] is None
          and expected_review["release_ready"] is False
          and expected_review["release_authorized"] is False
          and expected_review["ghcr_image_status"] == "NOT_PUBLISHED"
          and expected_review["remote_index_digest"] is None,
          "remote_release_permission_or_digest_forged")
    _need(expected_plan["status"] == "NOT_AUTHORIZED_NOT_PUBLISHED"
          and expected_plan["remote_index_digest"] is None
          and expected_plan["approved_compose_reference"] is None
          and expected_plan["requires_separate_user_approval"] is True,
          "unapproved_registry_publication")

    return {
        "status": "LOCAL_EVIDENCE_CLEAN_AWAITING_MANUAL_RELEASE_APPROVAL",
        "scope": "DOCKER_11_LOCAL_SECURITY_AND_SUPPLY_CHAIN_REVIEW",
        "reviewed_source_sha": revision,
        "platform": platform,
        "image": image,
        "local_image_id": image_id,
        "base_image": BASE,
        "build_version": _BUILD_VERSION,
        "scanner_db": expected_review["scanner_db"],
        "package_inventory": expected_review["package_inventory"],
        "affected_package_vulnerability_records": dict(totals),
        "known_vulnerability_records_at_scan_time": 0,
        "local_cyclonedx_sbom_validated": True,
        "local_oci_source_labels_validated": True,
        "remote_oci_index_verified": False,
        "remote_sbom_attestation_verified": False,
        "remote_signature_verified": False,
        "release_proposal": expected_plan,
        "manual_release_security_review_completed": False,
        "ghcr_image_status": "NOT_PUBLISHED",
        "remote_index_digest": None,
        "release_ready": False,
        "release_authorized": False,
        "requires_separate_user_release_approval": True,
        "outstanding_release_gates": [
            "MANUAL_SECURITY_RISK_ACCEPTANCE",
            "FINAL_PUBLISHABLE_BYTES_AND_MULTIARCH_INDEX_VALIDATION",
            "GHCR_PUBLICATION_SEPARATE_APPROVAL",
            "REMOTE_REGISTRY_INDEX_DIGEST_AND_PROVENANCE_ATTESTATION",
            "USER_NAS_PVE_DEPLOYMENT_SEPARATE_APPROVAL",
        ],
    }


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        _need(0 < len(raw) <= 64 * 1024 * 1024, "invalid_evidence_input_size")
        obj = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise FinalReleaseGateError("invalid_evidence_input_json") from None
    _need(isinstance(obj, dict), "evidence_input_not_object")
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check exact local GHCR preflight inputs; NEVER publish or approve"
    )
    for name in ("scan", "sbom", "db-metadata", "inspect",
                 "validated-report", "prepublish-review", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    parser.add_argument("--image", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    try:
        report = evaluate_final_release_evidence(
            scan=_load(args.scan), sbom=_load(args.sbom),
            db_metadata=_load(args.db_metadata), image_inspect=_load(args.inspect),
            validated=_load(args.validated_report),
            prepublish_review=_load(args.prepublish_review),
            revision=args.revision, platform=args.platform,
            image=args.image, version=args.version,
        )
        args.output.write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        # Only public metadata: do not print inspect.Env or scan raw payload.
        print("FINAL_GHCR_OFFLINE_PREPUBLISH_GATE=" + json.dumps({
            "platform": report["platform"],
            "source_sha": report["reviewed_source_sha"],
            "status": report["status"],
            "inventory": report["package_inventory"],
            "vulnerabilities": report["affected_package_vulnerability_records"],
            "scanner_db": report["scanner_db"],
            "ghcr": report["ghcr_image_status"],
            "release_ready": False,
            "release_authorized": False,
        }, sort_keys=True))
    except (FinalReleaseGateError, PreReleaseReviewError,
            SecurityEvidenceError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
