"""Offline-only GHCR image naming policy. NO publishing or network operations.

A locally built OCI digest is NOT the future GHCR multiarch index digest.
This module never creates a Git tag, Release, package or registry reference.
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

IMAGE_REPOSITORY = "ghcr.io/aspeternity/seekpulse"
PLATFORMS = ("linux/amd64", "linux/arm64")

_RELEASE_TAG = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-rc\.([1-9][0-9]*))?$"
)
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_REFERENCE = re.compile(
    r"^ghcr\.io/aspeternity/seekpulse@sha256:[0-9a-f]{64}$"
)


def validate_version(value: str) -> str:
    """Require a fully qualified, uniquely approved future release tag."""
    if not isinstance(value, str) or _RELEASE_TAG.fullmatch(value) is None:
        raise ValueError("invalid_release_version")
    return value


def validate_revision(value: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise ValueError("invalid_source_revision")
    return value


def validate_immutable_reference(value: str) -> str:
    """Validate syntax only: NEVER imply remote existence or verification."""
    if not isinstance(value, str) or _DIGEST_REFERENCE.fullmatch(value) is None:
        raise ValueError("invalid_immutable_image_reference")
    return value


def draft_release_plan(version: str, revision: str) -> dict[str, Any]:
    """An auditable unapproved suggestion, deliberately without a digest."""
    version = validate_version(version)
    revision = validate_revision(revision)
    return {
        "status": "NOT_AUTHORIZED_NOT_PUBLISHED",
        "repository": IMAGE_REPOSITORY,
        "proposed_tag": f"{IMAGE_REPOSITORY}:{version}",
        "source_revision": revision,
        "platforms": list(PLATFORMS),
        "remote_index_digest": None,
        "approved_compose_reference": None,
        "requires_separate_user_approval": True,
        "requires_remote_digest_verification_after_publish": True,
        "requires_release_security_review": True,
        "floating_tags_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Output a proposed V1.1 release plan, never publish"
    )
    sub = parser.add_subparsers(dest="operation", required=True)
    plan = sub.add_parser("plan", help="Print a non-published JSON plan")
    plan.add_argument("--version", required=True)
    plan.add_argument("--revision", required=True)
    verify = sub.add_parser(
        "validate-ref", help="Check digest-ref syntax without accessing GHCR"
    )
    verify.add_argument("--ref", required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "plan":
            result = draft_release_plan(args.version, args.revision)
        else:
            result = {
                "syntax_valid": bool(validate_immutable_reference(args.ref)),
                "remote_verified": False,
            }
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
